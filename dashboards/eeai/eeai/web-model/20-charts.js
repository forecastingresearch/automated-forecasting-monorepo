// The charts: an outcome over the years (fanChart), or the forecast for one
// year across runs (historyChart, the survey's History view).
//
// fanChart draws a median line with its 50% and 90% bands (one series: the
// unconditional forecast, or one scenario in the detail dialog) or three
// medians with their 50% bands (conditional on AI progress). It shows the years
// up to `last`: the near term (2025 to 2030, evenly) or the long term (to 2050,
// with 2025-2030 given half the width, each year asked, and 2030-2050 the other
// half, every five years, and a faint rule where the scale changes).
function timeScale(last) {
  return last > 2030 ? y => y <= 2030 ? (y - 2025) / 10 : 0.5 + (y - 2030) / (2 * (last - 2030))
    : y => (y - 2025) / (last - 2025);
}

// opts: size ("mini", "headline", "hero" or "dialog"); last (the last year
// shown; default all); year (a selected year, marked: the detail dialog's) and
// fromYear (the year marked before, so the mark slides over); previousScale (the
// time scale before the term changed: the chart eases from it, as the survey's);
// breakdown (the tooltip's rows; see hover).
function fanChart(box, o, years, series, opts) {
  box.replaceChildren();
  const mini = opts.size === "mini" || opts.size === "headline";      // (a headline chart is taller, labelled as a small one)
  const W = Math.max(box.clientWidth || 300, 240), H = { mini: 150, headline: 200, dialog: 320 }[opts.size] || 260;
  const m = { l: mini ? 40 : 52, r: 12, t: 10, b: 24 };
  const last = opts.last || +years[years.length - 1];
  const shown = years.map((y, i) => +y <= last ? i : -1).filter(i => i >= 0);
  const pts = series.flatMap(sr => shown.flatMap(i => { const c = sr.cells[i]; return c && c[MED] != null ? [sr.band90 ? c[0] : c[1], sr.band90 ? c[4] : c[3]] : []; }))
    .filter(v => v != null && isFinite(v));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${o.label}, ${years[0]} to ${last}` });
  box.append(svg);
  if (!pts.length) { svg.append(s("text", { x: W / 2, y: H / 2, "text-anchor": "middle" }, "No forecast")); return; }
  let lo = Math.min(...pts), hi = Math.max(...pts);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08; lo -= pad; hi += pad;
  const frac = timeScale(last);
  const X = y => m.l + frac(+y) * (W - m.l - m.r), Y = v => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  yAxis(svg, o, lo, hi, Y, W, m, mini);
  const xline = (y, attrs) => { const el = s("line", { class: "xline", "data-year": y, x1: X(y), x2: X(y), y1: m.t, y2: H - m.b, ...attrs }); svg.append(el); return el; };
  if (last > 2030) xline(2030, { stroke: "var(--line)", "stroke-dasharray": "2 3" });
  for (const i of shown) {
    const y = +years[i];
    if (mini && last > 2030 && ![2025, 2030, last].includes(y)) continue;     // a small long-term chart has room for three labels
    svg.append(s("text", { class: "time-tick", "data-year": y, x: X(y), y: H - 6, "text-anchor": "middle" }, y));
  }
  if (opts.year) {
    const mark = xline(opts.year, { stroke: "var(--ink-faint)", "stroke-width": 1, opacity: 0.5 });
    if (opts.fromYear && opts.fromYear !== opts.year && mark.animate && !reducedMotion())
      mark.animate([{ transform: `translateX(${X(opts.fromYear) - X(opts.year)}px)` }, { transform: "none" }], ZOOM);
  }
  const g = s("g", { class: "fc" });
  svg.append(g);
  for (const sr of series) {
    const idx = shown.filter(i => sr.cells[i] && sr.cells[i][MED] != null);
    const area = (a, b) => idx.map((i, k) => `${k ? "L" : "M"}${X(years[i])},${Y(sr.cells[i][a])}`).join("")
      + idx.slice().reverse().map(i => `L${X(years[i])},${Y(sr.cells[i][b])}`).join("") + "Z";
    if (sr.band90) g.append(s("path", { d: area(0, 4), fill: sr.color, opacity: 0.08 }));
    g.append(s("path", { d: area(1, 3), fill: sr.color, opacity: sr.band90 ? 0.18 : 0.12 }));
    g.append(s("path", { d: idx.map((i, k) => `${k ? "L" : "M"}${X(years[i])},${Y(sr.cells[i][MED])}`).join(""),
      fill: "none", stroke: sr.color, "stroke-width": 2 }));
    for (const i of idx) g.append(s("circle", { "data-year": years[i], cx: X(years[i]), cy: Y(sr.cells[i][MED]), r: mini ? 2 : 2.8, fill: sr.color }));
  }
  box.dataset.timeline = o.id;
  box.readTimeScale = () => X;
  hover(box, svg, W, years.slice(0, shown.length), X, series, o, opts.breakdown);
  if (opts.previousScale) zoomTimeline(svg, X, opts.previousScale, last);
}

function yAxis(svg, o, lo, hi, Y, W, m, mini) {
  const ticks = niceTicks(lo, hi, mini ? 3 : 5);
  // Tick labels carry as many decimals as the step needs, not the outcome's own.
  const tickFmt = { ...o, decimals: ticks.length > 1 ? Math.max(0, -Math.floor(Math.log10(ticks[1] - ticks[0]) + 1e-9)) : 0 };
  for (const t of ticks) {
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: "var(--line-soft)" }));
    svg.append(s("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end" }, fmt(tickFmt, t, true)));
  }
  if (lo < 0 && hi > 0) svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: "var(--line)" }));
}

const ZOOM = { duration: 440, easing: "cubic-bezier(.22,.68,.2,1)" };
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
// The survey's zoomTimeline: draw the new chart, then ease each mark in from
// where the previous time scale put it. Points, ticks and rules move to their
// own year's old position; the bands and lines stretch from their old extent.
function zoomTimeline(svg, X, previous, last) {
  const scale = (previous(last) - previous(2025)) / (X(last) - X(2025));
  const shift = previous(2025) - scale * X(2025);
  if (Math.abs(scale - 1) < .001 && Math.abs(shift) < .1) return;
  svg.classList.add("zooming");
  let animation;
  for (const el of svg.querySelectorAll("[data-year]")) {
    const y = el.dataset.year, at = X(y);
    animation = el.animate([{ transform: `translateX(${previous(y) - at}px)` }, { transform: "none" }], ZOOM);
  }
  for (const el of svg.querySelectorAll(".fc path"))
    animation = el.animate([{ transform: `matrix(${scale},0,0,1,${shift},0)` }, { transform: "none" }], ZOOM);
  if (animation) animation.onfinish = () => svg.classList.remove("zooming");
  else svg.classList.remove("zooming");
}

// The History view: the forecast for one year (`target`) in each run, by the
// date it was made. runs: [{date}]; each series' cells are per run.
function historyChart(box, o, runs, series, opts) {
  box.replaceChildren();
  const mini = opts.size === "mini" || opts.size === "headline";
  const W = Math.max(box.clientWidth || 300, 240), H = { mini: 150, headline: 200 }[opts.size] || 260;
  const m = { l: mini ? 40 : 52, r: 16, t: 10, b: 24 };
  const pts = series.flatMap(sr => sr.cells.flatMap(c => c && c[MED] != null ? [sr.band90 ? c[0] : c[1], sr.band90 ? c[4] : c[3]] : []))
    .filter(v => v != null && isFinite(v));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${o.label}: the forecast for ${opts.target} in each run` });
  box.append(svg);
  if (!pts.length) { svg.append(s("text", { x: W / 2, y: H / 2, "text-anchor": "middle" }, `No forecast for ${opts.target}`)); return; }
  let lo = Math.min(...pts), hi = Math.max(...pts);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08; lo -= pad; hi += pad;
  const t = runs.map(r => Date.parse(r.date)), t0 = Math.min(...t), t1 = Math.max(...t);
  // One run sits in the middle; more spread over the dates they were made.
  const X = i => m.l + (t1 > t0 ? (t[i] - t0) / (t1 - t0) : 0.5) * (W - m.l - m.r), Y = v => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  yAxis(svg, o, lo, hi, Y, W, m, mini);
  const labelled = runs.length <= 4 ? runs.map((_, i) => i) : [0, runs.length - 1];
  for (const i of labelled) svg.append(s("text", { x: X(i), y: H - 6, "text-anchor": runs.length === 1 ? "middle" : i ? "end" : "start" }, runs[i].date));
  const g = s("g", { class: "fc" });
  svg.append(g);
  for (const sr of series) {
    const idx = sr.cells.map((c, i) => c && c[MED] != null ? i : -1).filter(i => i >= 0);
    const area = (a, b) => idx.map((i, k) => `${k ? "L" : "M"}${X(i)},${Y(sr.cells[i][a])}`).join("")
      + idx.slice().reverse().map(i => `L${X(i)},${Y(sr.cells[i][b])}`).join("") + "Z";
    if (idx.length > 1) {
      if (sr.band90) g.append(s("path", { d: area(0, 4), fill: sr.color, opacity: 0.08 }));
      g.append(s("path", { d: area(1, 3), fill: sr.color, opacity: sr.band90 ? 0.18 : 0.12 }));
      g.append(s("path", { d: idx.map((i, k) => `${k ? "L" : "M"}${X(i)},${Y(sr.cells[i][MED])}`).join(""), fill: "none", stroke: sr.color, "stroke-width": 2 }));
    } else for (const i of idx)                           // one run: its interval as a whisker
      g.append(s("line", { x1: X(i), x2: X(i), y1: Y(sr.cells[i][1]), y2: Y(sr.cells[i][3]), stroke: sr.color, "stroke-width": 6, opacity: 0.25, "stroke-linecap": "round" }));
    for (const i of idx) g.append(s("circle", { cx: X(i), cy: Y(sr.cells[i][MED]), r: mini ? 3 : 3.5, fill: sr.color }));
  }
  const kind = series.length === 1 && series[0].id === "unconditional" ? ", unconditional" : "";
  hover(box, svg, W, runs.map((_, i) => i), X, series, o, opts.breakdown, i => `Asked ${runs[i].date} · forecast for ${opts.target}${kind}`);
}

// A tooltip number, right-aligned, with its interval in small type beneath (the survey's tipNumber).
function tipNumber(o, value, detail, bold) {
  return h("span", { class: "mono tip-number" }, h(bold ? "b" : "span", { class: "tip-value" }, fmt(o, value)), detail && h("small", {}, detail));
}
const rangeText = (o, c, lo, hi) => c && c[lo] != null ? `${fmt(o, c[lo], true)} to ${fmt(o, c[hi], true)}` : "";

// The tooltip, as the survey's: a column per series shown, the forecaster's
// median with its intervals beneath, then (for the ensemble) each model's
// median. keys: the stops along the x axis (years, or runs), X(key) their
// position; breakdown: {label, models: [model], at(model, series id, stop index) -> cell};
// title(i): the tooltip's heading (default: the year, and the window a growth rate covers).
function hover(box, svg, W, keys, X, series, o, breakdown, title) {
  const tip = h("div", { class: "tip", style: "display: none" });
  box.append(tip);
  const xs = keys.map(X);
  svg.addEventListener("pointermove", ev => {
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
    let i = 0; xs.forEach((x, k) => { if (Math.abs(x - px) < Math.abs(xs[i] - px)) i = k; });
    const shown = series.filter(sr => sr.cells[i] && sr.cells[i][MED] != null);
    if (!shown.length) { tip.style.display = "none"; return; }
    const grid = h("div", { class: "who", style: `grid-template-columns: auto repeat(${shown.length}, minmax(0, auto))` });
    if (shown.length > 1) grid.append(h("span", {}), ...shown.map(sr => h("i", {}, h("u", { style: `background: ${sr.color}` }), sr.label.replace(" progress", ""))));
    grid.append(h("b", {}, `${(breakdown && breakdown.label) || "Median"}`), ...shown.map(sr => {
      const c = sr.cells[i];
      return tipNumber(o, c[MED], `50%: ${rangeText(o, c, 1, 3)}` + (sr.band90 ? ` · 90%: ${rangeText(o, c, 0, 4)}` : ""), true);
    }));
    for (const m of (breakdown && breakdown.models) || [])
      grid.append(h("i", {}, m), ...shown.map(sr => tipNumber(o, (breakdown.at(m, sr.id, i) || [])[MED])));
    const y = keys[i], when = y + (o.kind === "growth" && +y > 2030 ? ` (average since ${keys[i - 1]})` : "");
    tip.replaceChildren(h("b", {}, title ? title(i) : shown.length === 1 && shown[0].id === "unconditional" ? `${when} · unconditional` : when), grid);
    tip.style.display = "block";
    const left = xs[i] / W * r.width;
    tip.style.left = Math.min(Math.max(left - tip.offsetWidth / 2, 0), r.width - tip.offsetWidth) + "px";
    tip.style.top = "-8px";
    tip.style.transform = "translateY(-100%)";
  });
  svg.addEventListener("pointerleave", () => { tip.style.display = "none"; });
}
