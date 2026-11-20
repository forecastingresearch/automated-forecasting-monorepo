// The page, laid out as the survey's: header, the headline forecasts, the
// other indicators, the scenario probabilities, then the model's own sections
// (real pay split into its three factors, growth by sector, employment by
// occupation, work absorbed by AI, the diagnostics).
//
// The controls are the survey's, page-wide (state): split -- the unconditional
// forecast, or one line per AI-progress scenario (the default); term -- the
// near term (each year to 2030) or the long term (to 2050); and year -- the date
// the numbers and tables are about, the term's last unless the History view
// picks another. Each chart section has its own Current / History toggle
// (historyOf). The front page shows the ensemble; a detail dialog can show one
// model. The view is kept in the page address (#split=1&term=long&year=2050).
//
// The headline outcomes are cards, as on the survey page; each opens a detail
// dialog (40-detail.js) showing how it is computed (25-recipes.js).
const D = window.__EEAI_MODEL__ || { years: [], headline: [], runs: [] };
const L = D.latest;
// The terms, as the survey's: the near term is the years asked within five years of the latest run, the long term 2030 onward.
const referenceYear = Number(((L && L.date) || new Date().toISOString()).slice(0, 4));
const future = D.years.slice(1);
const terms = {
  near: future.filter(y => +y > referenceYear && +y <= Math.max(referenceYear + 5, 2030) && +y <= 2030),
  long: future.filter(y => +y >= 2030),
};
if (!terms.near.length) terms.near = future.filter(y => +y <= 2030);
const said = new URLSearchParams(location.hash.slice(1));
const savedTerm = said.get("term") === "near" ? "near" : "long";
const state = { split: said.get("split") !== "0", system: "ensemble", term: savedTerm,
  year: terms[savedTerm].includes(said.get("year")) ? said.get("year") : terms[savedTerm].at(-1),
  // the ranked sections' measures, and whether each shows its chart or its table
  sector: said.get("sector") || "sector_growth", jobs: said.get("jobs") || "occupation_employment_change",
  sectorView: said.get("sectorView") === "table" ? "table" : "chart", jobsView: said.get("jobsView") === "table" ? "table" : "chart" };
const historyOf = new Set((said.get("history") || "").split(",").filter(a => a === "hero" || a === "grid"));
const remember = () => { try { history.replaceState(null, "", `#split=${state.split ? 1 : 0}&term=${state.term}&year=${state.year}`
  + (historyOf.size ? `&history=${[...historyOf].join(",")}` : "")
  + ["sector", "jobs", "sectorView", "jobsView"].map(k => `&${k}=${state[k]}`).join("")); } catch (e) {} };
const root = document.getElementById("root");
const charts = [];
const lastOfTerm = () => +terms[state.term].at(-1);

// A control was used: change, redraw (easing the time scale when the term
// changed, as the survey does), and keep that control where it was on screen.
function act(ev, change) {
  const k = ev.currentTarget.dataset.k, top = ev.currentTarget.getBoundingClientRect().top;
  const oldTerm = state.term;
  change();
  const zoom = state.term !== oldTerm && !reducedMotion();
  const previous = zoom ? new Map([...root.querySelectorAll(".chart[data-timeline]")].map(box => [box.dataset.timeline, box.readTimeScale()])) : null;
  render(previous); remember();
  const b = [...root.querySelectorAll("[data-k]")].find(b => b.dataset.k === k);
  if (!b) return;
  window.scrollBy(0, b.getBoundingClientRect().top - top);
  b.focus({ preventScroll: true });
  b.classList.add("just");
}
function seg(where, label, options, key, untitled) {
  return h("div", { class: "seg", role: "group", "aria-label": label }, !untitled && h("span", { class: "lab" }, label),
    options.map(([value, text]) => h("button", { type: "button", "aria-pressed": String(state[key] === value),
      "data-k": `${where}|${key}|${value}`, onclick: ev => act(ev, () => { state[key] = value; if (key === "term") state.year = terms[value].at(-1); }) }, text)));
}
function controls(where) {
  return h("div", { class: "controls" },
    seg(where, "Forecast shown", [[false, "Unconditional"], [true, "Conditional on AI progress"]], "split", true),
    seg(where, "Horizon", [["near", "Near-term"], ["long", "Long-term"]], "term"),
    historyOf.has(where) && terms[state.term].length > 1 && h("label", {}, "Forecast for ",
      h("select", { "data-k": where + "|year", onchange: ev => act(ev, () => { state.year = ev.target.value; }) },
        terms[state.term].map(y => h("option", { value: y, selected: y === state.year }, y)))),
    viewToggle(where));
}
// A chart section's own toggle, as the survey's: the current forecast over the years, or the history of one year's forecast.
function viewToggle(where) {
  const hist = historyOf.has(where);
  return h("div", { class: "mini", role: "group", "aria-label": "View" },
    [[false, "Current", "Current forecast"], [true, "History", "Forecast history"]].map(([v, text, title]) =>
      h("button", { type: "button", title, "aria-pressed": String(hist === v), "data-k": `${where}|view|${v}`,
        onclick: ev => act(ev, () => { v ? historyOf.add(where) : historyOf.delete(where); }) }, text)));
}

const sum = () => (L.summaries[state.system] || {});
const cells = (id, sc) => ((sum()[sc] || {})[id]) || [];
// Any forecaster's cells for an outcome: [[q05..q95] per year].
const cellsOf = (system, sc, id) => (((L.summaries[system] || {})[sc] || {})[id]) || [];
const yi = () => D.years.indexOf(state.year);
const hasUncond = () => !!sum().unconditional;
const forecasterName = system => system === "ensemble" ? "Ensemble" : system;
// The series one chart draws: the unconditional forecast with both bands, or the three scenarios with their 50% bands.
function seriesFor(id, system = state.system) {
  if (state.split || !hasUncond()) return SCEN.map(sc => ({ id: sc.id, label: sc.label, color: sc.color, cells: cellsOf(system, sc.id, id), band90: false }));
  return [{ id: "unconditional", label: "Unconditional", color: UNCOND.color, cells: cellsOf(system, "unconditional", id), band90: true }];
}
// The tooltip's rows: the forecaster shown, then (for the ensemble) each model.
function breakdownFor(id, system = state.system) {
  return { label: `${forecasterName(system)} median`, models: system === "ensemble" ? L.models : [],
    at: (m, sc, i) => cellsOf(m, sc, id)[i] };
}
// A chart in a section (where: "hero", "grid", or none): the current forecast
// over the term's years, or (History) the forecast for the selected year in each run.
function chartBox(o, size, where) {
  const box = h("div", { class: "chart" });
  charts.push(previous => historyOf.has(where) ? drawHistory(box, o, size)
    : fanChart(box, o, D.years, seriesFor(o.id), { size, last: lastOfTerm(), previousScale: previous && previous.get(o.id), breakdown: breakdownFor(o.id) }));
  return box;
}
// The History view's series: each run's ensemble forecast for the selected year.
function drawHistory(box, o, size) {
  const runs = D.history || [];
  const at = (run, sc) => { const k = run.years.indexOf(state.year), c = ((run.cells[sc] || {})[o.id] || [])[k]; return c && c[MED] != null ? c : null; };
  const series = seriesFor(o.id).map(sr => ({ ...sr, cells: runs.map(run => at(run, sr.id)) }));
  historyChart(box, o, runs, series, { size, target: state.year, breakdown: { label: "Ensemble median" } });
}
function legend() {
  const items = state.split || !hasUncond()
    ? SCEN.map(sc => h("span", { style: `color: ${sc.color}` }, h("i", { class: "sw" }), h("span", { style: "color: var(--ink-soft)" }, sc.label)))
    : [h("span", { style: "color: var(--uncond)" }, h("i", { class: "sw" }), h("span", { style: "color: var(--ink-soft)" }, "Unconditional (ensemble median)"))];
  items.push(state.split || !hasUncond() ? h("span", {}, "Hover a line for its 50% interval.")
    : h("span", {}, h("i", { class: "sw band" }), "50% and 90% intervals"));
  return h("div", { class: "legend" }, items);
}
const interval = (o, c) => c && c[MED] != null ? `${fmt(o, c[1], true)} to ${fmt(o, c[3], true)}` : "–";

const downloadButton = () => D.download && h("a", { class: "dl", href: D.download, download: D.download,
  title: "The quantiles, probabilities, rationales, simulation summaries and run file" }, "⤓ Download data");

function header() {
  return h("header", {},
    h("div", { class: "top" },
      h("a", { href: "https://forecastingresearch.org", title: "Forecasting Research Institute" }, h("img", { class: "brand-logo", src: "web/img/fri-logo.svg", alt: "Forecasting Research Institute", width: 231, height: 37 })),
      downloadButton()),
    h("nav", { class: "pages", "aria-label": "EEAI pages" }, h("a", { href: "index.html" }, "Survey"), h("a", { href: "model.html", "aria-current": "page" }, "Economy model")),
    h("h1", {}, "EEAI economy model (v0)"),
    h("p", { class: "lede" }, "A panel of frontier AI models forecasts the parts of an accounting model of the US economy: output, prices, productivity, hours and capital in 22 industries; jobs, unemployment and pay in 22 occupation groups. Every outcome below is computed from those parts, not asked directly, for each of three scenarios of AI progress."),
    L && h("p", { class: "meta" }, `Latest run ${L.date} · ${L.models.join(", ")} · ${L.worlds.toLocaleString("en-US")} simulated worlds per scenario and model`),
    D.synthetic && h("div", { class: "banner", role: "status" }, h("b", {}, "Placeholder data. "), "These numbers are made up to show the layout. No model has been asked yet."));
}

// The survey's dates: "Nov 20, 2026", in small type under a value or beside a caption.
const formatRunDate = date => date && new Date(date + "T00:00:00Z").toLocaleDateString("en-US",
  { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
const forecastDate = date => date && h("small", { class: "forecast-date" }, date);

const scenarioSummary = id => (D.scenarios.find(sc => sc.id === id) || {}).summary;

// The scenario probabilities, as the survey shows them: a bar for the
// forecaster selected, and a table of scenarios by forecaster. The bar's
// segments and the scenario names open a tooltip with the scenario's definition.
function probabilities() {
  const P = L.probabilities || {}, e = P[state.system];
  const pct = x => x == null ? "–" : Math.round(x) + "%";
  const tip = h("div", { id: "progress-tooltip", class: "progress-tooltip", role: "tooltip", hidden: true });
  let active;
  function hide() {
    if (active) active.removeAttribute("aria-describedby");
    active = null;
    tip.hidden = true;
  }
  function events(sc, value, source) {
    const show = ev => {
      hide();
      active = ev.currentTarget;
      tip.replaceChildren(...[h("b", {}, value == null ? sc.label : `${sc.label} · ${pct(value)}`), source && h("small", {}, source),
        h("p", {}, scenarioSummary(sc.id))].filter(Boolean));
      active.setAttribute("aria-describedby", tip.id);
      tip.hidden = false;
      const area = tip.offsetParent.getBoundingClientRect(), rect = active.getBoundingClientRect();
      const left = Math.max(8, Math.min(innerWidth - tip.offsetWidth - 8, rect.left + rect.width / 2 - tip.offsetWidth / 2));
      tip.style.left = (left - area.left) + "px";
      tip.style.top = ((rect.top > tip.offsetHeight + 12 ? rect.top - tip.offsetHeight - 6 : rect.bottom + 6) - area.top) + "px";
    };
    const leave = ev => { if (active === ev.currentTarget) hide(); };
    return { onpointerenter: show, onpointerleave: leave, onfocus: show, onblur: leave, onclick: show,
      onkeydown: ev => { if (ev.key === "Escape") hide(); } };
  }
  const label = "Model ensemble", date = formatRunDate(L.date);
  return h("section", { class: "card ai-progress" }, h("h2", {}, "AI progress by 2030"),
    h("p", { class: "sub" }, "How likely each forecaster thinks each scenario is. The unconditional forecast mixes the scenarios by these weights."),
    e && h("div", { class: "scenario-bars" }, h("figure", {}, h("figcaption", {}, h("b", {}, label), forecastDate(date)),
      h("div", { class: "bar", role: "group", "aria-label": `${label}. ` + SCEN.map(sc => `${sc.label} ${pct(e[sc.id])}`).join(", ") },
        SCEN.map(sc => h("button", { type: "button", "aria-label": `${sc.label} ${pct(e[sc.id])}`,
          style: `flex: ${e[sc.id]} 0 0; background: ${sc.color}`, ...events(sc, e[sc.id], label) }))))),
    h("div", { class: "scroll", style: "margin-top: 14px" }, h("table", { class: "tv" },
      h("thead", {}, h("tr", {}, h("th", {}, "Probability"), h("th", {}, "Model panel"), L.models.map(m => h("th", {}, m)))),
      h("tbody", {}, SCEN.map(sc => h("tr", {},
        h("th", { scope: "row" }, h("button", { type: "button", class: "scenario-label", ...events(sc) }, sc.label)),
        ["ensemble", ...L.models].map(m => h("td", { class: "mono" }, pct((P[m] || {})[sc.id]), forecastDate(date)))))))),
    tip);
}

// The unit line under a card's title: the unit, the window a growth rate covers, the year.
const forecastTitle = text => h("button", { type: "button", class: "forecast-trigger" }, text);

// A card opens its detail dialog (the survey's shared forecastDialog) from its title or anywhere on it.
function forecastCard(o, card) {
  return forecastDialog.bind(card, card.querySelector(".forecast-trigger"), opener => openDetail(o, opener));
}

// The survey's tile: a category, the title, the values, and what they measure ("per year, 2045–2050", "of the labor force in 2050").
const CATEGORY = { gdp_growth: "Economic Activity", lp_growth: "Economic Activity", tfp_growth: "Economic Activity",
  unemployment_rate: "Labor Markets", lfpr: "Labor Markets", epop: "Labor Markets", employment: "Labor Markets",
  labor_share: "Economic Inequality", ratio_90_10: "Economic Inequality",
  real_pay_growth: "Income and Well-Being", real_median_earnings: "Income and Well-Being", inflation_pce: "Prices" };
const unitWord = o => o.unit === "% per year" ? "per year" : o.unit.startsWith("%") ? o.unit.slice(1).trim() : o.unit;
// The window a value covers: a growth rate runs from the date before; a level is the year's average.
const period = o => o.kind === "growth" ? `${D.years[yi() - 1]}–${state.year}` : state.year;
const valueLine = o => o.kind === "growth" ? `${unitWord(o)}, ${period(o)}` : [unitWord(o), `in ${state.year}`].filter(Boolean).join(" ");

function tile(o) {
  const get = sc => cells(o.id, sc), i = yi();
  const shown = state.split || !hasUncond()
    ? h("div", { class: "num chips mono" }, SCEN.map(sc => h("span", { title: sc.label }, h("i", { class: "sw dot", style: `color: ${sc.color}` }), h("b", {}, fmt(o, (get(sc.id)[i] || [])[MED])))),
        h("span", {}, valueLine(o)))
    : h("div", { class: "num mono" }, h("b", {}, fmt(o, (get("unconditional")[i] || [])[MED])), ` ${valueLine(o)} · 50%: ${interval(o, get("unconditional")[i])}`);
  return forecastCard(o, h("article", { class: "tile forecast-card" }, h("div", { class: "cat" }, CATEGORY[o.id]), h("h3", {}, forecastTitle(o.label)),
    shown, chartBox(o, "mini", "grid")));
}

// A headline card, as the survey's: a measure line, the forecaster's median in
// large type (not repeated per scenario when the chart is split), and a larger chart.
function headlineCard(o) {
  const v = (cells(o.id, "unconditional")[yi()] || [])[MED];
  return forecastCard(o, h("article", { class: "tile headline forecast-card" }, h("h3", {}, forecastTitle(o.label)),
    h("p", { class: "sub" }, MEASURES[o.id]),
    !state.split && hasUncond() && h("div", { class: "headline-values" },
      h("small", {}, "Model panel median"), h("b", { class: "mono" }, fmt(o, v))),
    h("small", {}, o.kind === "growth" ? period(o) : `Annual average, ${state.year}`),
    chartBox(o, "headline", "hero")));
}

// The two chart sections, as the survey's: the headline forecasts, then the other indicators, each with its own controls.
function headline() {
  const lead = D.headline.filter(o => o.id in MEASURES);
  return h("section", { class: "card" }, h("h2", {}, "Headline forecasts"),
    h("p", { class: "sub" }, "Computed from the components in every simulated world, not asked directly. Open a card to see the forecasts it is computed from, and how."
      + (historyOf.has("hero") ? ` Each chart tracks the forecast for ${state.year} across runs.` : "")),
    controls("hero"), legend(), h("div", { class: "headline-grid" }, lead.map(headlineCard)));
}
function others() {
  const rest = D.headline.filter(o => !(o.id in MEASURES));
  return h("section", { class: "card" }, h("h2", {}, "The other indicators"),
    h("p", { class: "sub" }, "Each indicator has its own scale. Growth is the annual rate: year on year to 2030, then the average annual rate since the previous date shown."
      + (historyOf.has("grid") ? ` Each chart tracks the forecast for ${state.year} across runs.` : "")),
    controls("grid"), legend(), h("div", { class: "grid" }, rest.map(tile)),
    h("p", { class: "note" }, "Every component is drawn independently, across components and across years: the panel has not yet been asked how they move together. ",
      "For levels this understates uncertainty, since surprises that would move together cancel out instead. ",
      "For growth rates it can overstate it: a year-on-year rate divides two unrelated draws, so the intervals to 2030 are too wide, and they narrow abruptly at 2035. ",
      "These intervals will change once the panel is asked how each component's values in different years depend on each other. ",
      "Some of the narrowing after 2030 is real, though: from 2035 a growth rate is the average over five years, and an average is less uncertain than any single year's rate. ",
      "Compare an interval with others over the same window. Read the medians first."));
}

// The ranked charts' measures: a short name for the toggle and what the axis shows.
// The hollow ring (2025) appears where the measure has a 2025 value.
const RANKED = {
  sector: { names: () => D.industries, metas: () => D.sector, kind: "Industry", options: [
    ["sector_growth", "Growth", "Real value added growth, % per year"],
    ["sector_contribution", "Contribution to GDP", "Contribution to real GDP growth, percentage points: the industry's growth times its average share of nominal GDP"],
    ["sector_share", "Share of GDP", "Share of nominal GDP, %"]] },
  jobs: { names: () => D.occupations, metas: () => D.occupation, kind: "Occupation group", options: [
    ["occupation_employment_change", "Employment change", "Change in employment since 2025, % (each industry's employment times its occupation mix)"],
    ["occupation_unemployment", "Unemployment", "Unemployment rate, %"],
    ["occupation_time", "Human time with AI", "Human time a unit of the group's work takes, relative to doing it without AI (below 1: AI saves time)"],
    ["occupation_premium", "Pay premium", "Median earnings relative to the overall median"]] },
};
// A ranked section: the measure and Chart / Table toggles, a legend, then the chart or the full table.
function ranked(where, title, sub) {
  const R = RANKED[where];
  if (!R.options.some(o => o[0] === state[where])) state[where] = R.options[0][0];      // (an unknown measure in the address)
  const metric = state[where], option = R.options.find(o => o[0] === metric);
  const m = { ...R.metas().find(x => x.id === metric), kind: "level" };
  const sc = state.split || !hasUncond() ? SCEN : [UNCOND];
  const key = sc.length > 1 ? "moderate" : "unconditional", i = yi();
  const get = (id, k) => (cells(metric, id)[k] || [])[i];
  const base = k => metric.endsWith("_change") ? null : ((cells(metric, key)[k] || [])[0] || [])[MED] ?? null;
  const table = state[where + "View"] === "table";
  const box = h("div", { class: "rank" });
  if (!table) charts.push(() => rankChart(box, m, R.names(), sc.map(c => ({ id: c.id, label: c.label, color: c.color })), get, base, key, state.year));
  const toggle = (k, opts) => h("div", { class: k === where ? "mini measure" : "mini", role: "group", "aria-label": k === where ? "Measure" : "View" }, opts.map(([v, text]) =>
    h("button", { type: "button", "aria-pressed": String(state[k] === v), "data-k": `${where}|${k}|${v}`, onclick: ev => act(ev, () => { state[k] = v; }) }, text)));
  return h("section", { class: "card" }, h("h2", {}, title), h("p", { class: "sub" }, sub),
    h("div", { class: "controls" }, toggle(where, R.options.map(o => [o[0], o[1]])), toggle(where + "View", [["chart", "Chart"], ["table", "Table"]])),
    table ? vectorTable(R.kind, R.names(), R.metas(), metric)
      : [h("div", { class: "legend" }, ...(sc.length > 1 ? SCEN.map(c => h("span", {}, h("i", { class: "sw dot", style: `color: ${c.color}` }), c.label))
          : [h("span", {}, h("i", { class: "sw dot", style: `color: ${UNCOND.color}` }), "Unconditional (ensemble median)"), h("span", {}, h("i", { class: "sw band" }), "50% interval")]),
          metric.endsWith("_change") ? null : h("span", {}, h("i", { class: "sw ring" }), "2025"),
          h("span", {}, "Hover a row for its numbers.")),
        h("p", { class: "note" }, `${option[2]}, ${state.year}${m.unit === "% per year" && +state.year > 2030 ? ` (average since ${D.years[yi() - 1]})` : ""}. Sorted by the ${sc.length > 1 ? "moderate-progress" : "unconditional"} median.`),
        box]);
}

function vectorTable(kind, names, metas, sortBy) {
  const i = yi(), sc = state.split || !hasUncond() ? SCEN : [UNCOND];
  const at = (id, c, k) => (((sum()[c] || {})[id] || [])[k] || [])[i];
  const first = metas[0], rows = names.map((n, k) => ({ n, k })), key = sc[sc.length > 1 ? 1 : 0].id;
  if (sortBy) rows.sort((a, b) => ((at(sortBy, key, b.k) || [])[MED] ?? -1e9) - ((at(sortBy, key, a.k) || [])[MED] ?? -1e9));
  // The bar is the column the table is sorted by.
  const barId = sortBy || first.id;
  const max = Math.max(...rows.map(r => Math.abs((at(barId, key, r.k) || [])[MED] || 0)), 1e-9);
  return h("div", { class: "scroll", style: "margin-top: 12px" }, h("table", { class: "tv" },
    h("thead", {}, h("tr", {}, h("th", {}, kind), metas.flatMap(m => sc.map(c => h("th", {}, sc.length > 1 ? `${m.label} · ${c.label.replace(" progress", "")}` : m.label))), h("th", {}, ""))),
    h("tbody", {}, rows.map(({ n, k }) => {
      const lead = (at(barId, key, k) || [])[MED];
      return h("tr", {}, h("td", {}, n.name),
        metas.flatMap(m => sc.map(c => { const v = at(m.id, c.id, k) || [];
          return h("td", { class: "mono", title: sc.length === 1 ? `50%: ${interval(m, v)}` : null }, fmt(m, v[MED])); })),
        h("td", { class: "bar" }, lead != null && h("span", { class: "hbar" + (lead < 0 ? " neg" : ""), style: `width: ${Math.abs(lead) / max * 100}%` })));
    }))));
}

function sectors() {
  return ranked("sector", "Growth by sector", "Which of the 22 industries grow, and how much each adds to GDP growth. "
    + (state.split || !hasUncond() ? "The longer a row's line, the more that industry's future depends on how fast AI improves." : "Switch to Conditional on AI progress to see how much each industry depends on the scenario."));
}

function occupations() {
  return ranked("jobs", "Jobs by occupation", "How employment, unemployment, the human time work takes and pay shift across the 22 occupation groups. "
    + (state.split || !hasUncond() ? "The longer a row's line, the more that group depends on how fast AI improves." : "Switch to Conditional on AI progress to see how much each group depends on the scenario."));
}

function absorbed() {
  const o = { id: "work_absorbed", label: "Work absorbed by AI", unit: "millions of workers", decimals: 1, kind: "level" };
  return h("section", { class: "card" }, h("h2", {}, "Work absorbed by AI"),
    h("p", { class: "sub" }, "The extra workers it would take to do each year's work with 2025's AI, from the forecasters' stated shares of work done with AI help or by machines, and the time each takes. Not a count of jobs lost: cheaper work is also demanded more. These components have no official source, so this shows the forecasters' beliefs, not scoreable forecasts."),
    legend(), chartBox(o, "hero"));
}

function diagnostics() {
  const sys = state.system === "ensemble" ? L.models : [state.system];
  const scen = state.split ? SCEN : [SCEN[1]];
  const i = D.years.indexOf(state.year) - 1;
  const names = { nominal_gdp: ["Nominal GDP, US$ billions", 0], employment: ["Employment, millions", 2], unemployment_rate: ["Unemployment rate, %", 2], lfpr: ["Participation rate, %", 2] };
  const checks = { gdp_growth: "Real GDP growth", unemployment_rate: "Unemployment rate", lfpr: "Participation rate", lp_growth: "Productivity growth", tfp_growth: "TFP growth" };
  const n = (v, d) => v == null ? "–" : (+v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
  return h("section", { class: "card" }, h("h2", {}, "Checks"),
    h("p", { class: "sub" }, "Whether each forecaster's parts fit together. The 2025 identities applied to its baselines should reproduce the official 2025 totals; the computed outcomes are set beside its direct forecasts of the same things (a gap is a diagnostic, not a reason to prefer either)."),
    Object.keys(L.skipped || {}).length > 0 && h("p", { class: "warn" }, "Not simulated: " + Object.entries(L.skipped).map(([m, why]) => `${m} (${why})`).join("; ")),
    h("div", { class: "split2" }, sys.map(m => { const d = L.diagnostics[m] || {};
      return h("div", {}, h("h3", { style: "margin-top: 14px" }, m),
        h("div", { class: "scroll" }, h("table", { class: "tv" },
          h("thead", {}, h("tr", {}, h("th", {}, "2025"), h("th", {}, "Computed"), h("th", {}, "Official"), h("th", {}, "Gap"))),
          h("tbody", {}, Object.entries(d.baseline_check || {}).map(([k, v]) => h("tr", {}, h("td", {}, names[k][0]),
            h("td", { class: "mono" }, n(v.computed, names[k][1])), h("td", { class: "mono" }, n(v.official, names[k][1])), h("td", { class: "mono" }, n(v.diff, names[k][1]))))))),
        h("div", { class: "scroll" }, h("table", { class: "tv" },
          h("thead", {}, h("tr", {}, h("th", {}, `${state.year}, median`), scen.flatMap(sc => [h("th", {}, `Computed · ${sc.label.replace(" progress", "")}`), h("th", {}, "Direct")]))),
          h("tbody", {}, Object.entries(checks).map(([k, label]) => h("tr", {}, h("td", {}, label),
            scen.flatMap(sc => { const c = ((d.cross_checks || {})[sc.id] || {})[k] || {};
              return [h("td", { class: "mono" }, n((c.computed || [])[i], 2)), h("td", { class: "mono" }, n((c.direct || [])[i], 2))]; })))))),
        h("p", { class: "note" }, `Occupation shares summed to ${SCEN.map(sc => n((d.share_sum || {})[sc.id], 3)).join(" / ")} before rescaling (slow / moderate / rapid); `
          + `the metalog fallback was used for ${SCEN.map(sc => n(((d.fallback_rate || {})[sc.id] || 0) * 100, 1) + "%").join(" / ")} of the quantile sets; `
          + `automation shares were rescaled in ${SCEN.map(sc => n(((d.automation_rescaled || {})[sc.id] || 0) * 100, 1) + "%").join(" / ")} of draws; `
          + `${d.problems || 0} component(s) had answers left out by the cleaning.`));
    })));
}

function render(previous) {
  charts.length = 0;
  root.style.minHeight = root.offsetHeight + "px";
  root.classList.remove("still");
  root.replaceChildren(...[
    header(),
    !L && h("section", { class: "card" }, h("h2", {}, "No forecasts yet"), h("p", { class: "empty" }, "The panel has not been asked the economy model. The components are defined; the first run will fill this page.")),
    L && headline(), L && others(), L && probabilities(), L && sectors(), L && occupations(), L && absorbed(), L && diagnostics(),
    // The survey's download card.
    D.download && h("section", { class: "card" }, h("div", { class: "head" },
      h("div", {}, h("h2", {}, "Download data"),
        h("p", { class: "sub", style: "color: var(--ink-soft); margin: 4px 0 0; max-width: 640px" }, "Every quantile every model gave for every component, the scenario probabilities, the rationales, the simulation summaries and the run file.")),
      downloadButton())),
    h("footer", {}, `Instrument ${D.instrument}. Scenario definitions are from FRI's Economic Effects of AI survey. Components resolve against BEA and BLS series; the automation layer has no official source. `,
      "The ensemble mixes the models' simulated worlds with equal weight. Forecasts are not yet scored against outcomes.")].filter(Boolean));
  for (const draw of charts) draw(previous);
  root.style.minHeight = "";
}
let timer;
window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(() => { root.classList.add("still"); charts.forEach(d => d()); }, 120); });
render();
