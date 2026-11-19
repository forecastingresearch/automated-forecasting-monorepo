// The page: header, scenario probabilities, the headline outcomes, real pay
// split into its three factors, growth by sector, employment by occupation,
// work absorbed by AI, the diagnostics, the download.
//
// Three controls, page-wide (state): split -- the unconditional forecast, or
// one line per AI-progress scenario; system -- the ensemble or one model; and
// year -- the date the numbers and tables are about. The view is kept in the
// page address (#split=1&system=ensemble&year=2030).
const D = window.__EEAI_MODEL__ || { years: [], headline: [], runs: [] };
const L = D.latest;
const state = { split: false, system: "ensemble", year: "2030" };
const said = new URLSearchParams(location.hash.slice(1));
if (said.get("split") === "1") state.split = true;
if (L && (said.get("system") === "ensemble" || L.models.includes(said.get("system")))) state.system = said.get("system");
if (D.years.includes(said.get("year")) && said.get("year") !== D.years[0]) state.year = said.get("year");
const remember = () => { try { history.replaceState(null, "", `#split=${state.split ? 1 : 0}&system=${encodeURIComponent(state.system)}&year=${state.year}`); } catch (e) {} };
const root = document.getElementById("root");
const charts = [];

function act(ev, change) {
  const k = ev.currentTarget.dataset.k, top = ev.currentTarget.getBoundingClientRect().top;
  change(); render(); remember();
  const b = [...root.querySelectorAll("[data-k]")].find(b => b.dataset.k === k);
  if (!b) return;
  window.scrollBy(0, b.getBoundingClientRect().top - top);
  b.focus({ preventScroll: true });
  b.classList.add("just");
}
function seg(where, label, options, key, untitled) {
  return h("div", { class: "seg", role: "group", "aria-label": label }, !untitled && h("span", { class: "lab" }, label),
    options.map(([value, text]) => h("button", { type: "button", "aria-pressed": String(state[key] === value),
      "data-k": `${where}|${key}|${value}`, onclick: ev => act(ev, () => { state[key] = value; }) }, text)));
}
function controls(where) {
  return h("div", { class: "controls" },
    seg(where, "Forecast shown", [[false, "Unconditional"], [true, "By AI progress scenario"]], "split", true),
    seg(where, "Forecaster", [["ensemble", "Ensemble"], ...L.models.map(m => [m, m])], "system"),
    seg(where, "Year", D.years.slice(1).map(y => [y, y]), "year"));
}

const sum = () => (L.summaries[state.system] || {});
const cells = (id, sc) => ((sum()[sc] || {})[id]) || [];
const yi = () => D.years.indexOf(state.year);
const hasUncond = () => !!sum().unconditional;
// The series one chart draws: the unconditional forecast with both bands, or the three scenarios with their 50% bands.
function seriesFor(get) {
  if (state.split || !hasUncond()) return SCEN.map(sc => ({ label: sc.label, color: sc.color, cells: get(sc.id), band90: false }));
  return [{ label: "Unconditional", color: UNCOND.color, cells: get("unconditional"), band90: true }];
}
function chartBox(o, get, size) {
  const box = h("div", { class: "chart" });
  charts.push(() => fanChart(box, o, D.years, seriesFor(get), { size, year: state.year }));
  return box;
}
function legend() {
  const items = state.split || !hasUncond()
    ? SCEN.map(sc => h("span", { style: `color: ${sc.color}` }, h("i", { class: "sw" }), h("span", { style: "color: var(--ink-soft)" }, sc.label + " (median, 50% band)")))
    : [h("span", { style: "color: var(--uncond)" }, h("i", { class: "sw" }), h("span", { style: "color: var(--ink-soft)" }, "Unconditional median")),
       h("span", {}, h("i", { class: "sw band" }), "50% and 90% intervals")];
  return h("div", { class: "legend" }, items);
}
const interval = (o, c) => c && c[MED] != null ? `${fmt(o, c[1], true)} to ${fmt(o, c[3], true)}` : "–";

function header() {
  return h("header", {},
    h("div", { class: "top" },
      h("a", { href: "https://forecastingresearch.org", title: "Forecasting Research Institute" }, h("img", { class: "brand-logo", src: "web/img/fri-logo.svg", alt: "Forecasting Research Institute", width: 231, height: 37 })),
      D.download && h("a", { class: "dl", href: D.download, download: D.download, title: "The quantiles, probabilities, rationales, simulation summaries and run file" }, "⤓ Download data")),
    h("nav", { class: "pages", "aria-label": "EEAI pages" }, h("a", { href: "index.html" }, "Survey"), h("a", { href: "model.html", "aria-current": "page" }, "Economy model")),
    h("h1", {}, "EEAI economy model (v0)"),
    h("p", { class: "lede" }, "A panel of frontier AI models forecasts the parts of an accounting model of the US economy: output, prices, productivity, hours and capital in 22 industries; jobs, unemployment and pay in 22 occupation groups. Every outcome below is computed from those parts, not asked directly, for each of three scenarios of AI progress."),
    L && h("p", { class: "meta" }, `Latest run ${L.date} · ${L.models.join(", ")} · ${L.worlds.toLocaleString("en-US")} simulated worlds per scenario and model`),
    D.synthetic && h("div", { class: "banner", role: "status" }, h("b", {}, "Placeholder data. "), "These numbers are made up to show the layout. No model has been asked yet."));
}

function probabilities() {
  const P = L.probabilities || {}, e = P[state.system];
  const pct = x => x == null ? "–" : Math.round(x) + "%";
  return h("section", { class: "card" }, h("h2", {}, "AI progress by 2030"),
    h("p", { class: "sub" }, "How likely each forecaster thinks each scenario is. The unconditional forecast mixes the scenarios by these weights."),
    e && h("div", { class: "bar", role: "img", "aria-label": SCEN.map(sc => `${sc.label} ${pct(e[sc.id])}`).join(", ") },
      SCEN.map(sc => h("div", { style: `flex: ${e[sc.id]} 0 0; background: ${sc.color}`, title: `${sc.label}: ${pct(e[sc.id])}` }))),
    h("div", { class: "scroll", style: "margin-top: 14px" }, h("table", { class: "tv" },
      h("thead", {}, h("tr", {}, h("th", {}, "Forecaster"), SCEN.map(sc => h("th", {}, sc.label)))),
      h("tbody", {}, ["ensemble", ...L.models].map(m => h("tr", {}, h("td", {}, m === "ensemble" ? h("b", {}, "Ensemble (mean)") : m),
        SCEN.map(sc => h("td", { class: "mono" }, pct((P[m] || {})[sc.id])))))))));
}

function tile(o) {
  const get = sc => cells(o.id, sc), i = yi();
  const shown = state.split || !hasUncond()
    ? h("div", { class: "num chips mono" }, SCEN.map(sc => h("span", { title: sc.label }, h("i", { class: "sw dot", style: `color: ${sc.color}` }), h("b", {}, fmt(o, (get(sc.id)[i] || [])[MED])))))
    : h("div", { class: "num mono" }, h("b", {}, fmt(o, (get("unconditional")[i] || [])[MED])), ` · 50%: ${interval(o, get("unconditional")[i])}`);
  return h("div", { class: "tile" }, h("h3", {}, o.label), h("div", { class: "unit" }, o.unit + (o.kind === "growth" && +state.year > 2030 ? `, average since ${D.years[yi() - 1]}` : "") + ` · ${state.year}`),
    shown, chartBox(o, get, "mini"));
}

function headline() {
  return h("section", { class: "card" }, h("h2", {}, "The economy"),
    h("p", { class: "sub" }, "Computed from the components in every simulated world. Growth is the annual rate: year on year to 2030, then the average annual rate since the previous date shown."),
    controls("head"), legend(), h("div", { class: "grid" }, D.headline.map(tile)),
    h("p", { class: "note" }, "Every component is drawn independently, across parts and years, so the intervals understate uncertainty: surprises that would move together cancel out instead. Year-on-year growth to 2030 divides two independent draws, so its intervals are wider still. Read the medians first."));
}

function decomposition() {
  const i = yi(), o = { unit: "index", decimals: 3 };
  const sc = state.split || !hasUncond() ? SCEN : [UNCOND];
  return h("section", { class: "card" }, h("h2", {}, "Does productivity reach pay?"),
    h("p", { class: "sub" }, "Real pay per hour relative to 2025 is exactly labor productivity × the labor share (relative to 2025) × the price gap (the prices of what the economy produces against the prices households pay). Medians in " + state.year + "; each column's product holds world by world, so the medians need not multiply exactly."),
    h("div", { class: "scroll", style: "margin-top: 12px" }, h("table", { class: "tv" },
      h("thead", {}, h("tr", {}, h("th", {}, state.year), sc.map(c => h("th", {}, c.label)))),
      h("tbody", {}, D.decomposition.map((d, k) => h("tr", {}, h("td", {}, k ? "× " + d.label : h("b", {}, d.label)),
        sc.map(c => h("td", { class: "mono" }, fmt(o, (cells(d.id, c.id)[i] || [])[MED])))))))));
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
  return h("section", { class: "card" }, h("h2", {}, "Growth by sector"),
    h("p", { class: "sub" }, `Each industry's real value added growth in ${state.year}, its contribution to GDP growth (growth × its average share of nominal GDP), and its share. Sorted by contribution${state.split ? " under moderate progress" : ""}; hover a value for its 50% interval.`),
    vectorTable("Industry", D.industries, D.sector, "sector_contribution"));
}

function occupations() {
  return h("section", { class: "card" }, h("h2", {}, "Jobs by occupation"),
    h("p", { class: "sub" }, `Employment in ${state.year} by occupation group (each industry's employment times its occupation mix), the group's unemployment rate, its pay premium over the overall median, and the human time its work takes relative to doing it without AI (below 1: AI saves time).`),
    vectorTable("Occupation group", D.occupations, D.occupation, "occupation_employment"));
}

function absorbed() {
  const o = { id: "work_absorbed", label: "Work absorbed by AI", unit: "millions of workers", decimals: 1, kind: "level" };
  return h("section", { class: "card" }, h("h2", {}, "Work absorbed by AI"),
    h("p", { class: "sub" }, "The extra workers it would take to do each year's work with 2025's AI, from the forecasters' stated shares of work done with AI help or by machines, and the time each takes. Not a count of jobs lost: cheaper work is also demanded more. These components have no official source, so this shows the forecasters' beliefs, not scoreable forecasts."),
    legend(), chartBox(o, sc => cells("work_absorbed", sc), "hero"));
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

function render() {
  charts.length = 0;
  root.style.minHeight = root.offsetHeight + "px";
  root.classList.remove("still");
  root.replaceChildren(...[
    header(),
    !L && h("section", { class: "card" }, h("h2", {}, "No forecasts yet"), h("p", { class: "empty" }, "The panel has not been asked the economy model. The components are defined; the first run will fill this page.")),
    L && probabilities(), L && headline(), L && decomposition(), L && sectors(), L && occupations(), L && absorbed(), L && diagnostics(),
    h("footer", {},
      h("p", {}, `Instrument ${D.instrument}. Scenario definitions are from FRI's Economic Effects of AI survey. Components resolve against BEA and BLS series; the automation layer has no official source.`),
      h("p", {}, "The ensemble mixes the models' simulated worlds with equal weight. Forecasts are not yet scored against outcomes."))].filter(Boolean));
  for (const draw of charts) draw();
  root.style.minHeight = "";
}
let timer;
window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(() => { root.classList.add("still"); charts.forEach(d => d()); }, 120); });
render();
