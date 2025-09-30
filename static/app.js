// static/app.js — instant scroll, SVG reputation chart (no libraries), clears search on refresh
"use strict";

const API = ""; // same-origin

// ---------- DOM ----------
const resultsEl    = document.getElementById("results");
const paperSection = document.getElementById("paperSection");
const abstractEl   = document.getElementById("abstract");
const summBtn      = document.getElementById("summBtn");
const summaryText  = document.getElementById("summaryText");

// Reputation UI
const repExplain   = document.getElementById("repExplain");
const repBadge     = document.getElementById("repBadge");
const repMeter     = document.getElementById("repMeter");
const repBreakdown = document.getElementById("repBreakdown");
const repChartSvgC = document.getElementById("repChartSvg");

// Filters
const openFilters     = document.getElementById("openFilters");
const filterDrawer    = document.getElementById("filterDrawer");
const closeFilters    = document.getElementById("closeFilters");
const expandFilters   = document.getElementById("expandFilters");
const advancedFilters = document.getElementById("advancedFilters");
const applyFilters    = document.getElementById("applyFilters");
const clearBtn        = document.getElementById("clearBtn");

const startYear        = document.getElementById("startYear");
const endYear          = document.getElementById("endYear");
const textAvailability = document.getElementById("textAvailability");
const articleAttribute = document.getElementById("articleAttribute");
const articleType      = document.getElementById("articleType");
const languageSel      = document.getElementById("language");
const species          = document.getElementById("species");
const sex              = document.getElementById("sex");
const age              = document.getElementById("age");
const other            = document.getElementById("other");

// Search bar
const queryEl   = document.getElementById("query");
const searchBtn = document.getElementById("searchBtn");

// State
let CURRENT_PMID = null;

// ---------- On load: clear any persisted search text ----------
(function clearSearchOnLoad(){
  const wipe = () => { if (queryEl) queryEl.value = ""; };
  document.addEventListener("DOMContentLoaded", wipe);
  window.addEventListener("pageshow", (e) => { if (e.persisted) wipe(); });
})();

// ---------- Utils ----------
function h(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v);
  }
  (Array.isArray(children) ? children : [children]).forEach(ch => {
    if (ch == null) return;
    if (typeof ch === "string") el.appendChild(document.createTextNode(ch));
    else el.appendChild(ch);
  });
  return el;
}

function setStatus(target, msg) { if (target) target.textContent = msg; }

async function fetchJSON(url, opts = {}, timeoutMs = 15000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal });
    const txt = await res.text();
    let data;
    try { data = JSON.parse(txt); } catch { throw new Error(`HTTP ${res.status} (non-JSON)`); }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return data;
  } finally { clearTimeout(t); }
}

const clamp01To100 = v => Math.max(0, Math.min(100, Math.round(Number(v) || 0)));
function computeLevel(total) {
  return total < 40 ? "Low" : total < 60 ? "Medium" : total < 80 ? "High" : "Very High";
}

// ---------- Filters drawer ----------
openFilters?.addEventListener("click", () => {
  filterDrawer.classList.remove("hidden");
  filterDrawer.scrollIntoView({ behavior: "auto", block: "start" });
});
closeFilters?.addEventListener("click", () => filterDrawer.classList.add("hidden"));
expandFilters?.addEventListener("click", () => {
  advancedFilters.classList.toggle("hidden");
  expandFilters.textContent = advancedFilters.classList.contains("hidden")
    ? "+ See all the filters"
    : "− Hide extra filters";
});
clearBtn?.addEventListener("click", () => {
  textAvailability && (textAvailability.value = "Any");
  languageSel      && (languageSel.value      = "Any");
  articleAttribute && (articleAttribute.value = "None");
  articleType      && (articleType.value      = "None");
  species          && (species.value          = "Any");
  sex              && (sex.value              = "Any");
  age              && (age.value              = "Any");
  other            && (other.value            = "None");
});
applyFilters?.addEventListener("click", () => { filterDrawer.classList.add("hidden"); doSearch(); });

// ---------- Search ----------
searchBtn?.addEventListener("click", doSearch);
queryEl?.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

async function doSearch() {
  const q = (queryEl?.value || "").trim();
  if (!q) return;
  setStatus(resultsEl, "Searching…");

  const params = new URLSearchParams({
    query: q,
    start_year: (startYear?.value || "2000"),
    end_year: (endYear?.value || String(new Date().getFullYear())),
    text_availability: (textAvailability?.value || "Any"),
    article_attribute: (articleAttribute?.value || "None"),
    article_type: (articleType?.value || "None"),
    language: (languageSel?.value || "Any"),
    species: (species?.value || "Any"),
    sex: (sex?.value || "Any"),
    age: (age?.value || "Any"),
    other: (other?.value || "None")
  });

  let payload;
  try {
    payload = await fetchJSON(`${API}/api/search?${params.toString()}`, {}, 20000);
  } catch {
    setStatus(resultsEl, "Search failed.");
    return;
  }
  if (!payload || !Array.isArray(payload.results) || payload.results.length === 0) {
    const term = payload && payload.term ? `\n\nBuilt term:\n${payload.term}` : "";
    setStatus(resultsEl, "No results." + term);
    return;
  }
  renderResults(payload.results);
}

function renderResults(items) {
  if (!items || !items.length) { setStatus(resultsEl, "No results."); return; }
  resultsEl.innerHTML = "";
  items.forEach(it => {
    const title = h("div", {class: "title"}, it.title || "(no title)");
    const meta  = h("div", {class: "meta"}, `${it.journal || ""} • ${it.year || ""} • ${it.authors || ""}`);
    const btns  = h("div", {class: "actions"}, [
      h("button", {class: "secondary"}, "Abstract"),
      h("button", {}, "Select")
    ]);
    const card = h("div", {class: "card"}, [title, meta, btns]);
    resultsEl.appendChild(card);

    btns.children[0].addEventListener("click", async () => {
      try { const j = await fetchJSON(`${API}/api/abstract/${it.pmid}`, {}, 20000);
        alert((j?.abstract || "No abstract."));
      } catch { alert("Failed to fetch abstract."); }
    });

    btns.children[1].addEventListener("click", () => selectPaper(it.pmid));
  });
}

async function selectPaper(pmid) {
  CURRENT_PMID = pmid;
  paperSection.classList.remove("hidden");

  // Instant placeholder reputation and chart (no empty gap)
  renderReputation({});

  // Abstract
  try { const aj = await fetchJSON(`${API}/api/abstract/${pmid}`, {}, 20000);
    abstractEl.textContent = aj?.abstract || "";
  } catch { abstractEl.textContent = ""; }

  // Reputation
  try { const rep = await fetchJSON(`${API}/api/reputation/${pmid}`, {}, 25000);
    renderReputation(rep || {});
  } catch {}

  // Jump to section immediately
  paperSection.scrollIntoView({ behavior: "auto", block: "start" });
}

// ---------- Summarize ----------
summBtn?.addEventListener("click", async () => {
  const text = abstractEl.textContent.trim();
  if (!text) return;
  summaryText.textContent = "Summarizing…";
  try {
    const j = await fetchJSON(`${API}/api/summarize`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ text })
    }, 60000);
    summaryText.textContent = j?.summary || "";
  } catch { summaryText.textContent = "Summary failed."; }
});

// ---------- Reputation (SVG chart + CSS rows) ----------
function renderReputation(raw = {}) {
  // Normalize components
  let comps = {};
  if (raw && typeof raw === "object" && raw.components && typeof raw.components === "object") {
    comps = { ...raw.components };
  }
  if (!Object.keys(comps).length) {
    comps = { "Citations": 40, "Open Access": 60, "Recency": 70, "Journal Activity": 50, "Author Activity": 55 };
  }
  for (const k of Object.keys(comps)) comps[k] = clamp01To100(comps[k]);

  // Total / level
  let total = Number.isFinite(raw.total) ? Number(raw.total) : null;
  if (!Number.isFinite(total)) {
    const vals = Object.values(comps);
    total = vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : 0;
  }
  total = clamp01To100(total);
  const level = (raw.level && String(raw.level)) || computeLevel(total);

  // Badge + meter + explain
  if (repBadge) {
    repBadge.textContent = `${level} • ${total}`;
    repBadge.className = "badge " + level.toLowerCase().replace(/\s+/g, "");
  }
  if (repMeter) repMeter.style.width = `${total}%`;
  if (repExplain) {
    repExplain.textContent = raw.journal
      ? `Based on public signals for “${raw.journal}” and article context.`
      : `Based on public signals (citations, open access, recency, journal & author activity).`;
  }

  // Preferred order + labels
  const preferred = ["Citations", "Open Access", "Recency", "Journal Activity", "Author Activity"];
  const labels = [
    ...preferred.filter(k => Object.prototype.hasOwnProperty.call(comps, k)),
    ...Object.keys(comps).filter(k => !preferred.includes(k))
  ];
  const data = labels.map(k => comps[k]);

  // Breakdown rows
  if (repBreakdown) {
    repBreakdown.innerHTML = "";
    labels.forEach((k, i) => {
      const v = data[i];
      const row = document.createElement("div");
      row.className = "rowline rep-row";

      const left = document.createElement("div"); left.className = "rep-left"; left.textContent = k;
      const barOuter = document.createElement("div"); barOuter.className = "repbar";
      const barInner = document.createElement("span"); barInner.style.width = `${v}%`; barOuter.appendChild(barInner);
      const right = document.createElement("div"); right.className = "rep-val"; right.textContent = v;

      row.appendChild(left); row.appendChild(barOuter); row.appendChild(right);
      repBreakdown.appendChild(row);
    });
  }

  // SVG chart (horizontal bars with 0–100 axis)
  drawSvgChart(labels, data);
}

function drawSvgChart(labels, data) {
  if (!repChartSvgC) return;

  // Clear old
  repChartSvgC.innerHTML = "";

  // Dimensions
  const labelCol = 160;
  const rightPad = 16;
  const leftPad = 10;
  const topPad = 12;
  const bottomPad = 28;

  const barH = 22;
  const gap = 10;
  const n = Math.max(1, data.length);
  const plotH = n * barH + (n - 1) * gap;
  const width = Math.floor(repChartSvgC.clientWidth || 780);
  const height = topPad + plotH + bottomPad;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Journal reputation chart");

  // Gradient for bars
  const defs = document.createElementNS(svg.namespaceURI, "defs");
  const grad = document.createElementNS(svg.namespaceURI, "linearGradient");
  grad.setAttribute("id", "repGrad");
  grad.setAttribute("x1", "0"); grad.setAttribute("x2", "1");
  grad.setAttribute("y1", "0"); grad.setAttribute("y2", "0");
  const stops = [
    ["0%",  "#ff9f66"],
    ["60%", "#aef45a"],
    ["100%","#5ad1ff"]
  ];
  stops.forEach(([o,c]) => {
    const s = document.createElementNS(svg.namespaceURI, "stop");
    s.setAttribute("offset", o); s.setAttribute("stop-color", c); grad.appendChild(s);
  });
  defs.appendChild(grad);
  svg.appendChild(defs);

  // Axis + ticks
  const plotX = leftPad + labelCol;
  const plotW = Math.max(10, width - plotX - rightPad);
  const axisY = topPad + plotH + 4;

  const axis = document.createElementNS(svg.namespaceURI, "line");
  axis.setAttribute("x1", String(plotX));
  axis.setAttribute("y1", String(axisY));
  axis.setAttribute("x2", String(plotX + plotW));
  axis.setAttribute("y2", String(axisY));
  axis.setAttribute("stroke", "rgba(255,255,255,0.35)");
  axis.setAttribute("stroke-width", "1");
  svg.appendChild(axis);

  const ticks = [0,20,40,60,80,100];
  ticks.forEach(t => {
    const x = plotX + (t/100) * plotW;
    const line = document.createElementNS(svg.namespaceURI, "line");
    line.setAttribute("x1", String(x));
    line.setAttribute("y1", String(axisY - 4));
    line.setAttribute("x2", String(x));
    line.setAttribute("y2", String(axisY + 4));
    line.setAttribute("stroke", "rgba(255,255,255,0.35)");
    line.setAttribute("stroke-width", "1");
    svg.appendChild(line);

    const txt = document.createElementNS(svg.namespaceURI, "text");
    txt.setAttribute("x", String(x));
    txt.setAttribute("y", String(axisY + 16));
    txt.setAttribute("fill", "rgba(255,255,255,0.85)");
    txt.setAttribute("font-size", "12");
    txt.setAttribute("text-anchor", "middle");
    txt.textContent = String(t);
    svg.appendChild(txt);
  });

  // Bars + labels
  labels.forEach((label, i) => {
    const y = topPad + i * (barH + gap);
    const value = clamp01To100(data[i]);

    // Label
    const t = document.createElementNS(svg.namespaceURI, "text");
    t.setAttribute("x", String(leftPad + 2));
    t.setAttribute("y", String(y + barH - 5));
    t.setAttribute("fill", "rgba(255,255,255,0.9)");
    t.setAttribute("font-weight", "700");
    t.setAttribute("font-size", "13");
    t.textContent = (label || "").length > 26 ? (label || "").slice(0,24) + "…" : (label || "");
    svg.appendChild(t);

    // Bar background
    const bg = document.createElementNS(svg.namespaceURI, "rect");
    bg.setAttribute("x", String(plotX));
    bg.setAttribute("y", String(y));
    bg.setAttribute("width", String(plotW));
    bg.setAttribute("height", String(barH));
    bg.setAttribute("rx", "6");
    bg.setAttribute("fill", "rgba(255,255,255,0.16)");
    bg.setAttribute("stroke", "rgba(255,255,255,0.25)");
    svg.appendChild(bg);

    // Bar value
    const w = Math.max(0, (value/100) * plotW);
    const fg = document.createElementNS(svg.namespaceURI, "rect");
    fg.setAttribute("x", String(plotX));
    fg.setAttribute("y", String(y));
    fg.setAttribute("width", String(w));
    fg.setAttribute("height", String(barH));
    fg.setAttribute("rx", "6");
    fg.setAttribute("fill", "url(#repGrad)");
    svg.appendChild(fg);

    // Value text at bar end
    const val = document.createElementNS(svg.namespaceURI, "text");
    val.setAttribute("x", String(plotX + w + 6));
    val.setAttribute("y", String(y + barH - 5));
    val.setAttribute("fill", "rgba(255,255,255,0.9)");
    val.setAttribute("font-size", "12");
    val.textContent = String(value);
    svg.appendChild(val);
  });

  repChartSvgC.appendChild(svg);
}

// expose
window.renderReputation = renderReputation;
