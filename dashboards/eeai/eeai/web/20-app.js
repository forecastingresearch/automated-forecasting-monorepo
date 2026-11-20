// The page: window.__EEAI__ (eeai/build.py) -> the header, the GDP panel, the
// other indicators, the AI progress answers, the download. Plain DOM.
//
const D = window.__EEAI__ || { questions: [], runs: [], scenarios: [] };
const referenceYear = Number((D.latest?.date || D.human_extracted_on || new Date().toISOString()).slice(0, 4));
const dates = [...new Set(D.questions.flatMap(q => q.horizons.map(z => z.id)))].sort();
const terms = {
  near: dates.filter(year => +year > referenceYear && +year <= referenceYear + 5),
  long: dates.filter(year => year === "2030" || year === "2050"),
};
const said = new URLSearchParams(location.hash.slice(1));
const savedYear = said.get("horizon");
const savedTerm = said.get("term");
const term = savedTerm === "near" || savedTerm === "long" ? savedTerm
  : terms.near.includes(savedYear) && savedYear !== "2050" ? "near" : "long";
const state = { split: said.get("split") !== "0", term, horizon: terms[term].includes(savedYear) ? savedYear : terms[term].at(-1) };
const historyOf = new Set((said.get("history") || "").split(",").filter(a => a === "hero" || a === "grid"));
const remember = () => { try { history.replaceState(null, "", `#split=${state.split ? 1 : 0}&term=${state.term}`
  + (state.horizon ? `&horizon=${state.horizon}` : "")
  + (historyOf.size ? `&history=${[...historyOf].join(",")}` : "")); } catch (e) {} };
const root = document.getElementById("root");
const charts = [];

// A control was used: change, redraw, and keep that control where it was on
// the screen (the page above it may have changed height) and focused.
function act(ev, change) {
  const k = ev.currentTarget.dataset.k, top = ev.currentTarget.getBoundingClientRect().top;
  const oldTerm = state.term;
  change();
  const zoom = state.term !== oldTerm && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  const previous = zoom ? new Map([...root.querySelectorAll(".chart[data-timeline]")].map(box =>
    [box.dataset.timeline, box.readTimeScale()])) : null;
  render(previous); remember();
  const b = [...root.querySelectorAll("[data-k]")].find(b => b.dataset.k === k);
  if (!b) return;
  window.scrollBy(0, b.getBoundingClientRect().top - top);
  b.focus({ preventScroll: true });
  b.classList.add("just");        // the one control that changed gets a small press animation
}
function seg(where, label, options, key, untitled) {
  return h("div", { class: "seg", role: "group", "aria-label": label }, !untitled && h("span", { class: "lab" }, label),
    options.map(([value, text]) => h("button", { type: "button", "aria-pressed": String(state[key] === value),
      "data-k": `${where}|${key}|${value}`, onclick: ev => act(ev, () => { state[key] = value; if (key === "term") state.horizon = terms[value].at(-1); }) }, text)));
}
function controls(where) {
  return h("div", { class: "controls" },
    seg(where, "Forecast shown", [[false, "Unconditional"], [true, "Conditional on AI progress"]], "split", true),
    seg(where, "Horizon", [["near", "Near-term"], ["long", "Long-term"]], "term"),
    historyOf.has(where) && terms[state.term].length > 1 && h("label", {}, "Forecast for ",
      h("select", { "data-k": where + "|year", onchange: ev => act(ev, () => { state.horizon = ev.target.value; }) },
        terms[state.term].map(year => h("option", { value: year, selected: year === state.horizon }, year)))),
    viewToggle(where));
}
// A chart area's own little toggle: the current forecast on the timeline, or that forecast's history.
function viewToggle(where) {
  const hist = historyOf.has(where);
  return h("div", { class: "mini", role: "group", "aria-label": "View" },
    [[false, "Current", "Current forecast"], [true, "History", "Forecast history"]].map(([v, text, title]) =>
      h("button", { type: "button", title, "aria-pressed": String(hist === v), "data-k": `${where}|view|${v}`,
        onclick: ev => act(ev, () => { v ? historyOf.add(where) : historyOf.delete(where); }) }, text)));
}
function chartOptions(q, size) {
  const headline = q.id in headlineMeasures;
  return { ...state, size, headline, years: terms[state.term], referenceYear, target: horizonOf(q),
    view: historyOf.has(headline ? "hero" : "grid") ? "history" : "now", order: D.latest?.models || [] };
}
function chartBox(q, size) {
  const box = h("div", { class: "chart" });
  charts.push(previous => drawChart(box, q, { ...chartOptions(q, size), previousScale: previous?.get(q.id) }));
  return box;
}
function horizonOf(q) {
  const visible = q.horizons.filter(z => terms[state.term].includes(z.id));
  return visible.find(z => z.id === state.horizon)?.id || visible.at(-1)?.id;
}
const unitWord = q => q.unit === "% per year" ? "per year" : q.unit.startsWith("%") ? q.unit.slice(1).trim() : q.unit;

function legend(range, history, questions) {
  const items = history ? [] : [h("span", { style: "color: var(--ink)" }, h("i", { class: "sw" }), h("span", {}, "Actual"))];
  if (state.split) {
    for (const sc of SCEN) items.push(h("span", { style: `color: ${sc.color}` }, h("i", { class: "sw" }), h("span", { style: "color: var(--ink-soft)" }, sc.label)));
    if (range) items.push(h("span", {}, "Hover a line for its 80% range, where available."));
  } else {
    items.push(h("span", { style: "color: var(--uncond)" }, h("i", { class: "sw dash" }), h("span", { style: "color: var(--ink-soft)" }, "Unconditional (panel median)")));
    if (range) items.push(h("span", {}, h("i", { class: "sw band" }), range));
  }
  if (history) {
    if (D.questions.some(q => q.horizons.some(z => z.id === horizonOf(q) && z.actual))) items.push(h("span", { style: "color: var(--ink)" }, h("i", { class: "sw" }), h("span", {}, "Outcome")));
  } else if (D.questions.some(q => q.horizons.some(z => z.actual && z.asked))) items.push(h("span", {}, h("i", { class: "sw ring" }), "Forecast for a date whose outcome is in"));
  const series = state.split ? SCEN : [UNCOND];
  for (const panel of HUMAN_PANELS) {
    const available = questions.some(q => q.horizons.some(z => (history ? z.id === horizonOf(q) : terms[state.term].includes(z.id))
      && series.some(sc => humanCell(q.id, z.id, sc.id, panel.id))));
    if (available) items.push(h("span", { class: "legend-" + panel.id }, h("i", { class: "survey-dot " + panel.id }), panel.label));
  }
  return h("div", { class: "legend" }, items);
}

function modelTable(q, hz) {
  const cell = (forecasts, sc) => {
    const c = forecasts[hz]?.[sc] || {};
    return c.p50 == null ? "–" : fmt(q, c.p50) + (c.p10 != null && c.p90 != null ? ` (${fmt(q, c.p10, true)} to ${fmt(q, c.p90, true)})` : "");
  };
  const ens = sc => { const p10 = val(q, hz, sc, "p10"), p90 = val(q, hz, sc, "p90");
    return fmt(q, val(q, hz, sc)) + (p10 != null && p90 != null ? ` (${fmt(q, p10, true)} to ${fmt(q, p90, true)})` : ""); };
  const cols = ["unconditional", "slow", "moderate", "rapid"];
  const modelRows = Object.entries(runFor(q, hz).models || {}).filter(([, forecasts]) =>
    cols.some(sc => forecasts[hz]?.[sc]?.p50 != null));
  const panels = HUMAN_PANELS.filter(panel => cols.some(sc => humanCell(q.id, hz, sc, panel.id)));
  const hasMedian = cols.some(sc => val(q, hz, sc) != null);
  if (!hasMedian && !modelRows.length && !panels.length) return null;
  const group = (title, date) => h("tr", { class: "source-group" },
    h("th", { colspan: 5, scope: "rowgroup" }, title, forecastDate(date)));
  return h("div", { class: "scroll" }, h("table", { class: "tv" },
    h("thead", {}, h("tr", {}, h("th", {}, `${hz}`), h("th", {}, "Unconditional"), h("th", {}, "Slow"), h("th", {}, "Moderate"), h("th", {}, "Rapid"))),
    (hasMedian || modelRows.length > 0) && h("tbody", {}, group("Model forecasts", formatRunDate(runFor(q, hz).date)),
      hasMedian && h("tr", {}, h("td", {}, h("b", {}, "Model panel median")), cols.map(c => h("td", { class: "mono" }, ens(c)))),
      modelRows.map(([label, forecasts]) => h("tr", {}, h("td", {}, label), cols.map(c => h("td", { class: "mono" }, cell(forecasts, c)))))),
    panels.length > 0 && h("tbody", {}, group("Human forecasts", humanSurveyDate),
      panels.map(panel =>
        h("tr", {}, h("th", { scope: "row" }, panel.label), cols.map(sc => {
          const at = stat => humanCell(q.id, hz, sc, panel.id, stat);
          const median = at("p50");
          if (!median) return h("td", {}, "–");
          const lo = at("p10"), hi = at("p90");
          return h("td", { class: "mono" }, withRange(q, Number(median.value), lo && Number(lo.value), hi && Number(hi.value))
            + " (n=" + median.respondents + ")");
        }))))));
}
function rationales(q) {
  if (!q.models.length) return [h("p", {}, "No model rationales recorded yet.")];
  return q.models.map((m, index) => h("details", { class: "model-rationale", open: index === 0 },
    h("summary", {}, m.label), h("p", {}, m.rationale || "No rationale given.")));
}
// Each date whose outcome is in: the outcome, and every forecast with its miss.
function outcomes(q) {
  const cols = [UNCOND].concat(SCEN), rows = q.horizons.filter(z => z.actual);
  if (!rows.length) return null;
  const cell = (z, c, outcome, latest) => {
    const v = val(q, z.id, c.id);
    if (v == null) return "–";
    return scoreable(c.id, latest) ? `${fmt(q, v)} (${missText(q, v - outcome.value)})` : fmt(q, v);
  };
  const tableRows = rows.flatMap(z => {
    const history = z.actual.revisions || [z.actual];
    const views = [["First published", history[0]]];
    if (history.length > 1 || (D.latest_realized_scenario && D.latest_realized_scenario !== D.realized_scenario)) views.push(["Latest revised", history[history.length - 1]]);
    return views.map(([label, outcome], index) => h("tr", {},
      h("td", {}, z.id), h("td", {}, outcome.vintage ? label + " · " + outcome.vintage : "First observed"),
      h("td", { class: "mono" }, fmt(q, outcome.value)),
      cols.map(c => h("td", { class: "mono" }, cell(z, c, outcome, index === 1)))));
  });
  return h("div", { class: "scroll" }, h("table", { class: "tv" },
    h("thead", {}, h("tr", {}, h("th", {}, "Target"), h("th", {}, "Release"), h("th", {}, "Outcome"),
      cols.map(c => h("th", {}, c.label.replace(" progress", ""))))),
    h("tbody", {}, tableRows)));
}
const defined = q => [
  q.preamble && h("p", {}, q.preamble),
  h("p", {}, q.stem + (q.horizons[0].text ? "\n" + q.horizons.map(z => "• " + z.text).join("\n") : "")),
  h("p", {}, q.details), q.resolution_text && h("p", {}, q.resolution_text)];
function forecastCard(q, card) {
  const trigger = card.querySelector(".forecast-trigger");
  return forecastDialog.bind(card, trigger, opener => {
    const views = [
      ["Forecasts", body => {
        const tables = q.horizons.map(z => modelTable(q, z.id)).filter(Boolean);
        body.append(...(tables.length ? tables : ["No forecasts recorded yet."]));
      }],
      ["Definition", body => body.append(...defined(q).filter(Boolean))],
      ["Rationales", body => body.append(...rationales(q))]
    ];
    if (q.id in headlineMeasures) views.push(["Scenarios", body => {
      for (const sc of D.scenarios.filter(sc => sc.summary)) body.append(h("h3", {}, sc.label), h("p", {}, sc.summary));
    }]);
    const observed = outcomes(q);
    if (observed) views.push(["Outcomes", body => body.append(observed)]);
    forecastDialog.show(opener, q.category, q.short, views);
    const dialog = document.getElementById("question-dialog");
    const options = chartOptions(q, "hero");
    const box = h("div", { class: "chart" });
    const figure = h("div", { class: "dialog-chart" }, box,
      legend(q.uncertainty && "80% range", options.view === "history", [q]));
    dialog.querySelector("#question-views").before(figure);
    const draw = () => drawChart(box, q, options);
    draw();
    window.addEventListener("resize", draw);
    dialog.addEventListener("close", () => {
      window.removeEventListener("resize", draw);
      figure.remove();
    }, { once: true });
  });
}

function forecastTitle(text) {
  return h("button", { type: "button", class: "forecast-trigger" }, text);
}

const headlineMeasures = {
  gdp: ["Real GDP growth", "Annualized over the preceding five years"],
  lfpr: ["Labor force participation", "Share of U.S. civilian noninstitutional residents aged 16+ in the labor force"],
  wealth_inequality: ["Wealth inequality", "Share of U.S. wealth held by the top 10%"],
};

function headlines(questions) {
  return h("section", { class: "card" }, h("h2", {}, "Headline forecasts"),
    controls("hero"), legend("80% range, where available", historyOf.has("hero"), questions),
    h("div", { class: "headline-grid" }, questions.map(q => {
      const [title, measure] = headlineMeasures[q.id], hz = horizonOf(q);
      return forecastCard(q, h("article", { class: "tile headline forecast-card" }, h("h3", {}, forecastTitle(title)), h("p", { class: "sub" }, measure),
        hz && !state.split && h("div", { class: "headline-values" },
          h("small", {}, "Model panel median"), h("b", { class: "mono" }, fmt(q, val(q, hz, "unconditional")))),
        hz && h("small", {}, q.id === "gdp" ? `${hz - 5}–${hz}` : `Beginning of ${hz}`),
        chartBox(q, "headline")));
    })));
}

function tile(q) {
  const hz = horizonOf(q), v = val(q, hz, "unconditional"), p10 = val(q, hz, "unconditional", "p10"), p90 = val(q, hz, "unconditional", "p90");
  return forecastCard(q, h("article", { class: "tile forecast-card" },
    h("div", { class: "cat" }, q.category), h("h3", {}, forecastTitle(q.short)),
    hz && (state.split
      ? h("div", { class: "num chips mono" }, SCEN.map(sc => h("span", { title: sc.label }, h("i", { class: "sw dot", style: `color: ${sc.color}` }), h("b", {}, fmt(q, val(q, hz, sc.id))))), h("span", {}, `${unitWord(q)} in ${hz}`))
      : h("div", { class: "num mono" }, h("b", {}, fmt(q, v)), ` ${unitWord(q)} in ${hz}`, p10 != null && ` · 80%: ${fmt(q, p10, true)} to ${fmt(q, p90, true)}`)),
    chartBox(q, "mini")));
}

function progress() {
  const p = D.part1 || {}, models = D.latest?.models || [];
  const sp = p.scenario_probabilities, e = sp?.ensemble;
  const human = HUMAN_PANELS.filter(panel => D.human?.some(row => row.question === "scenario_probabilities" && row.cohort === panel.id));
  const modelDate = formatRunDate(D.latest?.date);
  const tip = h("div", { id: "progress-tooltip", class: "progress-tooltip", role: "tooltip", hidden: true });
  let active;
  function hide() {
    active?.removeAttribute("aria-describedby");
    active = null;
    tip.hidden = true;
  }
  function events(sc, value, source) {
    const show = ev => {
      hide();
      active = ev.currentTarget;
      tip.replaceChildren(h("b", {}, value == null ? sc.label : sc.label + " · " + value + "%"));
      if (source) tip.append(h("small", {}, source));
      else tip.append(h("p", {}, D.scenarios.find(item => item.id === sc.id)?.summary));
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
  const probability = (value, date, count) => h("td", { class: "mono" },
    value == null ? "–" : [value + "%",
      forecastDate(date), count && h("small", { class: "sample-size" }, "n=" + count)]);
  const modelProb = value => probability(value == null ? null : Math.round(value), modelDate);
  const humanProb = sc => human.map(panel => {
    const row = humanCell("scenario_probabilities", "2030", "unconditional", panel.id, "probability", sc.id);
    return probability(row?.value, humanSurveyDate, row?.respondents);
  });
  const fullPanel = Object.fromEntries(SCEN.map(sc => [sc.id,
    humanCell("scenario_probabilities", "2030", "unconditional", "full_panel", "probability", sc.id)?.value]));
  function scenarioBar(label, values, date) {
    if (!SCEN.every(sc => values?.[sc.id] != null)) return null;
    const describe = sc => sc.label + " " + values[sc.id] + "%";
    return h("figure", {}, h("figcaption", {}, h("b", {}, label), forecastDate(date)),
      h("div", { class: "bar", role: "group", "aria-label": label + ". " + SCEN.map(describe).join(", ") },
        SCEN.map(sc => h("button", { type: "button", "aria-label": describe(sc), style: `flex: ${values[sc.id]} 0 0; background: ${sc.color}`, ...events(sc, values[sc.id], label) }))));
  }
  return h("section", { class: "card ai-progress" }, h("h2", {}, "AI progress by 2030"),
    h("p", { class: "sub" }, "The survey asks which level of AI capability will be reached by the end of 2030."),
    h("div", { class: "scenario-bars" }, scenarioBar("Model ensemble", e, modelDate),
      scenarioBar("Full human panel", fullPanel, humanSurveyDate)),
    h("div", { class: "scroll", style: "margin-top: 14px" }, h("table", { class: "tv" },
      h("thead", {}, h("tr", {}, h("th", {}, "Probability"), h("th", {}, "Model panel"), models.map(mo => h("th", {}, mo)), human.map(panel => h("th", {}, panel.label)))),
      h("tbody", {},
        SCEN.map(sc => h("tr", {}, h("th", { scope: "row" }, h("button", { type: "button", class: "scenario-label", ...events(sc) }, sc.label)), modelProb(e?.[sc.id]),
          models.map(mo => modelProb(sp?.models?.[mo]?.[sc.id])), humanProb(sc)))))),
    tip);
}

function download() {
  return D.download && h("a", { class: "dl", href: D.download, download: D.download,
    title: "Everything: forecasts.csv, rationales.csv, the AI progress answers, the questions, the history, and the run files with every search and page read" },
    "⤓ Download data");
}

function baselineDetails() {
  const baseline = D.baseline;
  const label = baseline?.as_of ? `Baseline as of ${baseline.as_of}`
    : baseline?.source === "survey" ? "Baseline from the original survey"
    : "Baseline as-of date unavailable";
  return h("p", { class: "sub" }, label, " · ", h("a", { href: "release.json" }, "Release metadata"));
}

function render(previous) {
  charts.length = 0;
  // Hold the page's height while it is rebuilt: a chart measures its box as it
  // is drawn, and a page that is briefly shorter would lose its scroll position.
  root.style.minHeight = root.offsetHeight + "px";
  root.classList.remove("still");
  const top = Object.keys(headlineMeasures).map(id => D.questions.find(q => q.id === id)).filter(Boolean);
  const rest = D.questions.filter(q => !top.includes(q));
  const L = D.latest, hasForecasts = Boolean(L || D.human?.length);
  // replaceChildren would print a `false` as text, so the absent sections are filtered out.
  root.replaceChildren(...[
    h("header", {},
      h("div", { class: "top" },
        h("a", { href: "https://forecastingresearch.org", title: "Forecasting Research Institute" }, h("img", { class: "brand-logo", src: "web/img/fri-logo.svg", alt: "Forecasting Research Institute", width: 231, height: 37 })),
        download()),
      h("nav", { class: "pages", "aria-label": "EEAI pages" }, h("a", { href: "index.html", "aria-current": "page" }, "Survey"), h("a", { href: "model.html" }, "Economy model")),
      h("h1", {}, "EEAI (Economic Effects of AI)"),
      h("p", { class: "lede" }, "A panel of frontier AI models takes FRI's Economic Effects of AI survey: where the US economy is heading by 2030 and 2050, and how that depends on how fast AI improves."),
      L && h("p", { class: "meta" }, `Latest run ${L.date} · ${L.models.join(", ")} · each model searches the web before answering`),
      D.synthetic && h("div", { class: "banner", role: "status" }, h("b", {}, "Placeholder data. "), "These numbers are made up to show the layout. No model has been asked yet.")),
    !L && h("section", { class: "card" }, h("h2", {}, "No model forecasts yet"), h("p", { class: "empty" }, "The panel has not been asked. The questions are ready; the first run will fill this page.")),
    hasForecasts && top.length > 0 && headlines(top),
    hasForecasts && h("section", { class: "card" }, h("h2", {}, "The other indicators"),
      h("p", { class: "sub" }, `Each indicator has its own scale. ` + (historyOf.has("grid")
        ? `Each chart tracks forecasts for its selected year across runs.`
        : "Dots show model and human forecasts at the available target dates.")),
      controls("grid"), legend("80% range, where the survey asks for one", historyOf.has("grid"), rest), h("div", { class: "grid" }, rest.map(tile))),
    hasForecasts && progress(),
    D.download && h("section", { class: "card" }, h("div", { class: "head" },
      h("div", {}, h("h2", {}, "Download data"),
        h("p", { class: "sub", style: "color: var(--ink-soft); margin: 4px 0 0; max-width: 640px" }, "Every forecast from every model in every run, each model's rationale, the questions, and the run files with every search and page read."),
        baselineDetails()),
      download())),
    h("footer", {}, "Questions and scenario definitions are from the Forecasting Research Institute's Economic Effects of AI survey. ",
      "The panel is the four highest-ranked models on Epoch's Capabilities Index that FRI can run, one per model family. ",
      "Once an outcome is available, its table shows the forecast median minus the outcome. Conditional forecasts are scored when the AI scenario is known.")].filter(Boolean));
  for (const draw of charts) draw(previous);
  root.style.minHeight = "";
}
let timer;
// (a resize redraws the charts where they stand: "still", so the forecasts do not fade in again)
window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(() => { root.classList.add("still"); charts.forEach(d => d()); }, 120); });
render();
