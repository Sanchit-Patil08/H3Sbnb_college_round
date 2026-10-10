"""Verity backend. Proof and blockchain engines sit behind adapters (see ProofEngine / ChainAdapter)."""
import hashlib, importlib.util, json, os, sqlite3, subprocess, sys, uuid
from functools import wraps
from threading import Lock
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

if __name__ == "__main__" and importlib.util.find_spec("web3") is None:
    fallback_python = Path(__file__).resolve().parent / ".venv313" / "Scripts" / "python.exe"
    if fallback_python.is_file():
        print("web3 is missing from this interpreter; restarting with the project Python 3.13 environment.", flush=True)
        os.execv(str(fallback_python), [str(fallback_python), str(Path(__file__).resolve()), *sys.argv[1:]])

from flask import Flask, g, jsonify, render_template, request
from web3 import Web3

from services.blockchain import (
    ABI_ERROR,
    CONFIG_ERROR,
    account,
    contract,
    w3,
)
from services.risc0_engine import generate_proof, verify_receipt, proof_status

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

# Bound lock storage; serialize lifecycle changes per request in this local
# single-process server. Different requests can still prove concurrently.
_REQUEST_LOCKS = tuple(Lock() for _ in range(64))
_CHAIN_WRITE_LOCK = Lock()


def request_locked(handler):
    @wraps(handler)
    def wrapped(rid):
        with _REQUEST_LOCKS[int(sha(rid)[:8], 16) % len(_REQUEST_LOCKS)]:
            return handler(rid)
    return wrapped

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


class RealChain:
    name = "Local Hardhat commitment registry"

    @property
    def status(self):
        if CONFIG_ERROR:
            return {"enabled": False, "detail": CONFIG_ERROR}
        if ABI_ERROR:
            return {"enabled": False, "detail": ABI_ERROR}

        missing = [
            name for name, value in (
                ("BLOCKCHAIN_RPC_URL", w3),
                ("CONTRACT_ADDRESS", contract),
                ("VERIFIER_PRIVATE_KEY", account),
            )
            if value is None
        ]
        if missing:
            return {"enabled": False, "detail": f"Blockchain configuration is incomplete: missing {', '.join(missing)}."}

        try:
            if not w3.is_connected():
                return {"enabled": False, "detail": "The configured blockchain RPC is not responding."}
            chain_id = w3.eth.chain_id
        except Exception as exc:
            return {"enabled": False, "detail": f"Blockchain status check failed ({type(exc).__name__})."}

        if chain_id != 31337:
            return {"enabled": False, "detail": f"Connected to unexpected chain ID {chain_id}; expected 31337."}

        try:
            if not w3.eth.get_code(contract.address):
                return {"enabled": False, "detail": "No contract is deployed at CONTRACT_ADDRESS."}
            if contract.functions.verifier().call() != account.address:
                return {"enabled": False, "detail": "VERIFIER_PRIVATE_KEY does not match the contract verifier."}
        except Exception as exc:
            return {"enabled": False, "detail": f"Contract check failed ({type(exc).__name__})."}

        return {"enabled": True, "detail": "Connected to the configured audit contract on Hardhat chain 31337."}

    @property
    def enabled(self):
        return self.status["enabled"]

    def record(self, commitment):
        # All requests use one signer. Reserve/use its nonce serially, including
        # the duplicate-record check, to avoid parallel transaction collisions.
        with _CHAIN_WRITE_LOCK:
            return self._record(commitment)

    def _record(self, commitment):
        status = self.status
        if not status["enabled"]:
            return {"status": "NOT_SUBMITTED", "tx": None, "detail": status["detail"]}

        try:
            if commitment.get("proof_verified") is not True:
                return {"status": "NOT_SUBMITTED", "tx": None, "detail": "A verified RISC Zero receipt is required."}

            input_commitment = commitment["input_commitment"]
            program_digest = commitment["program_digest"]
            receipt_ref = commitment["receipt_ref"]
            output_value = commitment["output"]
            if (
                not isinstance(input_commitment, str)
                or len(input_commitment) != 64
                or not isinstance(program_digest, str)
                or len(program_digest) != 64
                or not isinstance(receipt_ref, str)
                or not receipt_ref.startswith("risc0-")
                or not isinstance(output_value, str)
            ):
                raise ValueError("Invalid proof commitment")

            input_hash = Web3.keccak(hexstr=f"0x{input_commitment}")
            program_id = Web3.keccak(hexstr=f"0x{program_digest}")
            output_hash = Web3.keccak(text=canon({
                "version": COMMIT_V,
                "output": output_value,
                "receipt_ref": receipt_ref,
            }))
            request_id = Web3.keccak(text=commitment["request_id"])
            if contract.functions.requestExists(request_id).call():
                saved = contract.functions.audits(request_id).call()
                if tuple(saved[:3]) != (input_hash, program_id, output_hash):
                    raise ValueError("Existing blockchain record does not match this request")
                return {"status": "RECORDED", "tx": None, "request_id": Web3.to_hex(request_id),
                        "detail": "Matching commitments already recorded on chain."}

            tx = contract.functions.recordAudit(request_id, input_hash, program_id, output_hash).build_transaction({
                "from": account.address,
                "chainId": w3.eth.chain_id,
                "nonce": w3.eth.get_transaction_count(account.address, "pending"),
                "gas": 300000,
                "gasPrice": w3.eth.gas_price,
            })
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status != 1:
                return {"status": "FAILED", "tx": None, "detail": "Blockchain transaction failed."}

            return {
                "status": "RECORDED",
                "tx": Web3.to_hex(tx_hash),
                "request_id": Web3.to_hex(request_id),
                "block_number": receipt.blockNumber,
                "detail": "Input, program, and output commitments were recorded. The contract does not verify RISC Zero proofs.",
            }
        except Exception as exc:
            return {"status": "FAILED", "tx": None, "detail": str(exc)}

class Risc0ProofEngine:
    """Thin adapter that exposes the app's expected proof interface while using the real RISC Zero host."""
    mode, name = "RISC0", "RISC Zero zkVM"

    def execute(self, program_id, inputs):
        return str((Decimal(inputs["salary"]) * Decimal(PROGRAMS[program_id]["rate"])).quantize(Decimal("0.01")))

    def prove(self, program_id, inputs, output):
        rate_percent = int(Decimal(PROGRAMS[program_id]["rate"]) * 100)
        salary_cents = int(Decimal(str(inputs["salary"])) * 100)
        proof_data = generate_proof(
            "bonus",
            [salary_cents, rate_percent],
        )
        output_cents = int(Decimal(str(output)) * 100)
        if proof_data["result"] != output_cents:
            raise RuntimeError("RISC Zero result does not match the computed bonus")

        journal = {
            "program_id": program_id,
            "program_digest": PROGRAMS[program_id]["digest"],
            "input_commitment": sha(inputs),
            "output": str(output),
        }
        receipt_ref = "risc0-" + sha({"proof": proof_data, "journal": journal})[:16]
        return {
            "receipt_ref": receipt_ref,
            "mode": self.mode,
            "journal": journal,
            "proof_verified": proof_data["proof_verified"],
            "native_proof": proof_data,
        }

    def verify(self, receipt):
        if not isinstance(receipt, dict):
            return {"mode": self.mode, "status": "INCOMPLETE", "verified_at": now(), "detail": "No receipt supplied."}

        proof = receipt.get("native_proof")
        journal = receipt.get("journal")
        if not isinstance(proof, dict) or not isinstance(journal, dict):
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "Receipt is missing its proof or journal."}
        if any(not isinstance(journal.get(key), str) for key in ("program_id", "program_digest", "input_commitment", "output")):
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "Receipt journal has invalid fields."}

        try:
            verified = verify_receipt(proof.get("receipt"))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return {"mode": self.mode, "status": "INCOMPLETE", "verified_at": now(), "detail": f"Verifier unavailable ({type(exc).__name__})."}
        except (ValueError, subprocess.CalledProcessError):
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "RISC Zero receipt verification failed."}

        numbers = verified["numbers"]
        if (
            verified["operation"] != 5
            or len(numbers) != 2
            or proof.get("operation") != 5
            or proof.get("numbers") != numbers
            or proof.get("result") != verified["result"]
        ):
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "Verified receipt does not match the stored proof data."}

        program = PROGRAMS.get(journal.get("program_id"))
        if (
            program is None
            or program["digest"] != journal.get("program_digest")
            or int(Decimal(program["rate"]) * 100) != numbers[1]
        ):
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "Receipt program does not match the journal."}

        salary = (Decimal(numbers[0]) / 100).quantize(Decimal("0.01"))
        if journal.get("input_commitment") != sha({"salary": str(salary)}):
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "Receipt input does not match the journal commitment."}

        try:
            journal_output_cents = Decimal(journal["output"]) * 100
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "Journal output is invalid."}
        if journal_output_cents != verified["result"]:
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "Receipt result does not match the journal output."}

        expected_ref = "risc0-" + sha({"proof": proof, "journal": journal})[:16]
        if receipt.get("receipt_ref") != expected_ref:
            return {"mode": self.mode, "status": "FAILED", "verified_at": now(), "detail": "Receipt reference does not match the receipt contents."}

        return {"mode": self.mode, "status": "VERIFIED", "verified_at": now(),
                "detail": "The RISC Zero receipt verified against the embedded guest image and its journal matches the request data."}

ENGINE, CHAIN = Risc0ProofEngine(), RealChain()

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

with sqlite3.connect(DB) as _c:
    _c.executescript(SCHEMA)
    # Preserve historical evidence, but never present the former boolean-only
    # verification as a valid proof under the repaired protocol.
    for _rid, _submission in _c.execute("select id,submission from requests where submission is not null").fetchall():
        try:
            _native = json.loads(_submission).get("receipt", {}).get("native_proof", {})
            _current = _native.get("protocol") == "verity-risc0/v2"
        except (ValueError, AttributeError):
            _current = False
        if not _current:
            _c.execute("update requests set status='PROOF_REBUILD_REQUIRED' where id=?", (_rid,))
_c.close()

def log(rid, typ, status, evidence=None):
    """Hash-chained application log: tamper-evident only to someone holding a trusted copy of the head hash."""
    d = db()
    if not d.in_transaction:
        d.execute("BEGIN IMMEDIATE")
    last = d.execute("select hash from audit order by seq desc limit 1").fetchone()
    prev, ts, ev = (last[0] if last else "0" * 64), now(), canon(evidence or {})
    cur = d.execute("insert into audit(ts,request_id,type,status,evidence,prev_hash,hash) values(?,?,?,?,?,?,?)",
                    (ts, rid, typ, status, ev, prev, sha([prev, ts, rid, typ, status, ev])))
    d.commit(); return f"audit:{cur.lastrowid}"

def req_row(r):
    o = dict(r); o["inputs"] = json.loads(o["inputs"]); o["chain_meta"] = json.loads(o["chain_meta"] or "{}")
    o["has_submission"] = bool(o.pop("submission")) and o["status"] != "PROOF_REBUILD_REQUIRED"
    o["agreed_program"] = PROGRAMS[o["program_id"]]
    return o

def get_req(rid):
    return db().execute("select * from requests where id=?", (rid,)).fetchone()

def err(msg, code=400): return jsonify(error=msg), code


def load_submission(req):
    """Reject damaged stored data before comparisons or verifier invocation."""
    try:
        sub = json.loads(req["submission"])
        if not isinstance(sub, dict) or not isinstance(sub.get("receipt"), dict):
            raise ValueError("Missing receipt")
        rec = sub["receipt"]
        journal = rec.get("journal")
        if not isinstance(journal, dict) or not isinstance(rec.get("receipt_ref"), str):
            raise ValueError("Missing journal or receipt reference")
        if any(not isinstance(journal.get(key), str) for key in ("program_id", "program_digest", "input_commitment", "output")):
            raise ValueError("Invalid journal fields")
        for output in (sub.get("claimed_output"), journal["output"]):
            if not isinstance(output, str) or not Decimal(output).is_finite() or Decimal(output) < 0:
                raise ValueError("Invalid output")
        return sub
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Stored submission is malformed; generate a new valid computation") from exc

# ---------- scenarios ----------
SCENARIOS = {
    "normal": ("Normal computation", "Provider runs the agreed program on the committed inputs and returns the true result."),
    "altered_output": ("Altered output", "Provider's proof is honest, but the answer delivered to the requester is inflated by 60%."),
    "altered_input": ("Altered input", "Provider computes on a salary 60% higher than the committed one. Treated as a separate test input; the original request is untouched."),
    "wrong_program": ("Different program", "Provider proves execution of a 15% bonus program instead of the agreed 10% one."),
    "invalid_proof": ("Invalid proof", "Provider returns correct-looking values with a corrupted RISC Zero receipt."),
}

def make_submission(req, scenario):
    inputs, pid = json.loads(req["inputs"]), req["program_id"]
    if scenario == "normal": return json.loads(req["submission"])
    out = ENGINE.execute(pid, inputs); sub = json.loads(req["submission"])
    if scenario == "altered_output":
        changed = max(Decimal(out) + Decimal("0.01"), Decimal(out) * Decimal("1.6"))
        sub["claimed_output"] = str(changed.quantize(Decimal("0.01")))
    elif scenario == "altered_input":
        bad = {"salary": str((Decimal(inputs["salary"]) * Decimal("1.6")).quantize(Decimal("0.01")))}
        o2 = ENGINE.execute(pid, bad); sub = {"claimed_output": o2, "receipt": ENGINE.prove(pid, bad, o2), "test_inputs": bad}
    elif scenario == "wrong_program":
        o2 = ENGINE.execute("bonus-15pct@1.0.0", inputs)
        sub = {"claimed_output": o2, "receipt": ENGINE.prove("bonus-15pct@1.0.0", inputs, o2)}
    elif scenario == "invalid_proof":
        sub["receipt"]["native_proof"]["receipt"] = {"invalid": "receipt"}
    return sub

# ---------- investigations ----------
def investigate(req, sub, rid):
    rec = sub.get("receipt"); j = rec["journal"] if rec else None
    v = ENGINE.verify(rec) if rec else {"mode": ENGINE.mode, "status": "INCOMPLETE", "verified_at": now(), "detail": "No receipt supplied."}
    trusted = j is not None and v["status"] in ("VERIFIED", "SIMULATED")
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
    status = proof_status() if ENGINE.mode == "RISC0" else {"available": True}
    return jsonify(proof_engine={"name": ENGINE.name, "mode": ENGINE.mode,
                                "genuine_verification": ENGINE.mode == "RISC0" and status["available"], **status},
                   blockchain={"name": CHAIN.name, **CHAIN.status},
                   audit_note="Audit log is hash-chained in SQLite. It is application history, not independently anchored or immutable.")

@app.get("/api/scenarios")
def scenarios(): return jsonify([{"id": k, "title": t, "description": d} for k, (t, d) in SCENARIOS.items()])

@app.post("/api/requests")
def create():
    b = request.get_json(silent=True) if request.data else {}
    if not isinstance(b, dict): return err("JSON body must be an object")
    sal = b.get("salary")
    if isinstance(sal, bool) or not isinstance(sal, (int, float, str)): return err("salary must be a number")
    try:
        sal = Decimal(str(sal))
        if not sal.is_finite() or sal <= 0 or sal > Decimal("100000000"):
            return err("salary must be > 0 and ≤ 100,000,000")
        sal = sal.quantize(Decimal("0.01"))
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
@request_locked
def execute(rid):
    r = get_req(rid)
    if not r: return err("not found", 404)
    if r["status"] in ("VERIFIED", "REJECTED"): return err(f"request already {r['status']}", 409)
    if r["submission"] and r["status"] != "PROOF_REBUILD_REQUIRED":
        return jsonify(req_row(r))
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
@request_locked
def run_investigation(rid):
    body = request.get_json(silent=True) if request.data else {}
    if not isinstance(body, dict): return err("JSON body must be an object")
    r = get_req(rid); scenario = body.get("scenario", "normal")
    if not r: return err("not found", 404)
    if not isinstance(scenario, str) or scenario not in SCENARIOS: return err("unknown scenario")
    if not r["submission"]: return err("execute the computation first", 409)
    try:
        load_submission(r)
    except ValueError as exc:
        return err(str(exc), 409)
    try:
        sub = make_submission(r, scenario)
    except Exception as exc:
        log(rid, "INVESTIGATION_FAILED", "FAILED", {"error": str(exc)})
        return err(f"investigation failed: {exc}", 502)
    run_id = "RUN-" + uuid.uuid4().hex[:8].upper()
    log(rid, "VERIFICATION_ATTEMPTED", "STARTED", {"run": run_id, "scenario": scenario})
    fs, v = investigate(r, sub, run_id); verdict = verdict_of(fs); refs = []
    for f in fs: refs.append(log(rid, f"INVESTIGATION_{f['n']}_{f['title'].split()[0].upper()}", f["status"], {"run": run_id, "code": f["code"]}))
    j = sub["receipt"]["journal"] if sub.get("receipt") else None
    limits = ["Proof engine is a SIMULATION: no genuine cryptographic verification took place." if ENGINE.mode == "SIMULATION" else "The serialized receipt is re-verified against the embedded RISC Zero guest image off-chain; the contract records commitments and does not verify the proof.",
              "A detected mismatch shows that values differ; it does not identify who changed them or establish intent.",
              "Commitments are stored in the same database as the request; they are not independently anchored until a blockchain adapter is connected.",
              "Audit log is application history (hash-chained), not an immutable record."]
    rep = {"verification_version": 2, "run_id": run_id, "request_id": rid, "scenario": scenario, "scenario_title": SCENARIOS[scenario][0],
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
@request_locked
def record(rid):
    r = get_req(rid)
    if not r: return err("not found", 404)
    if not r["submission"]:
        return err("execute the computation first", 409)

    try:
        submission = load_submission(r)
    except ValueError as exc:
        return err(str(exc), 409)
    receipt = submission.get("receipt")
    verification = ENGINE.verify(receipt)
    journal = receipt.get("journal") if isinstance(receipt, dict) else None
    if (
        verification["status"] != "VERIFIED"
        or not journal
        or journal.get("input_commitment") != r["input_commitment"]
        or journal.get("program_digest") != r["program_digest"]
        or submission.get("claimed_output") != journal.get("output")
    ):
        return err("a valid proof matching this request is required before blockchain recording", 409)

    res = CHAIN.record({
        "request_id": rid,
        "proof_verified": True,
        "input_commitment": r["input_commitment"],
        "program_digest": r["program_digest"],
        "output": journal["output"],
        "receipt_ref": receipt["receipt_ref"],
    })
    previous = json.loads(r["chain_meta"] or "{}")
    if (res["status"] == "RECORDED" and not res.get("tx")
            and previous.get("request_id") == res.get("request_id")):
        res = {**previous, **res, "tx": previous.get("tx")}
    db().execute("update requests set chain_status=?, chain_meta=? where id=?", (res["status"], canon(res), rid)); db().commit()
    log(rid, "BLOCKCHAIN_RECORD_ATTEMPTED", res["status"], res); return jsonify(res)

@app.get("/api/requests/<rid>/reports")
def reports(rid):
    if not get_req(rid): return err("not found", 404)
    rows = db().execute("select id,scenario,verdict,mode,created_at,report from runs where request_id=? order by rowid desc", (rid,))
    items = []
    for row in rows:
        item = dict(row)
        item["verdict"] = public_report(json.loads(item.pop("report")))["verdict"]
        items.append(item)
    return jsonify(items)


def public_report(report):
    if report.get("verification_version") != 2 and report.get("mode") == "RISC0":
        note = "Historical report predates receipt verification repairs. Run a new computation and investigation."
        report["verdict"] = report["proof_status"] = "INCOMPLETE"
        report["limitations"] = [note, *report.get("limitations", [])]
        for finding in report["findings"]:
            finding.update(status="INCOMPLETE", code="LEGACY_UNVERIFIED", explanation=note)
    return report

@app.get("/api/reports/<run_id>")
def report(run_id):
    x = db().execute("select report from runs where id=?", (run_id,)).fetchone()
    return jsonify(public_report(json.loads(x[0]))) if x else err("not found", 404)

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
    for x in runs:
        report = public_report(json.loads(x.pop("report")))
        x["verdict"] = report["verdict"]
        x["findings"] = [{"title": f["title"], "status": f["status"], "code": f["code"]} for f in report["findings"]]
    return jsonify(total=len(rs), verified=count("VERIFIED"), rejected=count("REJECTED"),
                   pending=len(rs) - count("VERIFIED") - count("REJECTED"), simulation_only=d.execute(
                       "select count(distinct request_id) from runs where scenario='normal' and verdict='SIMULATION ONLY'").fetchone()[0],
                   chain_statuses={s: sum(1 for x in rs if x["chain_status"] == s) for s in {x["chain_status"] for x in rs}},
                   recent_requests=list(reversed(rs))[:6], recent_runs=runs)

if __name__ == "__main__":
    app.run(debug=False, port=5000)
