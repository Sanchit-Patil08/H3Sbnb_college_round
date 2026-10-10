// Entry point: hash routing, nav state, sidebar integration status.
import { $, E, api, state, view, errBox, badge } from "./core.js";
import * as pages from "./pages.js";

const ROUTES = { dashboard: pages.dashboard, new: pages.newComputation, lab: pages.lab, report: pages.reports, audit: pages.audit };

function renderIntegrations() {
    const i = state.integ, sim = i.proof_engine.mode === "SIMULATION";
    $("#integ").innerHTML = `<div class="lbl">INTEGRATIONS</div>
    <div><div class="ln"><span>Proof engine</span>${badge(sim ? "SIMULATED" : "PASSED").replace(/>[^<]*<\/span>$/, `>${sim ? "SIMULATION" : "REAL"}</span>`)}</div><div class="mut">${E(i.proof_engine.name)}</div></div>
    <div><div class="ln"><span>Blockchain</span>${badge(i.blockchain.enabled ? "CONFIRMED" : "NOT_SUBMITTED").replace(/>[^<]*<\/span>$/, `>${i.blockchain.enabled ? "ENABLED" : "DISABLED"}</span>`)}</div><div class="mut">${E(i.blockchain.name)}</div></div>`;
    const env = $("#env"); env.textContent = sim ? "SIMULATION MODE" : "LIVE VERIFICATION"; env.classList.toggle("real", !sim);
}

async function route() {
    const [path, query = ""] = (location.hash.slice(2) || "dashboard").split("?");
    const [page, arg] = path.split("/");
    document.querySelectorAll(".nav a").forEach(a => { const on = a.dataset.route === page; a.classList.toggle("on", on); on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"); });
    document.body.classList.remove("nav-open");
    try { await (ROUTES[page] || pages.dashboard)(arg, new URLSearchParams(query)); }
    catch (e) { view(errBox(e)); }
    window.scrollTo(0, 0);
}

$("#menu").onclick = () => document.body.classList.add("nav-open");
$("#scrim").onclick = () => document.body.classList.remove("nav-open");
addEventListener("keydown", e => { if (e.key === "Escape") document.body.classList.remove("nav-open"); });
addEventListener("hashchange", route);

try { state.integ = await api("/integrations"); renderIntegrations(); }
catch (e) { $("#integ").innerHTML = `<div class="mut">Integration status unavailable</div>`; }
route();