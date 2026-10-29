/* ALIBI console. A client of two things only: case files (cases/*.json) and the ALIBI API (window.ALIBI_API).
   When the API is unreachable it switches to SAMPLE mode: a synthetic case from sample/ scored in the browser. */
"use strict";
(function () {
const API = String(window.ALIBI_API || "http://127.0.0.1:8601/api/v1").replace(/\/+$/, "");
const CSS = getComputedStyle(document.documentElement);
const tok = n => CSS.getPropertyValue(n).trim();
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const pct = v => v == null ? "--" : String(Math.round(v * 100));
const FX = ["WX", "ICE", "PLC", "GNSS", "TRF"];
const FX_SRC = { WX: "sea_state", ICE: "ice", PLC: "place", GNSS: "position_quality", TRF: "fleet" };
const FX_NAME = { WX: "Weather and sea state", ICE: "Sea ice", PLC: "Place", GNSS: "Position quality", TRF: "Traffic nearby" };
const SRC_FX = Object.fromEntries(Object.entries(FX_SRC).map(([k, v]) => [v, k]));
const FALLBACK_SOURCES = ["profile", "sea_state", "ice", "own_habit", "place", "fleet", "notices", "position_quality", "identity"];
const STATUS = {
  supports_explanation: ["ex", "EXPLAINS"], weakens_explanation: ["no", "NOT EXPLAINED"],
  unavailable: ["na", "NO DATA"], neutral: ["", "CONTEXT"], identity_context_only: ["", "CONTEXT"]
};

const S = {
  sample: false, health: null, sources: [], enabled: new Set(), sens: 0.5, recordedSens: null,
  cases: [], caseBase: "cases/", kase: null, rows: [], sortKey: "unx", sel: null,
  prevX: null, prevTop: null, lastWhat: "", seq: 0, batchMissing: false, sampleBatch: null, corridors: null
};
const th = s => 0.75 - 0.5 * (s == null ? S.sens : s);
const srcLabel = id => String(id).replace(/_/g, " ").toUpperCase();

/* ---------- fetch helpers ---------- */
async function getJSON(url, ms = 8000) {
  const ac = new AbortController(), t = setTimeout(() => ac.abort(), ms);
  try {
    const r = await fetch(url, { signal: ac.signal, cache: "no-cache" });
    if (!r.ok) throw Object.assign(new Error(r.status + " " + r.statusText), { status: r.status });
    return await r.json();
  } finally { clearTimeout(t); }
}
async function postJSON(url, body, ms = 120000) {
  const ac = new AbortController(), t = setTimeout(() => ac.abort(), ms);
  try {
    const r = await fetch(url, { method: "POST", signal: ac.signal, headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) {
      let msg = r.status + " " + r.statusText;
      try { const j = await r.json(); msg = j.message || j.detail && JSON.stringify(j.detail) || msg; } catch (e) { /* not json */ }
      throw Object.assign(new Error(msg), { status: r.status });
    }
    return await r.json();
  } finally { clearTimeout(t); }
}

/* ---------- boot ---------- */
async function boot() {
  tick(); setInterval(tick, 1000);
  wireControls();
  try { S.health = await getJSON(API + "/health", 3000); } catch (e) { S.health = null; }
  S.sample = !S.health;
  $("sample-badge").hidden = !S.sample;
  setLamps();
  await loadSources();
  await loadCases();
  getJSON(S.caseBase + "corridors.geojson", 4000).then(j => { S.corridors = j; scope(); }).catch(() => {});
  const want = decodeURIComponent((location.hash.match(/case=([^&]+)/) || [])[1] || "");
  const first = S.cases.find(c => c.case_id === want) || S.cases[0];
  if (first) loadCase(first); else boardMessage("No cases found. The detector writes them to cases/index.json.");
}

function setLamps() {
  const set = (id, st) => { const el = $(id); el.className = "lamp " + ({ ok: "", degraded: "warn", unavailable: "bad", bad: "bad" }[st] ?? "off"); el.title = el.title.split(" · ")[0] + " · " + (st || "not checked"); };
  if (!S.health) { set("lamp-api", "bad"); set("lamp-prof", "off"); set("lamp-cop", "off"); return; }
  set("lamp-api", S.health.status === "ok" ? "ok" : "degraded");
  const deps = S.health.dependencies || {};
  const find = re => { const k = Object.keys(deps).find(k => re.test(k)); return k ? deps[k] : "not_checked"; };
  set("lamp-prof", find(/profile/i));
  set("lamp-cop", find(/copernicus|cmems|env|sea_state|marine/i));
}

async function loadSources() {
  let list = null;
  try {
    const j = await getJSON(S.sample ? "sample/sources.json" : API + "/sources", 5000);
    const arr = Array.isArray(j) ? j : (j.sources || j.items || []);
    list = arr.map(x => typeof x === "string" ? { id: x } : { id: x.source_id || x.id, title: x.title, kind: x.kind, attribution: x.attribution }).filter(x => x.id);
  } catch (e) { /* fall back */ }
  if (!list || !list.length) list = FALLBACK_SOURCES.map(id => ({ id }));
  if (!list.some(s => s.id === "profile")) list.unshift({ id: "profile", title: "Vessel and class profile", kind: "behaviour" });
  S.sources = list;
  const def = Array.isArray(window.ALIBI_DEFAULT_SOURCES) ? window.ALIBI_DEFAULT_SOURCES : list.map(s => s.id);
  S.enabled = new Set(def.filter(id => list.some(s => s.id === id)).concat("profile"));
  renderSourceKeys();
}

async function loadCases() {
  const norm = j => (Array.isArray(j) ? j : (j.cases || j.items || [])).map(c => typeof c === "string" ? { case_id: c.replace(/\.json$/, "") } : c).filter(c => c && c.case_id);
  if (!S.sample) {
    try { S.cases = norm(await getJSON("cases/index.json", 5000)); S.caseBase = "cases/"; } catch (e) { S.cases = []; }
  }
  if (!S.cases.length) {
    try { S.cases = norm(await getJSON("sample/index.json", 5000)); S.caseBase = "sample/"; } catch (e) { S.cases = []; }
  }
  const box = $("case-keys"); box.innerHTML = "";
  S.cases.forEach(c => {
    const b = document.createElement("button");
    b.className = "key"; b.type = "button"; b.dataset.case = c.case_id; b.setAttribute("aria-pressed", "false");
    b.textContent = srcLabel(c.case_id); b.title = [c.title, c.kind, c.region].filter(Boolean).join(" · ");
    b.onclick = () => loadCase(c);
    box.appendChild(b);
  });
  if (!S.cases.length) box.innerHTML = '<span class="dimtxt">no cases</span>';
}

async function loadCase(c) {
  document.querySelectorAll("#case-keys .key").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.case === c.case_id)));
  boardMessage("Loading case " + esc(c.case_id) + " …");
  let kase;
  try { kase = await getJSON(S.caseBase + encodeURIComponent(c.case_id) + ".json", 30000); }
  catch (e) { boardMessage("Could not load case " + esc(c.case_id) + ": " + esc(e.message)); return; }
  S.kase = Object.assign({}, c, kase);
  S.sampleBatch = null;
  history.replaceState(null, "", "#case=" + encodeURIComponent(c.case_id));
  const d = S.kase.start ? new Date(S.kase.start) : null;
  const stamp = d && !isNaN(d) ? d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).toUpperCase() : "";
  $("replay-stamp").hidden = false;
  $("replay-stamp").textContent = "REPLAY · " + (stamp || srcLabel(c.case_id));
  $("board-sub").textContent = "· " + (S.kase.title || srcLabel(c.case_id)).toUpperCase();
  $("scope-sub").textContent = "· " + regionName(S.kase.region) + " · SCHEMATIC";
  S.rows = (S.kase.requests || []).map((req, i) => {
    const md = req.metadata || {}, ev = req.event || {};
    return { id: ev.event_id || ("req-" + i), i, req, a: null, U: null, X: null, prevX: undefined,
      name: md.vessel_name || ev.vessel_id || "UNKNOWN", loa: md.length_m, imo: md.imo };
  });
  S.sel = S.rows[0] ? S.rows[0].id : null;
  S.prevX = null; S.prevTop = null; S.rowEls = new Map(); $("board").innerHTML = "";
  await run({ kind: "load" });
}

/* ---------- running the case ---------- */
function options() { return { sensitivity: S.sens, enabled_sources: S.sources.map(s => s.id).filter(id => S.enabled.has(id)) }; }

async function run(what) {
  if (!S.kase) return;
  const seq = ++S.seq, opts = options();
  const before = new Map(S.rows.map(r => [r.id, r.X]));
  const beforeTop = S.rows.length && S.rows.some(r => r.a) ? topCount(what.prevSens) : null;
  document.body.classList.add("busy");
  setStrip({ busy: true });
  let results;
  try { results = S.sample ? await sampleAssess(opts) : await apiAssess(opts); }
  catch (e) {
    if (seq !== S.seq) return;
    document.body.classList.remove("busy");
    setStrip({ error: "API ERROR · " + e.message });
    return;
  }
  if (seq !== S.seq) return;
  document.body.classList.remove("busy");
  const byId = new Map(results.filter(Boolean).map(a => [a.event && a.event.event_id, a]));
  S.rows.forEach((r, k) => {
    const a = (results[k] && (!results[k].event || !r.req.event || results[k].event.event_id === r.id)) ? results[k] : byId.get(r.id) || results[k] || null;
    r.a = a && !a._error ? a : null; r.err = a && a._error;
    const m = (r.a && r.a.measures) || {};
    r.U = m.unusual == null ? null : +m.unusual;
    r.X = m.unexplained == null ? null : +m.unexplained;
    r.prevX = what.kind === "load" ? undefined : before.get(r.id);
    const v = (r.a && r.a.vessel) || {};
    if (v.name) r.name = v.name;
    r.cls = v.cls || (r.req.metadata && r.req.metadata.ship_type) || "";
    r.tier = v.profile_tier || (r.U == null && r.a ? "working" : "");
    r.work = r.tier === "working" || (r.a && r.U == null);
  });
  S.recordedSens = results[0] && results[0].configuration ? results[0].configuration.sensitivity : null;
  $("sens-rec").textContent = "· RECORDED " + (S.recordedSens == null ? "--" : (+S.recordedSens).toFixed(2));
  const nowTop = topCount();
  setStrip({ before: what.kind === "load" ? null : beforeTop, now: nowTop, what: describe(what) });
  renderBoard(what.kind !== "load");
  renderSheet(); scope();
}

async function apiAssess(opts) {
  const reqs = S.rows.map(r => Object.assign({}, r.req, { options: Object.assign({}, r.req.options || {}, opts) }));
  if (!S.batchMissing) {
    try {
      const j = await postJSON(API + "/assessments/batch", { requests: reqs, options: opts, persist: false });
      return Array.isArray(j) ? j : (j.results || []);
    } catch (e) {
      if (e.status !== 404 && e.status !== 405) throw e;
      S.batchMissing = true;
    }
  }
  const out = new Array(reqs.length); let next = 0;
  const worker = async () => {
    while (next < reqs.length) {
      const k = next++;
      try { out[k] = await postJSON(API + "/assessments", reqs[k], 60000); }
      catch (e) { out[k] = { _error: e.message }; }
    }
  };
  await Promise.all([0, 1, 2, 3].map(worker));
  if (out.every(o => o && o._error)) throw new Error(out[0]._error);
  return out;
}

/* SAMPLE mode only: replays the hand-made batch response and applies the documented formula
   X = U × Π(1 − e) over the enabled behaviour sources, so source toggles still work offline. */
async function sampleAssess(opts) {
  if (!S.sampleBatch) S.sampleBatch = await getJSON("sample/" + encodeURIComponent(S.kase.case_id) + ".batch.json", 30000);
  const en = new Set(opts.enabled_sources);
  await new Promise(r => setTimeout(r, 180));
  return (S.sampleBatch.results || []).map(a0 => {
    const a = JSON.parse(JSON.stringify(a0));
    a.findings = (a.findings || []).filter(f => en.has(f.source_id));
    const U = a.measures.unusual;
    if (U != null) {
      let X = U;
      a.findings.forEach(f => { if (f.status === "supports_explanation") X *= 1 - ((f.details && f.details.explains) || 0); });
      a.measures.unexplained = Math.round(X * 1000) / 1000;
    }
    a.lamps = {};
    a.findings.forEach(f => {
      const k = SRC_FX[f.source_id];
      if (k) a.lamps[k] = { supports_explanation: "explains", weakens_explanation: "not_explained", unavailable: "unavailable" }[f.status] || "neutral";
    });
    const g = a.signature;
    if (g && !a.findings.some(f => f.details && f.details.band_shift)) {
      g.expected_adjusted_kn = g.expected_profile_kn.slice(); g.band_adjusted_kn = g.band_profile_kn.slice();
      if (U != null) g.state = g.observed_kn.map((o, t) => Math.abs(o - g.expected_profile_kn[t]) > g.band_profile_kn[t] ? 2 : 0);
    }
    a.configuration = Object.assign({}, a.configuration, { sensitivity: opts.sensitivity, enabled_sources: opts.enabled_sources });
    a.limitations = (a.limitations || []).concat("Scored in the browser from the sample file because the ALIBI API is offline.");
    return a;
  });
}

function topCount(s) { const t = th(s); return S.rows.filter(r => r.X != null && r.X >= t).length; }
function describe(w) {
  if (w.kind === "load") return "RUN · " + S.enabled.size + " OF " + S.sources.length + " SOURCES ON";
  if (w.kind === "src") return "WITH " + srcLabel(w.id) + (w.on ? " ON" : " OFF");
  if (w.kind === "sens") return "SENSITIVITY " + (+w.prevSens).toFixed(2) + " → " + S.sens.toFixed(2);
  if (w.kind === "all") return "ALL SOURCES ON";
  if (w.kind === "base") return "PROFILE ONLY";
  return "";
}

/* ---------- strip ---------- */
let stripTween = 0;
function setStrip(o) {
  const strip = $("strip");
  strip.classList.toggle("err", !!o.error);
  if (o.busy) { $("strip-what").textContent = "RUNNING " + (S.sample ? "SAMPLE" : "ALIBI API") + " …"; return; }
  if (o.error) { $("strip-what").textContent = o.error; return; }
  const hasB = o.before != null && o.before !== undefined;
  $("strip-before").hidden = !hasB; $("strip-arrow").hidden = !hasB;
  if (hasB) $("strip-before").textContent = o.before;
  const now = $("strip-now");
  const from = hasB ? o.before : o.now;
  const id = ++stripTween;
  if (reduced() || from === o.now) now.textContent = o.now;
  else {
    const t0 = performance.now(), dur = 700;
    const step = t => { if (id !== stripTween) return; const k = Math.min(1, (t - t0) / dur); now.textContent = Math.round(from + (o.now - from) * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
  now.classList.remove("pop"); void now.offsetWidth; if (hasB && o.before !== o.now) now.classList.add("pop");
  now.style.color = o.now ? "" : "var(--ok)";
  $("strip-what").textContent = o.what || "";
  updateSub();
}
function updateSub() {
  const scored = S.rows.filter(r => r.X != null).length, work = S.rows.filter(r => r.work).length;
  $("strip-sub").textContent = S.rows.length + " candidates → " + topCount() + " in the top band" + (work ? " · " + work + " working, not scored" : "") + (scored < S.rows.length - work ? " · " + (S.rows.length - work - scored) + " not assessed" : "");
  $("sens-th").textContent = th().toFixed(2);
}

/* ---------- board ---------- */
function sortedRows() {
  const k = S.sortKey, val = r => k === "unu" ? r.U : r.X;
  return S.rows.slice().sort((a, b) => {
    if (k === "name") return a.name.localeCompare(b.name);
    const va = val(a), vb = val(b);
    if (va == null && vb == null) return a.name.localeCompare(b.name);
    if (va == null) return 1; if (vb == null) return -1;
    return vb - va || a.name.localeCompare(b.name);
  });
}
function boardMessage(html) { $("board").innerHTML = '<div class="empty">' + html + "</div>"; S.rowEls = new Map(); }
function xColor(v) { if (v == null) return tok("--dim"); const t = th(); return v >= t ? tok("--red") : v >= t / 2 ? tok("--amber") : tok("--ok"); }

function renderBoard(animate) {
  const board = $("board");
  if (!S.rows.length) { boardMessage("This case has no candidates."); return; }
  S.rowEls = S.rowEls || new Map();
  const first = new Map();
  if (animate) S.rowEls.forEach((el, id) => { if (el.isConnected) first.set(id, el.getBoundingClientRect().top); });
  const t = th(), list = sortedRows();
  const frag = document.createDocumentFragment();
  const byX = S.sortKey === "unx";
  const nTop = list.filter(r => r.X != null && r.X >= t).length;
  if (byX && nTop) { const c = document.createElement("div"); c.className = "caption"; c.textContent = "BEHAVING UNUSUALLY, AND THE AVAILABLE EVIDENCE DOES NOT EXPLAIN IT"; frag.appendChild(c); }
  list.forEach((r, k) => {
    let el = S.rowEls.get(r.id);
    if (!el) { el = makeRow(r); S.rowEls.set(r.id, el); }
    fillRow(el, r, t);
    frag.appendChild(el);
    if (byX && k === nTop - 1) {
      const cut = document.createElement("div"); cut.className = "cut";
      cut.textContent = "TOP BAND ENDS · UNEXPLAINED ≥ " + pct(t); frag.appendChild(cut);
    }
  });
  if (byX && !nTop) { const c = document.createElement("div"); c.className = "cut"; c.textContent = "NOTHING IN THE TOP BAND · UNEXPLAINED ≥ " + pct(t); frag.insertBefore(c, frag.firstChild); }
  board.innerHTML = ""; board.appendChild(frag);
  list.forEach(r => { const el = S.rowEls.get(r.id); drawRow(el, r); });
  if (animate && !reduced()) {
    list.forEach(r => {
      const el = S.rowEls.get(r.id), y0 = first.get(r.id);
      if (y0 == null) return;
      const dy = y0 - el.getBoundingClientRect().top;
      if (Math.abs(dy) < 2) return;
      el.classList.add("moving");
      el.style.transition = "none"; el.style.transform = "translateY(" + dy + "px)";
      requestAnimationFrame(() => requestAnimationFrame(() => {
        el.style.transition = "transform .75s cubic-bezier(.2,.75,.2,1)"; el.style.transform = "";
        setTimeout(() => el.classList.remove("moving"), 800);
      }));
    });
  }
}

function makeRow(r) {
  const el = document.createElement("div");
  el.className = "row"; el.tabIndex = -1; el.setAttribute("role", "option"); el.dataset.id = r.id;
  el.innerHTML = '<div class="delta"></div><div class="id"></div><canvas class="tr sp" aria-hidden="true"></canvas><canvas class="tr hd" aria-hidden="true"></canvas><div class="fx"></div>';
  el.addEventListener("click", () => { select(r.id, false); if (innerWidth <= 1100) $("sheet").scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "start" }); });
  el.addEventListener("keydown", e => {
    const rows = [...document.querySelectorAll("#board .row")], k = rows.indexOf(el);
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(r.id, false); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); const n = rows[Math.max(0, Math.min(rows.length - 1, k + (e.key === "ArrowDown" ? 1 : -1)))];
      if (n) select(n.dataset.id, true);
    } else if (e.key === "Home" || e.key === "End") { e.preventDefault(); const n = rows[e.key === "Home" ? 0 : rows.length - 1]; if (n) select(n.dataset.id, true); }
  });
  return el;
}

function fillRow(el, r, t, quiet) {
  const isTop = r.X != null && r.X >= t;
  el.classList.toggle("top", isTop); el.classList.toggle("work", !!r.work);
  el.setAttribute("aria-selected", String(r.id === S.sel));
  el.tabIndex = r.id === S.sel ? 0 : -1;
  const v = S.sortKey === "unu" ? r.U : r.X;
  const pv = S.sortKey === "unu" ? undefined : r.prevX;
  const changed = pv != null && v != null && Math.abs(pv - v) >= 0.005;
  const d = el.querySelector(".delta");
  d.style.color = xColor(v);
  d.innerHTML = '<span class="dv">' + (r.work ? "--" : pct(v)) + "</span>" +
    (changed ? '<span class="chg ' + (v < pv ? "down" : "up") + '" title="was ' + pct(pv) + '">' + (v < pv ? "▼" : "▲") + pct(pv) + "</span>" : "") +
    "<small>" + (r.work ? "NOT SCORED" : S.sortKey === "unu" ? "UNUSUAL" : "UNEXPL.") + "</small>" +
    (r.work || v == null ? "" : '<div class="meter"><i class="th" style="left:' + (S.sortKey === "unu" ? -10 : t * 100) + '%"></i>' +
      (changed ? '<span class="run" style="left:' + Math.min(pv, v) * 100 + "%;width:" + Math.abs(pv - v) * 100 + '%"></span><i class="gh" style="left:' + pv * 100 + '%"></i>' : "") +
      '<i class="cur" style="left:' + (changed && !quiet ? pv : v) * 100 + '%"></i></div>');
  if (changed && !quiet) {
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
    const cur = d.querySelector(".cur");
    requestAnimationFrame(() => requestAnimationFrame(() => { cur.style.left = v * 100 + "%"; }));
    if (!reduced()) tweenNum(d.querySelector(".dv"), pv, v);
  }
  const tier = r.work ? "working" : (r.tier || "");
  const tierTxt = { own: "OWN", prototype: "PROTOTYPE", journey: "JOURNEY", working: "WORK" }[tier] || (tier ? tier.toUpperCase() : "");
  const conf = r.a && r.a.confidence ? " · CONF " + String(r.a.confidence.level).toUpperCase() : "";
  el.querySelector(".id").innerHTML = '<b title="' + esc(r.name) + '">' + esc(r.name) + "</b><span>" + (tierTxt ? '<span class="tag ' + esc(tier) + '">' + tierTxt + "</span> " : "") +
    esc(clsText(r.cls)) + conf + (r.err ? " · ERROR" : "") + "</span>";
  const lamps = (r.a && r.a.lamps) || {};
  el.querySelector(".fx").innerHTML = FX.map(f => {
    const on = S.enabled.has(FX_SRC[f]), st = lamps[f];
    const c = !on ? "off" : st === "explains" ? "ex" : st === "not_explained" ? "no" : st === "unavailable" ? "na" : "";
    const word = !on ? "source off" : { explains: "explains", not_explained: "does not explain", unavailable: "no data", neutral: "neutral" }[st] || "not reported";
    return '<i class="' + c + '" title="' + FX_NAME[f] + ": " + word + '">' + f + "</i>";
  }).join("");
  el.setAttribute("aria-label", r.name + ", " + (r.work ? "working vessel, not scored" : "unexplained " + pct(r.X) + ", unusual " + pct(r.U)) + (isTop ? ", in the top band" : ""));
}
function tweenNum(node, a, b) {
  const t0 = performance.now(), dur = 650;
  const step = t => { const k = Math.min(1, (t - t0) / dur); node.textContent = Math.round((a + (b - a) * (1 - Math.pow(1 - k, 3))) * 100); if (k < 1 && node.isConnected) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function drawRow(el, r) {
  const g = sigOf(r);
  speedTrace(el.querySelector(".sp"), g, { work: r.work });
  headTrace(el.querySelector(".hd"), r, g, r.work);
}
function select(id, focus) {
  S.sel = id;
  document.querySelectorAll("#board .row").forEach(el => { const on = el.dataset.id === id; el.setAttribute("aria-selected", String(on)); el.tabIndex = on ? 0 : -1; if (on && focus) el.focus(); });
  renderSheet(); scope();
}
function clsText(c) { if (!c) return "CLASS UNKNOWN"; const [g, s] = String(c).split("/"); return (g || "").toUpperCase() + (s ? " · " + s.toUpperCase() : ""); }

/* ---------- traces ---------- */
function fit(cv) {
  const d = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  if (cv.width !== Math.round(w * d) || cv.height !== Math.round(h * d)) { cv.width = Math.round(w * d); cv.height = Math.round(h * d); }
  const g = cv.getContext("2d"); g.setTransform(d, 0, 0, d, 0, 0); g.clearRect(0, 0, w, h); return [g, w, h];
}
function grid(g, w, h, nx, ny) {
  g.strokeStyle = tok("--grid"); g.lineWidth = 1; g.beginPath();
  for (let i = 1; i < nx; i++) { const x = Math.round(w * i / nx) + .5; g.moveTo(x, 0); g.lineTo(x, h); }
  for (let j = 1; j < ny; j++) { const y = Math.round(h * j / ny) + .5; g.moveTo(0, y); g.lineTo(w, y); }
  g.stroke();
}
const msCache = new WeakMap();
function times(g) { let m = msCache.get(g); if (!m) { m = (g.t || []).map(t => Date.parse(t)); msCache.set(g, m); } return m; }
function idxAt(g, iso) {
  if (!iso) return -1; const T = times(g), v = Date.parse(iso); if (isNaN(v) || !T.length) return -1;
  for (let i = 0; i < T.length; i++) if (T[i] >= v) return i; return T.length - 1;
}
function sigOf(r) {
  const s = r.a && r.a.signature;
  if (s && s.observed_kn && s.observed_kn.length > 1) return s;
  if (!r._fallback) {
    const tr = r.req.track || [];
    r._fallback = { t: tr.map(p => p.timestamp), observed_kn: tr.map(p => +p.sog_knots || 0), missing: true,
      event_start: r.req.event && r.req.event.start_time, event_end: r.req.event && r.req.event.end_time };
  }
  return r._fallback;
}
function speedTrace(cv, s, o) {
  const [g, w, h] = fit(cv); const big = !!o.big, n = s.observed_kn.length;
  grid(g, w, h, big ? 12 : 6, big ? 4 : 2);
  if (n < 2) return;
  const obs = s.observed_kn, ep = s.expected_profile_kn, bp = s.band_profile_kn;
  const ea = s.expected_adjusted_kn || ep, ba = s.band_adjusted_kn || bp, st = s.state || [];
  let mx = 12; for (let t = 0; t < n; t++) { mx = Math.max(mx, obs[t] || 0, ea ? ea[t] + ba[t] : 0, ep ? ep[t] + bp[t] : 0); }
  const max = mx * 1.08, X = t => t / (n - 1) * w, Y = v => h - 4 - (Math.max(0, v) / max) * (h - 8);
  // event window
  const i0 = idxAt(s, s.event_start), i1 = idxAt(s, s.event_end);
  if (i0 >= 0) {
    const x0 = X(i0), x1 = i1 >= i0 ? X(i1) : w;
    g.fillStyle = big ? "rgba(255,181,61,.10)" : "rgba(255,181,61,.06)"; g.fillRect(x0, 0, Math.max(2, x1 - x0), h);
    if (big) {
      g.strokeStyle = tok("--amber"); g.globalAlpha = .7; g.setLineDash([3, 3]); g.beginPath();
      g.moveTo(Math.round(x0) + .5, 0); g.lineTo(Math.round(x0) + .5, h); if (i1 > i0 && i1 < n - 1) { g.moveTo(Math.round(x1) + .5, 0); g.lineTo(Math.round(x1) + .5, h); }
      g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
      g.fillStyle = tok("--amber"); g.font = "10px " + tok("--f-data"); g.fillText("EVENT", Math.min(x0 + 4, w - 40), 22);
    }
  }
  if (ea && ba && !o.work) {
    g.beginPath(); for (let t = 0; t < n; t++) { const y = Y(ea[t] + ba[t]); t ? g.lineTo(X(t), y) : g.moveTo(X(t), y); }
    for (let t = n - 1; t >= 0; t--) g.lineTo(X(t), Y(ea[t] - ba[t])); g.closePath();
    g.fillStyle = tok("--band-fill"); g.fill();
    g.strokeStyle = tok("--band-edge"); g.lineWidth = 1;
    [1, -1].forEach(k => { g.beginPath(); for (let t = 0; t < n; t++) { const y = Y(ea[t] + k * ba[t]); t ? g.lineTo(X(t), y) : g.moveTo(X(t), y); } g.stroke(); });
    if (ep && bp) { // profile alone, dashed, only where the factors moved the band
      g.setLineDash([2, 4]);
      [1, -1].forEach(k => { g.beginPath(); let on = false; for (let t = 0; t < n; t++) { const moved = Math.abs(ea[t] - ep[t]) > .05 || Math.abs(ba[t] - bp[t]) > .05; const y = Y(ep[t] + k * bp[t]); if (moved) { on ? g.lineTo(X(t), y) : g.moveTo(X(t), y); on = true; } else on = false; } g.stroke(); });
      g.setLineDash([]);
    }
  }
  g.lineWidth = big ? 1.7 : 1.4;
  const cols = [tok("--trace"), tok("--amber"), tok("--red")], dim = tok("--dim");
  for (let t = 1; t < n; t++) {
    g.strokeStyle = o.work || s.missing ? dim : cols[st[t] || 0];
    g.beginPath(); g.moveTo(X(t - 1), Y(obs[t - 1])); g.lineTo(X(t), Y(obs[t])); g.stroke();
  }
  g.fillStyle = tok("--dim"); g.font = "10px " + tok("--f-data"); g.fillText(Math.round(max) + " kn", 3, 11);
  if (s.missing) g.fillText("no signature", w - 80, 11);
  if (big) {
    const T = times(s), hm = v => isNaN(v) ? "" : new Date(v).toISOString().slice(11, 16);
    g.fillText(hm(T[0]), 3, h - 4); const e = hm(T[n - 1]) + " UTC"; g.fillText(e, w - g.measureText(e).width - 3, h - 4);
    if (ea && ep) { const t0 = ea.findIndex((v, t) => Math.abs(v - ep[t]) > .05 || Math.abs(ba[t] - bp[t]) > .05); if (t0 >= 0) { g.fillStyle = tok("--band-edge"); g.fillText("band adjusted by evidence", Math.min(X(t0) + 4, w - 160), Math.max(34, Y(ea[n - 1] + ba[n - 1]) - 6)); } }
  }
}
function headTrace(cv, r, s, work) {
  const [g, w, h] = fit(cv); grid(g, w, h, 6, 2);
  const tr = r.req.track || []; if (tr.length < 2) return;
  const T = times(s), t0 = T[0], t1 = T[T.length - 1], span = (t1 - t0) || 1;
  const pts = tr.map(p => [Date.parse(p.timestamp), p.heading_degrees != null && p.heading_degrees < 360 ? p.heading_degrees : p.cog_degrees]).filter(p => p[1] != null && !isNaN(p[0]));
  if (!pts.length) return;
  const useT = !isNaN(t0) && T.length > 1;
  const X = (p, k) => useT ? (p[0] - t0) / span * w : k / (pts.length - 1) * w, Y = a => { a = ((a % 360) + 360) % 360; return h - 3 - a / 360 * (h - 6); };
  g.strokeStyle = work ? tok("--dim") : tok("--trace"); g.lineWidth = 1.2; g.beginPath();
  let prev = null; pts.forEach((p, k) => { const x = X(p, k), y = Y(p[1]); if (prev === null || Math.abs(y - prev) > h * .5) g.moveTo(x, y); else g.lineTo(x, y); prev = y; });
  g.stroke(); g.fillStyle = tok("--dim"); g.font = "10px " + tok("--f-data"); g.fillText("360", 3, 11);
}

/* ---------- recognition sheet ---------- */
function kindOf(cls) {
  const g = String(cls || "").split("/")[0].toLowerCase();
  if (/tank/.test(g)) return "tanker"; if (/bulk/.test(g)) return "bulk";
  if (/pass|ferry|ro.?pax|cruise/.test(g)) return "ferry";
  if (/tug|pilot|sar|work|service|fish|pleasure|tow|dredg/.test(g)) return "tug";
  return "cargo";
}
function silhouette(cv, kind) {
  const [g, w, h] = fit(cv); g.fillStyle = tok("--ink"); const L = w * .94, x0 = (w - L) / 2, wl = h * .78, fb = h * .16;
  g.beginPath(); g.moveTo(x0, wl - fb); g.lineTo(x0 + L * .97, wl - fb); g.lineTo(x0 + L, wl - fb - 4); g.lineTo(x0 + L * .95, wl + h * .1); g.lineTo(x0 + L * .03, wl + h * .1); g.closePath(); g.fill();
  const box = (a, b, top) => g.fillRect(x0 + L * a, wl - fb - top, L * (b - a), top);
  if (kind === "tanker") { box(.03, .17, h * .42); box(.05, .13, h * .52); box(.08, .10, h * .62); g.fillRect(x0 + L * .2, wl - fb - 5, L * .72, 5); for (let k = 0; k < 6; k++) g.fillRect(x0 + L * (.25 + k * .11), wl - fb - 10, 3, 10); }
  if (kind === "cargo" || kind === "bulk") { box(.03, .15, h * .45); box(.05, .12, h * .55); for (let k = 0; k < (kind === "bulk" ? 5 : 4); k++) { g.fillRect(x0 + L * (.2 + k * .16), wl - fb - h * .12, L * .12, h * .12); if (kind === "cargo") g.fillRect(x0 + L * (.29 + k * .16), wl - fb - h * .45, 3, h * .33); } box(.93, .98, h * .08); }
  if (kind === "ferry") { box(.04, .92, h * .32); box(.12, .80, h * .44); box(.30, .62, h * .54); g.fillRect(x0 + L * .18, wl - fb - h * .62, L * .06, h * .2); }
  if (kind === "tug") { box(.04, .45, h * .2); box(.38, .62, h * .42); box(.45, .55, h * .6); }
  g.strokeStyle = tok("--ink-2"); g.setLineDash([2, 3]); g.beginPath(); g.moveTo(0, wl + .5); g.lineTo(w, wl + .5); g.stroke(); g.setLineDash([]);
}
const TIER_TXT = { own: "OWN PROFILE", prototype: "CLASS PROTOTYPE", journey: "JOURNEY BASELINE", working: "WORKING VESSEL · NOT SCORED" };

function renderSheet() {
  const el = $("sheet"), r = S.rows.find(x => x.id === S.sel);
  if (!r) { el.innerHTML = '<p class="foot">Select a row to open its recognition sheet.</p>'; return; }
  const a = r.a || {}, conf = a.confidence || {}, cfg = a.configuration || {}, ev = a.event || r.req.event || {}, v = a.vessel || {};
  const findings = a.findings || [];
  const isId = f => f.status === "identity_context_only" || f.source_id === "identity";
  const beh = findings.filter(f => !isId(f)), ids = findings.filter(isId);
  const t = th(), hotU = r.U != null && r.U >= t, hotX = r.X != null && r.X >= t;
  const was = x => r.prevX != null && Math.abs(r.prevX - r.X) >= 0.005 && x === "X" ? "<em>was " + pct(r.prevX) + "</em>" : "";
  const stamp = $("replay-stamp").hidden ? "" : '<div class="stamp">' + esc($("replay-stamp").textContent) + "</div>";
  const srcTitle = id => (S.sources.find(s => s.id === id) || {}).title || srcLabel(id);
  const factLine = f => {
    const [c, label] = STATUS[f.status] || ["", String(f.status || "").toUpperCase()];
    const e = f.details && typeof f.details.explains === "number" && f.status === "supports_explanation" ? " · explains " + Math.round(f.details.explains * 100) + " %" : "";
    return '<li class="' + c + '"><b>' + label + '</b><span><span class="src">' + esc(srcLabel(f.source_id)) + e + "</span>" + esc(f.summary) + "</span></li>";
  };
  const refs = findings.filter(f => f.source_reference).map(f => esc(srcLabel(f.source_id)) + ": " + esc(f.source_reference) + (f.observed_at ? " · " + esc(f.observed_at) : ""));
  const pos = r.req.event && r.req.event.location;
  el.innerHTML = stamp +
    '<div class="cls">RECOGNITION SHEET · ' + esc(clsText(r.cls)) + "</div><h2>" + esc(r.name) + "</h2>" +
    '<canvas id="sil" aria-hidden="true"></canvas><div class="dims"><span>LOA ' + (r.loa ? esc(Math.round(r.loa)) + " m" : "--") + "</span><span>MMSI " + esc(v.mmsi || ev.vessel_id || "--") + "</span><span>IMO " + esc(v.imo || r.imo || "--") + "</span><span>SIDE VIEW · NOT TO SCALE</span></div>" +
    '<dl class="kv"><dt>PROFILE</dt><dd>' + esc(TIER_TXT[r.tier] || (r.tier || "--").toUpperCase()) + "</dd>" +
    "<dt>CONFIDENCE</dt><dd>" + esc(String(conf.level || "--").toUpperCase()) + "</dd>" +
    "<dt>EVENT</dt><dd>" + esc((ev.event_type || "--").toUpperCase()) + " · " + esc(fmtT(ev.start_time)) + "–" + esc(fmtT(ev.end_time, true)) + "</dd>" +
    (pos ? "<dt>POSITION</dt><dd>" + (+pos.latitude).toFixed(3) + "° N " + (+pos.longitude).toFixed(3) + "° E</dd>" : "") + "</dl>" +
    (conf.reasons && conf.reasons.length ? '<ul class="reasons">' + conf.reasons.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") +
    '<div class="measures"><div class="measure' + (hotU ? " hot" : "") + '"><span>UNUSUAL</span><b>' + (r.U == null ? "--" : pct(r.U) + "<small> / 100</small>") + "</b><em>deviation from the expected band</em></div>" +
    '<div class="measure' + (hotX ? " hot" : "") + '"><span>UNEXPLAINED</span><b>' + (r.X == null ? "--" : pct(r.X) + "<small> / 100</small>") + "</b>" + (was("X") || "<em>what the evidence leaves open</em>") + "</div></div>" +
    (r.work ? '<p class="foot" style="margin-top:0">Working vessels loiter and turn for a living. Shown, not scored.</p>' : "") +
    (r.err ? '<p class="foot" style="color:var(--stamp)">The API returned an error for this candidate: ' + esc(r.err) + "</p>" : "") +
    '<div class="cls">SPEED · RECORDED vs EXPECTED · EVENT WINDOW MARKED</div><div class="sig"><canvas id="sig" aria-label="Speed signature" role="img"></canvas></div>' +
    '<div class="cls" style="margin-bottom:6px">FACTORS CHECKED</div>' +
    (beh.length ? '<ul class="facts">' + beh.map(factLine).join("") + "</ul>" : '<p class="foot" style="margin-top:0">' + (r.a ? "Only the profile was used in this run. Switch sources on to check what explains the behaviour." : "Not assessed yet.") + "</p>") +
    '<section class="identity" aria-label="Identity context"><div class="cls">IDENTITY CONTEXT — NOT PART OF THE SCORE</div>' +
    (!S.enabled.has("identity") ? "<p>Identity lists are switched off for this run.</p>" :
      ids.length ? ids.map(f => "<p>" + esc(f.summary) + (f.source_reference ? "<small>" + esc(f.source_reference) + "</small>" : "") + "</p>").join("") : "<p>No identity findings returned.</p>") + "</section>" +
    '<details class="audit"><summary>AUDIT</summary><dl class="kv">' +
    kv("API VERSION", a.api_version) + kv("MODEL", cfg.model_version) + kv("PROFILES", cfg.profile_version) +
    kv("SENSITIVITY", cfg.sensitivity == null ? null : (+cfg.sensitivity).toFixed(2)) + kv("SOURCES", (cfg.enabled_sources || []).join(", ")) +
    kv("DETECTED BY", cfg.detected_by) + kv("ASSESSMENT", a.assessment_id) + kv("ASSESSED AT", a.assessed_at) + kv("AUDIT REF", a.audit_reference) + kv("EVENT ID", ev.event_id) +
    "</dl>" + (refs.length ? '<div class="cls">SOURCE REFERENCES</div><ul>' + refs.map(x => "<li>" + x + "</li>").join("") + "</ul>" : "") +
    ((a.limitations || []).length ? '<div class="cls">LIMITATIONS</div><ul>' + a.limitations.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") +
    '<div class="keys"><button class="key" type="button" id="copy-json">COPY JSON</button><button class="key" type="button" id="dl-json">DOWNLOAD JSON</button></div></details>' +
    '<p class="foot">Sentences are fixed and written by people. The model only picks which one applies. A flag says the sea does not explain the behaviour. It does not say why.</p>';
  silhouette($("sil"), kindOf(r.cls));
  speedTrace($("sig"), sigOf(r), { big: true, work: r.work });
  const raw = () => JSON.stringify(r.a || { error: r.err || "not assessed", request_event: r.req.event }, null, 2);
  $("copy-json").onclick = async e => {
    const b = e.currentTarget;
    try { await navigator.clipboard.writeText(raw()); b.textContent = "COPIED"; }
    catch (err) { const ta = document.createElement("textarea"); ta.value = raw(); document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); b.textContent = "COPIED"; } catch (x) { b.textContent = "COPY FAILED"; } ta.remove(); }
    setTimeout(() => { b.textContent = "COPY JSON"; }, 1500);
  };
  $("dl-json").onclick = () => {
    const url = URL.createObjectURL(new Blob([raw()], { type: "application/json" }));
    const l = document.createElement("a"); l.href = url; l.download = "alibi-" + (a.assessment_id || r.id) + ".json"; document.body.appendChild(l); l.click(); l.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };
}
function kv(k, v) { return v == null || v === "" ? "" : "<dt>" + k + "</dt><dd>" + esc(v) + "</dd>"; }
function fmtT(iso, short) { const d = Date.parse(iso); if (isNaN(d)) return "--"; const s = new Date(d).toISOString(); return short ? s.slice(11, 16) + " UTC" : s.slice(0, 10) + " " + s.slice(11, 16); }

/* ---------- chart scope ---------- */
const REGIONS = {
  gof: { name: "GULF OF FINLAND", lo: [21, 30.6], la: [59.1, 60.9],
    land: [[[21, 61], [21.3, 60.6], [22, 60.3], [22.6, 60.05], [23.3, 59.92], [24, 60.1], [25, 60.2], [26, 60.42], [27, 60.5], [28, 60.55], [28.7, 60.7], [29.5, 60.25], [30.2, 60.0], [31, 60.0], [31, 61]],
      [[21, 59.0], [23.4, 59.2], [24, 59.42], [24.8, 59.46], [25.6, 59.56], [26.5, 59.55], [27.5, 59.45], [28.1, 59.42], [28.7, 59.6], [29.5, 59.92], [30.2, 59.95], [31, 59.9], [31, 59], [21, 59]]],
    labels: [["HELSINKI", 24.6, 60.3], ["TALLINN", 24.4, 59.32]] },
  dk: { name: "DANISH STRAITS", lo: [7.8, 15.5], la: [54.2, 58.0],
    land: [
      [[7.6, 54.9], [8.6, 55.4], [8.1, 55.6], [8.2, 56.1], [8.1, 56.6], [8.6, 57.1], [9.6, 57.2], [10.6, 57.75], [10.4, 57.2], [10.3, 56.7], [10.9, 56.45], [10.3, 56.2], [10.2, 55.85], [9.7, 55.6], [9.8, 55.3], [9.5, 55.0], [9.9, 54.8], [10.0, 54.55], [10.9, 54.35], [11.1, 54.0], [12.3, 54.25], [13.2, 54.55], [13.7, 54.2], [14.3, 53.95], [15.7, 54.15], [15.7, 53.7], [7.6, 53.7]],
      [[9.7, 55.5], [10.2, 55.6], [10.6, 55.45], [10.8, 55.1], [10.6, 54.95], [10.2, 55.05], [9.75, 55.2]],
      [[10.9, 55.7], [11.2, 55.95], [11.9, 56.1], [12.6, 56.05], [12.6, 55.6], [12.3, 55.4], [12.2, 55.1], [11.7, 55.15], [11.2, 55.2], [11.1, 55.5]],
      [[11.0, 54.85], [11.6, 54.85], [12.0, 54.95], [12.0, 54.6], [11.4, 54.65], [11.0, 54.75]],
      [[12.5, 58.2], [11.9, 57.7], [12.0, 57.3], [12.6, 56.6], [12.9, 56.2], [12.6, 56.0], [13.0, 55.4], [14.2, 55.4], [14.4, 55.7], [14.8, 56.15], [15.7, 56.15], [15.7, 58.2]],
      [[14.7, 55.1], [15.1, 55.15], [15.15, 55.0], [14.75, 54.98]]],
    labels: [["COPENHAGEN", 12.0, 55.85], ["SKAGEN", 10.0, 57.85], ["KIEL", 9.6, 54.45]] }
};
function regionName(k) { return (REGIONS[k] && REGIONS[k].name) || String(k || "REGION").toUpperCase(); }
function rowPos(r) {
  const l = r.req.event && r.req.event.location; if (l && l.latitude != null) return [+l.longitude, +l.latitude];
  const tr = r.req.track || []; const p = tr[tr.length - 1]; return p ? [+p.longitude, +p.latitude] : null;
}
function scope() {
  const cv = $("scope"), [g, w, h] = fit(cv);
  grid(g, w, h, 10, 4);
  let R = REGIONS[S.kase && S.kase.region];
  if (!R) {
    const ps = S.rows.map(rowPos).filter(Boolean);
    if (!ps.length) return;
    const lo = [Math.min(...ps.map(p => p[0])) - .5, Math.max(...ps.map(p => p[0])) + .5], la = [Math.min(...ps.map(p => p[1])) - .3, Math.max(...ps.map(p => p[1])) + .3];
    R = { lo, la, land: [], labels: [] };
  }
  const X = x => (x - R.lo[0]) / (R.lo[1] - R.lo[0]) * w, Y = y => h - (y - R.la[0]) / (R.la[1] - R.la[0]) * h;
  R.land.forEach(p => { g.beginPath(); p.forEach(([x, y], k) => k ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.closePath(); g.fillStyle = tok("--screen-2"); g.fill(); g.strokeStyle = tok("--dim"); g.lineWidth = 1; g.stroke(); });
  g.font = "9px " + tok("--f-data");
  if (S.corridors && S.corridors.features) {
    g.strokeStyle = tok("--amber"); g.globalAlpha = .6; g.setLineDash([4, 4]); g.lineWidth = 1;
    const line = cs => { g.beginPath(); cs.forEach(([x, y], k) => k ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.stroke(); };
    S.corridors.features.forEach(f => {
      const geo = f.geometry || {}, c = geo.coordinates || [];
      if (geo.type === "LineString") line(c);
      else if (geo.type === "MultiLineString" || geo.type === "Polygon") c.forEach(line);
      else if (geo.type === "MultiPolygon") c.forEach(p => p.forEach(line));
    });
    g.setLineDash([]); g.globalAlpha = 1;
  }
  g.fillStyle = tok("--dim"); R.labels.forEach(([t, x, y]) => g.fillText(t, X(x), Y(y)));
  const selRow = S.rows.find(r => r.id === S.sel);
  S.rows.slice().sort((a, b) => (a.X ?? -1) - (b.X ?? -1)).forEach(r => {
    const p = rowPos(r); if (!p) return;
    const x = X(p[0]), y = Y(p[1]), c = xColor(r.X);
    g.fillStyle = c; g.strokeStyle = c; g.lineWidth = 1;
    if (r.X == null) g.strokeRect(x - 3, y - 3, 6, 6); else { g.beginPath(); g.arc(x, y, r.X >= th() ? 4 : 3, 0, 7); g.fill(); }
    const tr = r.req.track || [], last = tr[tr.length - 1];
    const hd = last && (last.heading_degrees != null && last.heading_degrees < 360 ? last.heading_degrees : last.cog_degrees);
    if (hd != null) { const ang = (hd - 90) * Math.PI / 180; g.beginPath(); g.moveTo(x, y); g.lineTo(x + Math.cos(ang) * 12, y + Math.sin(ang) * 12); g.stroke(); }
  });
  if (selRow) {
    const p = rowPos(selRow); if (p) {
      const x = X(p[0]), y = Y(p[1]); g.strokeStyle = tok("--paper"); g.lineWidth = 1; g.strokeRect(x - 8, y - 8, 16, 16);
      g.fillStyle = tok("--paper"); const tw = g.measureText(selRow.name).width; g.fillText(selRow.name, x + 11 + tw > w ? x - 11 - tw : x + 11, y - 9);
    }
  }
  g.fillStyle = tok("--dim"); g.fillText(R.lo[0] + "°E", 3, h - 4); const e = R.lo[1] + "°E"; g.fillText(e, w - g.measureText(e).width - 3, h - 4);
}

/* ---------- controls ---------- */
function renderSourceKeys() {
  const box = $("source-keys"); box.innerHTML = "";
  S.sources.forEach(s => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "key kind-" + (s.kind || "behaviour");
    b.dataset.src = s.id;
    const locked = s.id === "profile";
    b.setAttribute("aria-pressed", String(S.enabled.has(s.id)));
    if (locked) { b.classList.add("locked"); b.setAttribute("aria-disabled", "true"); }
    b.innerHTML = esc(srcLabel(s.id)) + (s.kind && s.kind !== "behaviour" ? '<span class="k-kind">' + esc(s.kind.toUpperCase()) + "</span>" : "");
    b.title = [s.title, locked ? "always on: the baseline" : s.kind === "identity" ? "context only, never changes the score" : s.kind === "quality" ? "changes confidence only" : null, s.attribution].filter(Boolean).join(" · ");
    b.onclick = () => {
      if (locked || !S.kase) return;
      const on = !S.enabled.has(s.id);
      on ? S.enabled.add(s.id) : S.enabled.delete(s.id);
      b.setAttribute("aria-pressed", String(on));
      run({ kind: "src", id: s.id, on });
    };
    box.appendChild(b);
  });
  const sep = document.createElement("span"); sep.style.width = "8px"; box.appendChild(sep);
  [["PROFILE ONLY", "base"], ["ALL ON", "all"]].forEach(([label, kind]) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "key"; b.textContent = label;
    b.onclick = () => {
      if (!S.kase) return;
      S.enabled = new Set(kind === "all" ? S.sources.map(s => s.id) : ["profile"]);
      box.querySelectorAll("[data-src]").forEach(k => k.setAttribute("aria-pressed", String(S.enabled.has(k.dataset.src))));
      run({ kind });
    };
    box.appendChild(b);
  });
}

function wireControls() {
  document.querySelectorAll(".sortkeys .key").forEach(b => b.onclick = () => {
    S.sortKey = b.dataset.sort;
    document.querySelectorAll(".sortkeys .key").forEach(k => k.setAttribute("aria-pressed", String(k === b)));
    S.rows.forEach(r => { r.prevX = undefined; });
    renderBoard(true);
  });
  const sl = $("sens"); let sensFrom = S.sens;
  sl.addEventListener("pointerdown", () => { sensFrom = S.sens; });
  sl.addEventListener("keydown", () => { if (!sl._k) { sensFrom = S.sens; sl._k = true; } });
  sl.addEventListener("input", () => {
    S.sens = +sl.value; $("sens-val").textContent = S.sens.toFixed(2);
    if (!S.rows.length) { $("sens-th").textContent = th().toFixed(2); return; }
    $("strip-now").textContent = topCount(); updateSub();
    if (S.rowEls) S.rows.forEach(r => { const el = S.rowEls.get(r.id); if (el) fillRow(el, r, th(), true); });
  });
  sl.addEventListener("change", () => {
    sl._k = false;
    if (Math.abs(sensFrom - S.sens) < 1e-9) return;
    run({ kind: "sens", prevSens: sensFrom }); sensFrom = S.sens;
  });
  const dlg = $("about");
  $("about-open").onclick = () => { if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", ""); };
  $("about-close").onclick = () => { if (dlg.close) dlg.close(); else dlg.removeAttribute("open"); };
  dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (S.rows.length && S.rowEls) { S.rows.forEach(r => { const el = S.rowEls.get(r.id); if (el && el.isConnected) drawRow(el, r); }); renderSheet(); } scope(); }, 150); });
}
function tick() { $("clock").textContent = new Date().toISOString().slice(11, 19) + " UTC"; }

(document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(boot, boot);
})();
