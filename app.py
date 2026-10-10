"""Verity backend. Proof and blockchain engines sit behind adapters (see ProofEngine / ChainAdapter)."""
import hashlib, json, os, sqlite3, uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import Flask, g, jsonify, render_template, request

DB = os.environ.get("VERITY_DB", "verity.db")
app = Flask(__name__, static_folder="static")
now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
canon = lambda o: json.dumps(o, sort_keys=True, separators=(",", ":"))  # commitment-format v1
sha = lambda o: hashlib.sha256((o if isinstance(o, str) else canon(o)).encode()).hexdigest()
COMMIT_V = "verity-commit/v1"

PROGRAMS = {}
for _id, _rate in (("bonus-10pct@1.0.0", "0.10"), ("bonus-15pct@1.0.0", "0.15")):
    spec = {"id": _id, "rule": f"bonus = salary * {_rate}", "rate": _rate}
    PROGRAMS[_id] = {**spec, "digest": sha(spec)}
AGREED = "bonus-10pct@1.0.0"

# ---------- adapters ----------
class SimulatedProofEngine:
    """SIMULATION ONLY. Not RISC Zero. Its 'seal' is a plain SHA-256 anyone can forge: never real verification.
    Replace with a class exposing the same execute/prove/verify methods once the RISC Zero interface is confirmed."""
    mode, name = "SIMULATION", "Simulated proof engine (not RISC Zero)"
    def execute(self, program_id, inputs):
        return str((Decimal(inputs["salary"]) * Decimal(PROGRAMS[program_id]["rate"])).quantize(Decimal("0.01")))
    def prove(self, program_id, inputs, output):
        j = {"program_id": program_id, "program_digest": PROGRAMS[program_id]["digest"],
             "input_commitment": sha(inputs), "output": output}
        return {"receipt_ref": "sim-" + sha(j)[:16], "mode": self.mode, "journal": j, "seal": sha(["sim-seal", j])}
    def verify(self, receipt):
        ok = receipt.get("seal") == sha(["sim-seal", receipt.get("journal")])
        return {"mode": self.mode, "status": "SIMULATED" if ok else "FAILED", "verified_at": now(),
                "detail": "Simulated seal consistent with journal (NOT a cryptographic proof)." if ok
                else "Simulated seal does not match journal contents."}

class DisabledChain:
    name = "Blockchain adapter disabled (network not confirmed)"
    def record(self, commitment):
        return {"status": "NOT_SUBMITTED", "tx": None, "detail": "No network configured; nothing was submitted."}

ENGINE, CHAIN = SimulatedProofEngine(), DisabledChain()

# ---------- db ----------
SCHEMA = """create table if not exists requests(id text primary key, type text, inputs text, input_commitment text,
 program_id text, program_digest text, commitment_version text, status text, chain_status text, chain_meta text,
 submission text, created_at text);
create table if not exists runs(id text primary key, request_id text, scenario text, mode text, verdict text,
 report text, created_at text);
create table if not exists audit(seq integer primary key autoincrement, ts text, request_id text, type text,
 status text, evidence text, prev_hash text, hash text);"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def _close(_):
    d = g.pop("db", None)
    if d: d.close()

with sqlite3.connect(DB) as _c: _c.executescript(SCHEMA)

def log(rid, typ, status, evidence=None):
    """Hash-chained application log: tamper-evident only to someone holding a trusted copy of the head hash."""
    d = db(); last = d.execute("select hash from audit order by seq desc limit 1").fetchone()
    prev, ts, ev = (last[0] if last else "0" * 64), now(), canon(evidence or {})
    cur = d.execute("insert into audit(ts,request_id,type,status,evidence,prev_hash,hash) values(?,?,?,?,?,?,?)",
                    (ts, rid, typ, status, ev, prev, sha([prev, ts, rid, typ, status, ev])))
    d.commit(); return f"audit:{cur.lastrowid}"

def req_row(r):
    o = dict(r); o["inputs"] = json.loads(o["inputs"]); o["chain_meta"] = json.loads(o["chain_meta"] or "{}")
    o["has_submission"] = bool(o.pop("submission")); o["agreed_program"] = PROGRAMS[o["program_id"]]
    return o

def get_req(rid):
    return db().execute("select * from requests where id=?", (rid,)).fetchone()

def err(msg, code=400): return jsonify(error=msg), code

# ---------- scenarios ----------
SCENARIOS = {
    "normal": ("Normal computation", "Provider runs the agreed program on the committed inputs and returns the true result."),
    "altered_output": ("Altered output", "Provider's proof is honest, but the answer delivered to the requester is inflated by 60%."),
    "altered_input": ("Altered input", "Provider computes on a salary 60% higher than the committed one. Treated as a separate test input; the original request is untouched."),
    "wrong_program": ("Different program", "Provider proves execution of a 15% bonus program instead of the agreed 10% one."),
    "invalid_proof": ("Invalid proof", "Provider returns correct-looking values with a forged proof seal."),
}

def make_submission(req, scenario):
    inputs, pid = json.loads(req["inputs"]), req["program_id"]
    if scenario == "normal": return json.loads(req["submission"])
    out = ENGINE.execute(pid, inputs); sub = {"claimed_output": out, "receipt": ENGINE.prove(pid, inputs, out)}
    if scenario == "altered_output":
        sub["claimed_output"] = str((Decimal(out) * Decimal("1.6")).quantize(Decimal("0.01")))
    elif scenario == "altered_input":
        bad = {"salary": str((Decimal(inputs["salary"]) * Decimal("1.6")).quantize(Decimal("0.01")))}
        o2 = ENGINE.execute(pid, bad); sub = {"claimed_output": o2, "receipt": ENGINE.prove(pid, bad, o2), "test_inputs": bad}
    elif scenario == "wrong_program":
        o2 = ENGINE.execute("bonus-15pct@1.0.0", inputs)
        sub = {"claimed_output": o2, "receipt": ENGINE.prove("bonus-15pct@1.0.0", inputs, o2)}
    elif scenario == "invalid_proof":
        sub["receipt"]["seal"] = sha("forged")
    return sub

# ---------- investigations ----------
def investigate(req, sub, rid):
    rec = sub.get("receipt"); j = rec["journal"] if rec else None
    v = ENGINE.verify(rec) if rec else {"mode": ENGINE.mode, "status": "INCOMPLETE", "verified_at": now(), "detail": "No receipt supplied."}
    trusted = j is not None and v["status"] != "FAILED"
    ok = "SIMULATED" if ENGINE.mode == "SIMULATION" else "PASSED"
    inputs = json.loads(req["inputs"]); n = [0]
    def ev(label, value):
        n[0] += 1; return {"ref": f"{rid}/E{n[0]}", "label": label, "value": value}
    def finding(i, title, question, code, same, exp, rcv, evid, texts):
        st = ok if same else "FAILED"
        if not trusted: st, code = "INCOMPLETE", "NO_TRUSTED_PROOF_VALUES"
        elif same: code = "OK"
        return {"n": i, "title": title, "question": question, "status": st, "code": code, "mode": ENGINE.mode,
                "expected": exp, "received": rcv, "evidence": evid,
                "explanation": texts[2] if not trusted else texts[0] if same else texts[1]}
    claimed = sub.get("claimed_output")
    f1 = finding(1, "Output Integrity", "Was the returned answer changed after computation?", "OUTPUT_MISMATCH",
        trusted and Decimal(claimed) == Decimal(j["output"]),
        {"label": "Proof-bound output", "value": j and "₹" + j["output"]}, {"label": "Received output", "value": "₹" + claimed},
        [ev("claimed_output", claimed), ev("journal.output", j and j["output"])],
        ["Received output equals the output bound to the proof.",
         "Received output differs from the proof-bound output. The answer was changed or not produced by the proven run. This does not show who changed it or why.",
         "Proof failed verification, so its bound output cannot be trusted for comparison."])
    f2 = finding(2, "Input Integrity", "Were the original inputs altered?", "INPUT_MISMATCH",
        trusted and j["input_commitment"] == req["input_commitment"],
        {"label": "Original commitment (stored at creation)", "value": req["input_commitment"][:20] + "…"},
        {"label": "Proof input commitment", "value": j and j["input_commitment"][:20] + "…"},
        [ev("original_inputs", inputs), ev("original_commitment", req["input_commitment"]),
         ev("journal.input_commitment", j and j["input_commitment"]), ev("test_inputs (scenario only)", sub.get("test_inputs"))],
        ["The proof's input commitment equals the commitment recorded when the request was created.",
         "The proof was computed over different inputs than the ones committed. Commitment comparison reveals a difference, not its cause.",
         "Proof failed verification, so its input commitment cannot be trusted for comparison."])
    f3 = finding(3, "Program Integrity", "Was the agreed program used?", "PROGRAM_MISMATCH",
        trusted and j["program_digest"] == req["program_digest"],
        {"label": "Agreed program", "value": req["program_id"]}, {"label": "Proven program", "value": j and j["program_id"]},
        [ev("agreed_digest", req["program_digest"]), ev("journal.program_digest", j and j["program_digest"])],
        ["The proven program digest equals the agreed program digest.",
         "The proof is bound to a different program than the agreed one. A valid proof of the wrong program proves nothing about the agreed rule.",
         "Proof failed verification, so its program identity cannot be trusted for comparison."])
    st4 = v["status"] if v["status"] != "SIMULATED" or ENGINE.mode == "SIMULATION" else "PASSED"
    f4 = {"n": 4, "title": "Proof Validity", "question": "Is the cryptographic proof valid?", "status": st4,
          "code": {"FAILED": "PROOF_INVALID", "INCOMPLETE": "NO_PROOF"}.get(st4, "OK"), "mode": v["mode"],
          "expected": {"label": "Verifier result", "value": "valid receipt"}, "received": {"label": "Verifier output", "value": v["status"]},
          "evidence": [ev("receipt_ref", rec and rec["receipt_ref"]), ev("verifier_detail", v["detail"]), ev("verified_at", v["verified_at"])],
          "explanation": v["detail"] + (" Simulation mode: this is NOT genuine cryptographic verification." if ENGINE.mode == "SIMULATION" else "")}
    return [f1, f2, f3, f4], v

def verdict_of(fs):
    s = {f["status"] for f in fs}
    return "REJECTED" if "FAILED" in s else "INCOMPLETE" if "INCOMPLETE" in s else "SIMULATION ONLY" if "SIMULATED" in s else "VERIFIED"

# ---------- API ----------
@app.get("/")
def index(): return render_template("index.html")

@app.get("/api/integrations")
def integrations():
    return jsonify(proof_engine={"name": ENGINE.name, "mode": ENGINE.mode, "genuine_verification": False},
                   blockchain={"name": CHAIN.name, "enabled": False},
                   audit_note="Audit log is hash-chained in SQLite. It is application history, not independently anchored or immutable.")

@app.get("/api/scenarios")
def scenarios(): return jsonify([{"id": k, "title": t, "description": d} for k, (t, d) in SCENARIOS.items()])

@app.post("/api/requests")
def create():
    b = request.get_json(silent=True) or {}
    sal = b.get("salary")
    if isinstance(sal, bool) or not isinstance(sal, (int, float, str)): return err("salary must be a number")
    try: sal = Decimal(str(sal)).quantize(Decimal("0.01"))
    except InvalidOperation: return err("salary must be a number")
    if not sal.is_finite() or sal <= 0 or sal > Decimal("100000000"): return err("salary must be > 0 and ≤ 100,000,000")
    if b.get("agreed_rate_percent", 10) != 10 or b.get("program_id", AGREED) != AGREED:
        return err("MVP supports only the agreed 10% rule (bonus-10pct@1.0.0); the formula cannot be redefined")
    inputs, rid = {"salary": str(sal)}, "VRT-" + uuid.uuid4().hex[:8].upper()
    p = PROGRAMS[AGREED]
    db().execute("insert into requests values(?,?,?,?,?,?,?,?,?,?,?,?)", (rid, "employee_bonus", canon(inputs), sha(inputs), AGREED,
                 p["digest"], COMMIT_V, "CREATED", "NOT_SUBMITTED", "{}", None, now()))
    db().commit(); log(rid, "REQUEST_CREATED", "CREATED", {"input_commitment": sha(inputs), "program_digest": p["digest"]})
    return jsonify(req_row(get_req(rid))), 201

@app.get("/api/requests")
def list_requests():
    return jsonify([req_row(r) for r in db().execute("select * from requests order by created_at desc, rowid desc")])

@app.get("/api/requests/<rid>")
def one(rid):
    r = get_req(rid)
    return jsonify(req_row(r)) if r else err("not found", 404)

@app.post("/api/requests/<rid>/execute")
def execute(rid):
    r = get_req(rid)
    if not r: return err("not found", 404)
    if r["status"] in ("VERIFIED", "REJECTED"): return err(f"request already {r['status']}", 409)
    try:
        inputs = json.loads(r["inputs"]); out = ENGINE.execute(r["program_id"], inputs)
        log(rid, "COMPUTATION_EXECUTED", "EXECUTED", {"mode": ENGINE.mode})
        receipt = ENGINE.prove(r["program_id"], inputs, out)
        db().execute("update requests set submission=?, status='PROOF_GENERATED' where id=?",
                     (canon({"claimed_output": out, "receipt": receipt}), rid)); db().commit()
        log(rid, "PROOF_GENERATED", "PROOF_GENERATED", {"receipt_ref": receipt["receipt_ref"], "mode": ENGINE.mode})
    except Exception as e:  # keep the record intact, preserve failure, allow retry
        log(rid, "EXECUTION_FAILED", "FAILED", {"error": str(e)}); return err(f"execution failed: {e}", 502)
    return jsonify(req_row(get_req(rid)))

@app.post("/api/requests/<rid>/investigate")
def run_investigation(rid):
    r = get_req(rid); scenario = (request.get_json(silent=True) or {}).get("scenario", "normal")
    if not r: return err("not found", 404)
    if scenario not in SCENARIOS: return err("unknown scenario")
    if not r["submission"]: return err("execute the computation first", 409)
    sub = make_submission(r, scenario); run_id = "RUN-" + uuid.uuid4().hex[:8].upper()
    log(rid, "VERIFICATION_ATTEMPTED", "STARTED", {"run": run_id, "scenario": scenario})
    fs, v = investigate(r, sub, run_id); verdict = verdict_of(fs); refs = []
    for f in fs: refs.append(log(rid, f"INVESTIGATION_{f['n']}_{f['title'].split()[0].upper()}", f["status"], {"run": run_id, "code": f["code"]}))
    j = sub["receipt"]["journal"] if sub.get("receipt") else None
    limits = ["Proof engine is a SIMULATION: no genuine cryptographic verification took place." if ENGINE.mode == "SIMULATION" else "Real verifier used.",
              "A detected mismatch shows that values differ; it does not identify who changed them or establish intent.",
              "Commitments are stored in the same database as the request; they are not independently anchored until a blockchain adapter is connected.",
              "Audit log is application history (hash-chained), not an immutable record."]
    rep = {"run_id": run_id, "request_id": rid, "scenario": scenario, "scenario_title": SCENARIOS[scenario][0],
           "scenario_description": SCENARIOS[scenario][1], "generated_at": now(), "request": req_row(r), "mode": ENGINE.mode,
           "claimed_output": sub.get("claimed_output"), "proof_bound_output": j and j["output"],
           "agreed_program": r["program_id"], "proven_program": j and j["program_id"], "findings": fs, "verdict": verdict,
           "proof_status": v["status"], "blockchain_status": r["chain_status"], "limitations": limits, "audit_refs": refs}
    rep["audit_refs"].append(log(rid, "REPORT_GENERATED", verdict, {"run": run_id}))
    db().execute("insert into runs values(?,?,?,?,?,?,?)", (run_id, rid, scenario, ENGINE.mode, verdict, canon(rep), rep["generated_at"]))
    if scenario == "normal":  # only the real request lifecycle changes status; adversarial tests never do
        st = {"VERIFIED": "VERIFIED", "REJECTED": "REJECTED"}.get(verdict, "INVESTIGATION_INCOMPLETE")
        db().execute("update requests set status=? where id=?", (st, rid))
    db().commit(); return jsonify(rep)

@app.post("/api/requests/<rid>/record")
def record(rid):
    r = get_req(rid)
    if not r: return err("not found", 404)
    res = CHAIN.record({"version": COMMIT_V, "input_commitment": r["input_commitment"], "program_digest": r["program_digest"]})
    db().execute("update requests set chain_status=?, chain_meta=? where id=?", (res["status"], canon(res), rid)); db().commit()
    log(rid, "BLOCKCHAIN_RECORD_ATTEMPTED", res["status"], res); return jsonify(res)

@app.get("/api/requests/<rid>/reports")
def reports(rid):
    rows = db().execute("select id,scenario,verdict,mode,created_at from runs where request_id=? order by rowid desc", (rid,))
    return jsonify([dict(x) for x in rows])

@app.get("/api/reports/<run_id>")
def report(run_id):
    x = db().execute("select report from runs where id=?", (run_id,)).fetchone()
    return jsonify(json.loads(x[0])) if x else err("not found", 404)

@app.get("/api/audit")
def audit():
    q, a = "select * from audit where 1=1", []
    for col, key in (("request_id", "request_id"), ("status", "status"), ("type", "type")):
        if request.args.get(key): q += f" and {col} like ?"; a.append(f"%{request.args[key]}%")
    rows = db().execute(q + " order by seq desc limit 500", a)
    return jsonify([{**dict(x), "ref": f"audit:{x['seq']}", "evidence": json.loads(x["evidence"])} for x in rows])

@app.get("/api/dashboard")
def dashboard():
    d = db(); rs = [dict(x) for x in d.execute("select id,status,chain_status from requests")]
    count = lambda s: sum(1 for x in rs if x["status"] == s)
    runs = [dict(x) for x in d.execute("select id,request_id,scenario,verdict,mode,created_at,report from runs order by rowid desc limit 8")]
    for x in runs: x["findings"] = [{"title": f["title"], "status": f["status"], "code": f["code"]} for f in json.loads(x.pop("report"))["findings"]]
    return jsonify(total=len(rs), verified=count("VERIFIED"), rejected=count("REJECTED"),
                   pending=len(rs) - count("VERIFIED") - count("REJECTED"), simulation_only=d.execute(
                       "select count(distinct request_id) from runs where scenario='normal' and verdict='SIMULATION ONLY'").fetchone()[0],
                   chain_statuses={s: sum(1 for x in rs if x["chain_status"] == s) for s in {x["chain_status"] for x in rs}},
                   recent_requests=list(reversed(rs))[:6], recent_runs=runs)

if __name__ == "__main__":
    app.run(debug=True, port=5000)