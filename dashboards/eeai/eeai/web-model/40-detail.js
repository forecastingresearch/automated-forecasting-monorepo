// The detail dialog a headline card opens (the survey's shared forecastDialog):
// the outcome's chart, its own forecaster / scenario / year controls (starting
// from the page's), and four views -- how the outcome is computed (the
// equations and a diagram of inputs, intermediate totals and the outcome), the
// inputs themselves, every forecaster's forecast by year, and the scenarios.
//
// The inputs and the intermediate totals are in model-inputs.json beside the
// page, fetched the first time a card opens.

let inputsLoad = null, INPUTS = null;
function loadInputs() {
  if (!inputsLoad) inputsLoad = (D.inputs ? fetch(D.inputs).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    : Promise.reject(new Error("this build has no input data")))
    .then(data => { INPUTS = data; return data; }, err => ({ error: String(err.message || err) }));
  return inputsLoad;
}

const PER_NAME = { industry: "22 industries", occupation: "22 occupation groups", cell: "484 shares a year" };
const scenarioOf = id => id === "unconditional" ? UNCOND : SCEN.find(sc => sc.id === id);
const yearIndex = ds => D.years.indexOf(ds.year);
// A series' cells for the dialog's forecaster and scenario: the page's own data first, then the inputs file.
function seriesCells(id, ds) {
  const own = cellsOf(ds.system, ds.scen, id);
  if (own.length) return own;
  return (((INPUTS || {})[ds.system] || {})[ds.scen] || {})[id] || [];
}
// One cell [q05..q95] at the dialog's year; k picks an industry or occupation.
const cellAt = (id, ds, k, year = ds.year) => { const c = seriesCells(id, ds), i = D.years.indexOf(year); return (k == null ? c[i] : (c[k] || [])[i]) || []; };
const metaOf = id => SERIES[id] || D.headline.find(o => o.id === id) || { label: id, unit: "", decimals: 2 };
const symbolOf = m => m.sym ? h("span", { class: "sym" }, m.sym) : null;

function openDetail(o, opener) {
  const recipe = RECIPES[o.id] || {};
  const canUncond = system => !!(L.summaries[system] || {}).unconditional;
  const ds = { system: state.system, year: state.year, scen: !state.split && canUncond(state.system) ? "unconditional" : "moderate" };
  const views = [
    ["How it is computed", body => withInputs(body, "how", () => howView(o, recipe, ds, body))],
    ["Inputs", body => withInputs(body, "inputs", () => inputsView(recipe, ds, body))],
    ["Forecasts", body => forecastsView(o, ds, body)],
    ["Scenarios", body => scenariosView(body)],
  ];
  // The chart shows every scenario at once (and the unconditional forecast, dashed), as the survey's dialog does.
  // The scenario the controls select keeps its intervals in view; hovering another line shows that one's instead.
  const chartSeries = () => [...SCEN.map(sc => ({ id: sc.id, label: sc.label, color: sc.color, cells: cellsOf(ds.system, sc.id, o.id), band90: true })),
    ...(canUncond(ds.system) ? [{ id: "unconditional", label: "Unconditional", color: UNCOND.color, cells: cellsOf(ds.system, "unconditional", o.id), band90: true, dash: true }] : [])];
  forecastDialog.show(opener, "Economy model", o.label, views);
  const dialog = document.getElementById("question-dialog");
  const box = h("div", { class: "chart" }), ctl = h("div", { class: "controls dialog-controls" });
  const figure = h("div", { class: "dialog-chart" }, box, legendFor(), ctl);
  dialog.querySelector("#question-views").before(figure);
  let fromYear;
  function legendFor() {
    return h("div", { class: "legend" }, h("span", { style: "color: var(--ink-soft)" }, `${forecasterName(ds.system)}:`),
      ...chartSeries().map(sr => h("span", { style: `color: ${sr.color}` }, h("i", { class: "sw" + (sr.dash ? " dash" : "") }),
        h("span", { style: sr.id === ds.scen ? "color: var(--ink); font-weight: 600" : "color: var(--ink-soft)" }, sr.label))),
      h("span", {}, "Hover a line for its 50% and 90% intervals; the selected scenario's are shown."));
  }
  function draw() {
    fanChart(box, o, D.years, chartSeries(), { size: "dialog", year: ds.year, fromYear, selected: ds.scen, breakdown: breakdownFor(o.id, ds.system) });
    fromYear = undefined;
  }
  const seg = (label, options, key) => h("div", { class: "seg", role: "group", "aria-label": label }, h("span", { class: "lab" }, label),
    options.map(([value, text]) => h("button", { type: "button", "aria-pressed": String(ds[key] === value), onclick: () => {
      if (key === "year") fromYear = ds.year;
      ds[key] = value;
      if (key === "system" && ds.scen === "unconditional" && !canUncond(value)) ds.scen = "moderate";
      update();
    } }, text)));
  function controls() {
    ctl.replaceChildren(
      seg("Forecaster", [["ensemble", "Ensemble"], ...L.models.map(m => [m, m])], "system"),
      seg("Scenario", [...(canUncond(ds.system) ? [["unconditional", "Unconditional"]] : []), ...SCEN.map(sc => [sc.id, sc.label.replace(" progress", "")])], "scen"),
      seg("Year", D.years.map(y => [y, y]), "year"));
  }
  function update() {
    controls();
    figure.querySelector(".legend").replaceWith(legendFor());
    draw();
    const on = dialog.querySelector('#question-views [aria-pressed="true"]');
    if (on) on.click();
  }
  controls();
  draw();
  window.addEventListener("resize", draw);
  dialog.addEventListener("close", () => { window.removeEventListener("resize", draw); figure.remove(); }, { once: true });
}

// Run a view that needs the inputs file: at once if it is loaded, else after
// it loads (unless the reader has moved to another view meanwhile).
function withInputs(body, view, render) {
  body.dataset.view = view;
  if (INPUTS) return render();
  body.append(h("p", { class: "empty" }, "Loading the inputs…"));
  loadInputs().then(data => {
    if (body.dataset.view !== view || !body.isConnected) return;
    body.replaceChildren();
    if (data.error) body.append(h("p", { class: "warn" }, `The inputs (${D.inputs || "model-inputs.json"}) could not be loaded: ${data.error}. `
      + "Browsers do not load them from a page opened as a file; serve the site folder instead (python3 -m http.server)."));
    else render();
  });
}

const contextLine = ds => `${forecasterName(ds.system)} median · ${scenarioOf(ds.scen).label} · ${ds.year}`;

// A diagram box: the series' symbol and name, and its median when it is one number.
function node(id, ds, kind) {
  const m = metaOf(id);
  const value = m.per === "scalar" || !m.per ? fmt(m, cellAt(id, ds)[MED]) : PER_NAME[m.per];
  return h("div", { class: `node ${kind}` }, h("div", { class: "node-name" }, symbolOf(m), m.label),
    h("div", { class: "node-value mono" }, value), m.per === "scalar" && h("div", { class: "node-unit" }, m.unit));
}

function howView(o, recipe, ds, body) {
  delete body.dataset.view;
  const steps = recipe.steps || [];
  const eq = h("div", { class: "eq" });
  for (const line of recipe.eq || []) { const p = document.createElement("p"); p.innerHTML = line; eq.append(p); }
  body.append(...[
    recipe.text && h("p", { class: "lede" }, recipe.text),
    h("h3", {}, "The equations"), eq,
    recipe.note && h("p", { class: "note" }, recipe.note),
    h("h3", {}, "From forecasts to the outcome"),
    h("p", { class: "note" }, `${contextLine(ds)}. Each box is a median across simulated worlds, so the boxes need not combine exactly; the identities hold world by world.`),
    h("div", { class: "flow", role: "group", "aria-label": `How ${o.label} is computed` },
      steps.map((col, c) => h("div", { class: "flow-col" }, h("div", { class: "flow-head" }, c === 0 ? "Forecast by the panel" : "Computed"),
        col.map(id => node(id, ds, SERIES[id] && SERIES[id].input ? "input" : "computed")))),
      h("div", { class: "flow-col" }, h("div", { class: "flow-head" }, "Outcome"), node(o.id, ds, "outcome"))),
    h("div", { class: "legend" }, h("span", {}, h("i", { class: "key input" }), "A component the panel forecasts"),
      h("span", {}, h("i", { class: "key computed" }), "Computed by the model"))].filter(Boolean));
}

// A table of medians, the 50% interval on hover: rows are industries or occupations (or one per series, for national totals).
function inputsView(recipe, ds, body) {
  delete body.dataset.view;
  const i50 = (m, c) => c[MED] != null ? `50%: ${fmt(m, c[1], true)} to ${fmt(m, c[3], true)}` : null;
  const mark = id => SERIES[id] && SERIES[id].input ? h("span", { class: "key input", title: "Forecast by the panel" }) : h("span", { class: "key computed", title: "Computed by the model" });
  const parts = [h("p", { class: "note" }, `${contextLine(ds)}. Hover a value for its 50% interval. Inputs on the industry and occupation scale are indexes or rates for each group; the national values are totals.`),
    h("div", { class: "legend" }, h("span", {}, h("i", { class: "key input" }), "Forecast by the panel"), h("span", {}, h("i", { class: "key computed" }), "Computed by the model"))];
  if ((recipe.scalar || []).length) parts.push(h("h3", {}, "National"), h("div", { class: "scroll" }, h("table", { class: "tv" },
    h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "Unit"), h("th", {}, "2025"), h("th", {}, ds.year), h("th", {}, "50% interval"))),
    h("tbody", {}, recipe.scalar.map(id => { const m = metaOf(id), c = cellAt(id, ds), base = cellAt(id, ds, null, D.years[0]);
      return h("tr", {}, h("td", {}, mark(id), symbolOf(m), m.label), h("td", {}, m.unit), h("td", { class: "mono" }, fmt(m, base[MED])),
        h("td", { class: "mono" }, h("b", {}, fmt(m, c[MED]))), h("td", { class: "mono" }, c[MED] != null ? `${fmt(m, c[1], true)} to ${fmt(m, c[3], true)}` : "–"));
    })))));
  for (const [per, names, title] of [["industry", D.industries, "By industry"], ["occupation", D.occupations, "By occupation group"]]) {
    const ids = recipe[per] || [];
    if (!ids.length) continue;
    const metas = ids.map(metaOf);
    parts.push(h("h3", {}, title), h("div", { class: "scroll" }, h("table", { class: "tv" },
      h("thead", {}, h("tr", {}, h("th", {}, per === "industry" ? "Industry" : "Occupation group"),
        ids.map((id, j) => h("th", { title: metas[j].unit }, mark(id), symbolOf(metas[j]), metas[j].label, h("small", { class: "unit" }, metas[j].unit))))),
      h("tbody", {}, names.map((n, k) => h("tr", {}, h("td", {}, n.name),
        ids.map((id, j) => { const c = cellAt(id, ds, k); return h("td", { class: "mono", title: i50(metas[j], c) }, fmt(metas[j], c[MED])); })))))));
  }
  body.append(...parts);
}

// Every forecaster's median (and 50% interval) by year, for the dialog's scenario.
function forecastsView(o, ds, body) {
  delete body.dataset.view;
  const systems = ["ensemble", ...L.models];
  body.append(h("p", { class: "note" }, `${scenarioOf(ds.scen).label}. Medians across simulated worlds, the 50% interval beneath. Change the scenario above.`),
    h("div", { class: "scroll" }, h("table", { class: "tv" },
      h("thead", {}, h("tr", {}, h("th", {}, o.kind === "growth" ? "Year (growth since the date before)" : "Year"), systems.map(s => h("th", {}, forecasterName(s))))),
      h("tbody", {}, D.years.slice(1).map((y, j) => h("tr", {}, h("td", {}, y), systems.map(s => {
        const c = cellsOf(s, ds.scen, o.id)[j + 1] || [];
        return h("td", { class: "mono" }, c[MED] == null ? "–" : [h("b", {}, fmt(o, c[MED])), h("small", { class: "range" }, `${fmt(o, c[1], true)} to ${fmt(o, c[3], true)}`)]);
      })))))));
}

function scenariosView(body) {
  delete body.dataset.view;
  const P = L.probabilities || {};
  const pct = x => x == null ? "–" : Math.round(x) + "%";
  body.append(h("p", { class: "note" }, "The survey's three scenarios for AI capability at the end of 2030. Every component is forecast under each; the unconditional forecast mixes them by each forecaster's probabilities."),
    ...SCEN.flatMap(sc => [h("h3", {}, h("i", { class: "sw dot", style: `color: ${sc.color}` }), " ", sc.label),
      h("p", {}, scenarioSummary(sc.id)),
      h("p", { class: "note" }, ["ensemble", ...L.models].map(m => `${forecasterName(m)} ${pct((P[m] || {})[sc.id])}`).join(" · "))]));
}
