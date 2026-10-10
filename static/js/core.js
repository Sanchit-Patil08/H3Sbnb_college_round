// Shared helpers: API client, escaping, reusable UI fragments.
export const $ = (s, r = document) => r.querySelector(s);
export const E = s => String(s ?? "—").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export async function api(path, method = "GET", body) {
    const r = await fetch("/api" + path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    let j = {};
    try { j = await r.json(); } catch { /* non-JSON error body */ }
    if (!r.ok) throw new Error(j.error || `Request failed (HTTP ${r.status})`);
    return j;
}

export const state = { integ: null };
export const ic = n => `<svg class="i" aria-hidden="true"><use href="#i-${n}"/></svg>`;
export const cls = s => "s-" + String(s).replace(/ /g, "_");
export const badge = s => `<span class="badge ${cls(s)}">${E(s)}</span>`;
export const inr = v => v == null ? "—" : "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2 });
export const when = t => t ? t.replace("T", " ").replace("+00:00", " UTC") : "—";
export const hash = h => h ? `<button type="button" class="hash mono" data-copy="${E(h)}" title="Click to copy full value: ${E(h)}">${E(h.slice(0, 12))}…${E(h.slice(-4))}${ic("copy")}</button>` : "—";
export const loading = m => `<div class="state" role="status"><div><span class="spin"></span>${m}…</div></div>`;
export const empty = (t, d, a = "") => `<div class="state"><div class="state-t">${t}</div><p>${d}</p>${a}</div>`;
export const errBox = e => `<div class="alert a-red" role="alert">${ic("alert")}<span>${E(e.message || e)}</span></div>`;
export const simBanner = () => state.integ?.proof_engine.mode === "SIMULATION"
    ? `<div class="banner">${ic("alert")}<span><b>Simulation mode.</b> ${E(state.integ.proof_engine.name)}. Results are labelled SIMULATED and are not genuine cryptographic verification.</span></div>` : "";

export const view = html => { const v = $("#view"); v.innerHTML = html; return v; };
export function setTop(crumb, reqId, action = "") {
    $("#crumb").textContent = crumb;
    const c = $("#reqchip"); c.hidden = !reqId; c.textContent = reqId || "";
    $("#topact").innerHTML = action;
    document.title = `${crumb} · Verity`;
}

const fmtVal = v => typeof v === "object" && v ? JSON.stringify(v) : v;
const evVal = v => { const s = String(fmtVal(v) ?? "—"); return /^[0-9a-f]{64}$/.test(s) ? hash(s) : `<span class="mono">${E(s)}</span>`; };
export const evTable = ev => `<table class="ev"><tbody>${ev.map(e => `<tr><td class="mono mut">${E(e.ref)}</td><td>${E(e.label)}</td><td>${evVal(e.value)}</td></tr>`).join("")}</tbody></table>`;

export const finding = f => `<article class="find ${cls(f.status)}">
  <header><span class="fn">${f.n}</span><div><h3>${E(f.title)}</h3><p>${E(f.question)}</p></div>
  <div class="row">${f.mode === "SIMULATION" ? badge("SIMULATION") : ""}${badge(f.status)}</div></header>
  <div class="cmp"><div><small>${E(f.expected.label)}</small><b>${E(f.expected.value)}</b></div>
  <div class="${f.status === "FAILED" ? "diff" : ""}"><small>${E(f.received.label)}</small><b>${E(f.received.value)}</b></div></div>
  <p class="expl">${f.code !== "OK" ? `<code>${E(f.code)}</code> ` : ""}${E(f.explanation)}</p>
  <details><summary>Technical evidence · ${f.evidence.length} items</summary>${evTable(f.evidence)}</details></article>`;

export const VERDICT = {
    "VERIFIED": ["green", "All required checks passed and the proof was cryptographically verified."],
    "REJECTED": ["red", "A required integrity check failed or the proof was invalid."],
    "INCOMPLETE": ["amber", "One or more checks could not be completed."],
    "SIMULATION ONLY": ["violet", "Checks ran against a simulated proof engine. Nothing was cryptographically verified."]
};
export const verdictBox = v => { const [c, t] = VERDICT[v]; return `<div class="verdict" style="color:var(--${c});border-color:var(--${c});background:color-mix(in srgb,var(--${c}) 8%,transparent)"><div><h2>${E(v)}</h2><p style="color:var(--tx)">${t}</p></div></div>`; };

document.addEventListener("click", e => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    navigator.clipboard?.writeText(b.dataset.copy);
    b.classList.add("ok"); setTimeout(() => b.classList.remove("ok"), 900);
});