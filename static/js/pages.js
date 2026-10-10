// The five screens. Each is an async function that renders into #view.
import { $, E, api, ic, badge, cls, inr, when, hash, loading, empty, errBox, simBanner, view, setTop, state, finding, evTable, verdictBox } from "./core.js";

const newBtn = `<a class="btn btn-p" href="#/new">${ic("plus")}New Computation</a>`;
const head = (t, d, act = "") => `<div class="ph"><div><h1>${t}</h1><p class="mut">${d}</p></div>${act}</div>`;
const metric = (l, n, c = "", note = "") => `<div class="metric m-${c}"><b>${n}</b><span>${l}</span>${note ? `<small>${note}</small>` : ""}</div>`;
const ID = id => `<a class="mono" href="#/lab/${E(id)}">${E(id)}</a>`;

/* ---------- A. Overview ---------- */
export async function dashboard() {
    setTop("Overview");
    view(loading("Loading overview"));
    const [d, rq, au] = await Promise.all([api("/dashboard"), api("/requests"), api("/audit")]);
    const bad = d.recent_runs.filter(r => r.findings.some(f => f.status === "FAILED" || f.status === "INCOMPLETE"));
    view(`${head("Security Overview", "Submit computations, then investigate whether each result, input, program and proof can be trusted.", newBtn)}
  <div class="metrics">${metric("Total requests", d.total)}${metric("Verified", d.verified, "green", "real verification only")}${metric("Rejected", d.rejected, "red")}${metric("Pending / incomplete", d.pending, "amber", `${d.simulation_only} simulation-only`)}</div>
  ${simBanner()}
  <div class="cols"><section class="panel"><header><h2>Recent computations</h2></header>
  ${rq.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Request</th><th>Salary</th><th>Program</th><th>Status</th><th>Chain</th></tr></thead><tbody>${rq.slice(0, 6).map(r => `<tr><td>${ID(r.id)}</td><td>${inr(r.inputs.salary)}</td><td class="mono">${E(r.program_id)}</td><td>${badge(r.status)}</td><td>${badge(r.chain_status)}</td></tr>`).join("")}</tbody></table></div>` : empty("No requests yet", "Create a computation request to begin.", newBtn)}</section>
  <section class="panel"><header><h2>Security findings</h2></header>
  ${bad.length ? bad.map(r => `<div class="row" style="margin-bottom:12px"><div class="grow"><a href="#/report/${E(r.id)}" class="mono">${E(r.request_id)}</a> <span class="mut">· ${E(r.scenario.replace("_", " "))}</span><div class="row" style="margin-top:4px">${r.findings.filter(f => f.status === "FAILED" || f.status === "INCOMPLETE").map(f => `<code>${E(f.code)}</code>`).join("")}</div></div>${badge(r.verdict)}</div>`).join("") : empty("No failed or incomplete checks", "Findings from the Investigation Lab appear here.")}</section></div>
  <section class="panel"><header><h2>Latest audit activity</h2><a href="#/audit">View all</a></header>
  ${au.length ? `<div class="tbl-wrap"><table class="tbl"><tbody>${au.slice(0, 6).map(e => `<tr><td class="mono mut">${when(e.ts)}</td><td class="mono">${E(e.request_id)}</td><td>${E(e.type)}</td><td>${badge(e.status)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="mut">No events recorded yet.</p>`}</section>`);
}

/* ---------- B. New Computation ---------- */
export function newComputation() {
    setTop("New Computation");
    view(`${head("New Computation", "Create a request for the employee bonus calculation. The agreed rule is fixed at creation and cannot be redefined by the provider.")}
  <div class="cols"><form class="panel" id="f" novalidate>
    <div class="field"><label for="sal">Salary (₹)</label><input class="input" id="sal" type="number" min="0" step="0.01" value="50000" inputmode="decimal" aria-describedby="salerr"><div class="err" id="salerr" role="alert"></div></div>
    <div class="field"><label for="rate">Agreed bonus rate (%)</label><input class="input" id="rate" value="10" readonly><small>Fixed by the agreed program for this MVP.</small></div>
    <div class="field"><label for="prog">Agreed program</label><input class="input mono" id="prog" value="bonus-10pct@1.0.0" readonly></div>
    <button class="btn btn-p" id="go" type="submit">Create request</button><div id="msg" style="margin-top:14px"></div></form>
  <aside class="panel"><header><h2>Calculation preview</h2><span class="sub">local only</span></header><div id="prev"></div>
    <p class="mut" style="margin-top:14px;font-size:.8rem">This is a local preview, not proof verification. On creation the backend stores a SHA-256 commitment of the canonical inputs and the program digest.</p></aside></div>`);
    const sal = $("#sal"), valid = () => { const n = Number(sal.value); return sal.value !== "" && n > 0 && n <= 1e8; };
    const prev = () => {
        const ok = valid(), n = Number(sal.value);
        sal.classList.toggle("bad", !ok); $("#salerr").textContent = ok ? "" : "Enter a salary greater than 0 and up to 100,000,000.";
        $("#prev").innerHTML = ok ? `<dl class="kv"><dt>Salary</dt><dd>${inr(n)}</dd><dt>Agreed rate</dt><dd>10%</dd><dt>Formula</dt><dd class="mono">salary × 0.10</dd><dt><b>Expected bonus</b></dt><dd><b>${inr(n * 0.1)}</b></dd></dl>` : `<p class="mut">Enter a valid salary to preview.</p>`;
    };
    sal.oninput = prev; prev();
    $("#f").onsubmit = async e => {
        e.preventDefault(); if (!valid()) return prev();
        const b = $("#go"); b.disabled = true; b.textContent = "Creating…";
        try {
            const r = await api("/requests", "POST", { salary: Number(sal.value), agreed_rate_percent: 10 });
            $("#msg").innerHTML = `<div class="alert a-green">${ic("alert")}<div><b>Request ${E(r.id)} created.</b><div style="margin-top:6px">Input commitment ${hash(r.input_commitment)}</div><div style="margin-top:8px"><a href="#/lab/${E(r.id)}">Open in Investigation Lab →</a></div></div></div>`;
        } catch (x) { $("#msg").innerHTML = errBox(x); }
        b.disabled = false; b.textContent = "Create request";
    };
}

/* ---------- C. Investigation Lab ---------- */
let sel = "normal";
const STEPS = ["Output", "Input", "Program", "Proof"];
const progress = fs => `<div class="steps">${STEPS.map((s, i) => `<div class="step ${fs ? cls(fs[i].status) : ""}"><b>${s}</b>${fs ? E(fs[i].status) : "Not run"}</div>`).join("")}</div>`;

function evidencePanel(rep, sc) {
    const s = sc.find(x => x.id === sel);
    if (!rep) return `<section class="panel evp"><header><h2>Evidence</h2></header><p class="sub">Selected scenario</p><h3 style="margin:6px 0 4px">${E(s.title)}</h3><p class="mut">${E(s.description)}</p><p class="mut" style="margin-top:12px;font-size:.8rem">Run the investigation to collect evidence. Test scenarios never modify the original request.</p></section>`;
    const refs = rep.findings.flatMap(f => f.evidence.filter(e => e.value != null && typeof e.value !== "object").map(e => ({ ...e, f: f.title })));
    return `<section class="panel evp"><header><h2>Evidence</h2>${badge(rep.mode)}</header><p class="sub">Scenario</p><p style="margin:4px 0 12px"><b>${E(rep.scenario_title)}</b></p>
  <dl class="kv"><dt>Claimed output</dt><dd>${inr(rep.claimed_output)}</dd><dt>Proof-bound</dt><dd>${inr(rep.proof_bound_output)}</dd><dt>Agreed program</dt><dd class="mono">${E(rep.agreed_program)}</dd><dt>Proven program</dt><dd class="mono">${E(rep.proven_program)}</dd><dt>Proof status</dt><dd>${badge(rep.proof_status)}</dd><dt>Blockchain</dt><dd>${badge(rep.blockchain_status)}</dd></dl>
  <details open><summary>Evidence references (${refs.length})</summary><div class="reflist">${refs.map(e => `<div><span class="mono mut">${E(e.ref)}</span><span>${E(e.label)}</span>${/^[0-9a-f]{64}$/.test(e.value) ? hash(e.value) : `<span class="mono">${E(e.value)}</span>`}</div>`).join("")}</div></details>
  <details><summary>Limitations</summary><ul class="mut" style="font-size:.78rem;padding-left:16px">${rep.limitations.map(l => `<li>${E(l)}</li>`).join("")}</ul></details></section>`;
}

export async function lab(rid) {
    setTop("Investigation Lab");
    view(loading("Loading lab"));
    const [rq, sc] = await Promise.all([api("/requests"), api("/scenarios")]);
    if (!rq.length) return view(empty("No requests to investigate", "Create a computation request first.", newBtn));
    const r = rq.find(x => x.id === rid) || rq[0];
    setTop("Investigation Lab", r.id);
    view(`${head("Proof Detective Lab", "Four checks: was the output changed, were the inputs altered, was the agreed program used, and is the proof valid?")}${simBanner()}
  <div class="lab"><div class="stack"><section class="panel"><div class="field"><label for="rsel">Request</label><select id="rsel">${rq.map(x => `<option value="${E(x.id)}" ${x.id === r.id ? "selected" : ""}>${E(x.id)} · ${E(x.status)}</option>`).join("")}</select></div>
    <dl class="kv"><dt>Salary</dt><dd>${inr(r.inputs.salary)}</dd><dt>Agreed rule</dt><dd class="mono">${E(r.agreed_program.rule)}</dd><dt>Status</dt><dd id="rstat">${badge(r.status)}</dd><dt>Commitment</dt><dd>${hash(r.input_commitment)}</dd></dl>
    <div class="stack" style="margin-top:14px"><button class="btn btn-w" id="exec" ${r.has_submission ? "disabled" : ""}>${ic("play")}${r.has_submission ? "Provider has executed" : "1 · Run provider computation"}</button>
    <button class="btn btn-s btn-w" id="rec" title="${E(state.integ?.blockchain.name)}">Record on blockchain${state.integ?.blockchain.enabled ? "" : " (adapter disabled)"}</button></div></section>
    <section class="panel"><header><h2>Test scenario</h2></header><div role="radiogroup" aria-label="Test scenario">${sc.map(s => `<label class="scn"><input type="radio" name="sc" value="${s.id}" ${s.id === sel ? "checked" : ""}><b>${E(s.title)}</b><span>${E(s.description)}</span></label>`).join("")}</div>
    <button class="btn btn-p btn-w" id="run" ${r.has_submission ? "" : "disabled"}>${ic("search")}2 · Run four investigations</button>${r.has_submission ? "" : `<p class="mut" style="font-size:.76rem;margin-top:8px">Run the provider computation first.</p>`}</section></div>
    <div id="res">${progress(null)}<section class="panel">${empty("No investigation run yet", "Pick a scenario and run the four checks.")}</section></div><div class="evp-slot" id="evp">${evidencePanel(null, sc)}</div></div>`);
    $("#rsel").onchange = e => { location.hash = "#/lab/" + e.target.value; };
    document.querySelectorAll("input[name=sc]").forEach(i => i.onchange = () => { sel = i.value; if (!$("#res .find")) $("#evp").innerHTML = evidencePanel(null, sc); });
    $("#exec").onclick = async e => { e.target.disabled = true; try { await api(`/requests/${r.id}/execute`, "POST"); lab(r.id); } catch (x) { $("#res").innerHTML = errBox(x); e.target.disabled = false; } };
    $("#rec").onclick = async () => { try { const x = await api(`/requests/${r.id}/record`, "POST"); $("#res").insertAdjacentHTML("afterbegin", `<div class="alert a-amber">${ic("alert")}<span>Blockchain: ${badge(x.status)} ${E(x.detail)}</span></div>`); } catch (x) { $("#res").insertAdjacentHTML("afterbegin", errBox(x)); } };
    const run = $("#run");
    run.onclick = async () => {
        if (run.disabled) return;
        run.disabled = true; run.innerHTML = `<span class="spin"></span>Investigating…`; $("#res").innerHTML = loading("Running four investigations");
        try {
            const rep = await api(`/requests/${r.id}/investigate`, "POST", { scenario: sel });
            $("#res").innerHTML = `${verdictBox(rep.verdict)}${progress(rep.findings)}${rep.findings.map(finding).join("")}<a class="btn btn-s" href="#/report/${E(rep.run_id)}">${ic("file")}Open full report</a>`;
            $("#evp").innerHTML = evidencePanel(rep, sc);
            const fresh = await api("/requests/" + r.id); $("#rstat").innerHTML = badge(fresh.status);
        } catch (x) { $("#res").innerHTML = errBox(x); }
        run.disabled = false; run.innerHTML = `${ic("search")}2 · Run four investigations`;
    };
}

/* ---------- D. Reports ---------- */
export async function reports(id) {
    if (!id) {
        setTop("Investigation Reports"); view(loading("Loading reports"));
        const rq = await api("/requests");
        const runs = (await Promise.all(rq.map(r => api(`/requests/${r.id}/reports`).then(l => l.map(x => ({ ...x, request_id: r.id })))))).flat().sort((a, b) => b.created_at.localeCompare(a.created_at));
        return view(`${head("Investigation Reports", "Each report records one investigation run: its findings, evidence and limitations.")}<section class="panel">${runs.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Report</th><th>Request</th><th>Scenario</th><th>Verdict</th><th>Generated</th></tr></thead><tbody>${runs.map(x => `<tr><td><a class="mono" href="#/report/${E(x.id)}">${E(x.id)}</a></td><td>${ID(x.request_id)}</td><td>${E(x.scenario.replace("_", " "))}</td><td>${badge(x.verdict)}</td><td class="mono mut">${when(x.created_at)}</td></tr>`).join("")}</tbody></table></div>` : empty("No reports yet", "Reports are generated when you run an investigation.", `<a class="btn" href="#/lab">Open the Lab</a>`)}</section>`);
    }
    setTop("Investigation Reports"); view(loading("Loading report"));
    const r = await api("/reports/" + id);
    setTop("Report " + r.run_id, r.request_id, `<button class="btn btn-s noprint" onclick="print()">${ic("print")}Print / save PDF</button>`);
    view(`<div class="doc">${head("Investigation Report", `<span class="mono">${E(r.run_id)}</span> · request <span class="mono">${E(r.request_id)}</span> · ${when(r.generated_at)}`)}
  ${verdictBox(r.verdict)}${r.mode === "SIMULATION" ? `<div class="banner">${ic("alert")}<span>Simulation only. No genuine cryptographic verification was performed.</span></div>` : ""}
  <section><h2 class="sec">Scenario</h2><p><b>${E(r.scenario_title)}</b> — ${E(r.scenario_description)}</p></section>
  <section class="grid2"><div><h2 class="sec">Original request</h2><dl class="kv"><dt>Salary</dt><dd>${inr(r.request.inputs.salary)}</dd><dt>Created</dt><dd>${when(r.request.created_at)}</dd><dt>Agreed program</dt><dd class="mono">${E(r.agreed_program)}</dd><dt>Commitment</dt><dd>${hash(r.request.input_commitment)}</dd></dl></div>
  <div><h2 class="sec">Claimed vs proof-bound</h2><dl class="kv"><dt>Claimed output</dt><dd>${inr(r.claimed_output)}</dd><dt>Proof-bound output</dt><dd>${inr(r.proof_bound_output)}</dd><dt>Proven program</dt><dd class="mono">${E(r.proven_program)}</dd></dl></div></section>
  <section><h2 class="sec">Investigation findings</h2>${r.findings.map(finding).join("")}</section>
  <section class="grid2"><div><h2 class="sec">Proof verification</h2>${badge(r.proof_status)}<p class="mut" style="margin-top:6px;font-size:.8rem">Cryptographic status of the receipt, separate from the integrity checks.</p></div>
  <div><h2 class="sec">Blockchain recording</h2>${badge(r.blockchain_status)}<p class="mut" style="margin-top:6px;font-size:.8rem">Reported separately. A recording failure does not invalidate a verified proof.</p></div></section>
  <section><h2 class="sec">What this report cannot conclude</h2><ul class="mut">${r.limitations.map(l => `<li>${E(l)}</li>`).join("")}</ul></section>
  <section><h2 class="sec">Audit event references</h2><div class="row">${r.audit_refs.map(a => `<a class="mono" href="#/audit?request_id=${E(r.request_id)}">${E(a)}</a>`).join("")}</div></section></div>`);
}

/* ---------- E. Audit Trail ---------- */
export async function audit(arg, params) {
    setTop("Audit Trail");
    view(`${head("Audit Trail", "Chronological application events for every request, from creation to investigation and blockchain-recording attempts.")}
  <div class="banner">${ic("alert")}<span>${E(state.integ?.audit_note || "Application history only.")}</span></div>
  <form class="panel row" id="af" style="margin-bottom:16px;align-items:flex-end"><div class="field grow" style="margin:0"><label for="fr">Request ID</label><input class="input" id="fr" value="${E(params.get("request_id") || "")}" placeholder="VRT-…"></div>
  <div class="field grow" style="margin:0"><label for="ft">Event type</label><input class="input" id="ft" placeholder="e.g. INVESTIGATION"></div><div class="field grow" style="margin:0"><label for="fs">Status</label><input class="input" id="fs" placeholder="e.g. FAILED"></div>
  <button class="btn btn-p" type="submit">Apply</button><button class="btn btn-s" type="button" id="rs">Reset</button></form><section class="panel" id="rows"></section>`);
    const go = async () => {
        $("#rows").innerHTML = loading("Loading events");
        try {
            const a = await api("/audit?" + new URLSearchParams({ request_id: $("#fr").value, type: $("#ft").value, status: $("#fs").value }));
            $("#rows").innerHTML = a.length ? `<div class="tl">${a.map(e => {
                const j = JSON.stringify(e.evidence), long = j.length > 70; return `<div class="ev-i ${cls(e.status)}"><div class="row"><span class="t">${E(e.type.replaceAll("_", " "))}</span>${badge(e.status)}<span class="mono mut">${when(e.ts)}</span></div>
      <div class="row" style="margin-top:4px"><a class="mono" href="#/audit?request_id=${E(e.request_id)}">${E(e.request_id)}</a><span class="mono mut">${E(e.ref)}</span>${hash(e.hash)}</div>
      <div class="mono mut" style="margin-top:4px">${E(long ? j.slice(0, 70) + "…" : j)}</div>${long ? `<details><summary>Inspect evidence</summary><pre>${E(JSON.stringify(e.evidence, null, 2))}</pre></details>` : ""}</div>`;
            }).join("")}</div>` : empty("No matching events", "Adjust or reset the filters.");
        } catch (x) { $("#rows").innerHTML = errBox(x); }
    };
    $("#af").onsubmit = e => { e.preventDefault(); go(); };
    $("#rs").onclick = () => { ["fr", "ft", "fs"].forEach(i => { $("#" + i).value = ""; }); go(); };
    go();
}