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
  const traces = drawSeries(svg, series, shown, i => X(years[i]), Y, mini, opts.selected, i => years[i]);
  box.dataset.timeline = o.id;
  box.readTimeScale = () => X;
  hover(box, svg, W, years.slice(0, shown.length), X, series, o, opts.breakdown, null, traces, opts.selected);
  if (opts.previousScale) zoomTimeline(svg, X, opts.previousScale, last);
}

// Draw the series, as the survey does: one series (the unconditional forecast)
// keeps its bands in view; with several, each line's bands stay hidden until the
// line is hovered (or until it is the selected series), the other lines fade, and
// an invisible, wider stroke over each line makes it easy to hover. stops: the
// cell indexes to draw, pos(i) their x. A series may be dashed (the unconditional
// forecast beside the scenarios). -> traces for hover.
function drawSeries(svg, series, stops, pos, Y, mini, selected, yearOf) {
  const g = s("g", { class: "fc" });
  svg.append(g);
  const hidden = series.length > 1, traces = [];
  for (const sr of series) {
    const idx = stops.filter(i => sr.cells[i] && sr.cells[i][MED] != null);
    const area = (a, b) => idx.map((i, k) => `${k ? "L" : "M"}${pos(i)},${Y(sr.cells[i][a])}`).join("")
      + idx.slice().reverse().map(i => `L${pos(i)},${Y(sr.cells[i][b])}`).join("") + "Z";
    const band = s("g", hidden ? { "data-range": sr.id, visibility: sr.id === selected ? "visible" : "hidden", "pointer-events": "none" } : {});
    if (idx.length > 1) {
      if (sr.band90) band.append(s("path", { d: area(0, 4), fill: sr.color, opacity: 0.08 }));
      band.append(s("path", { d: area(1, 3), fill: sr.color, opacity: sr.band90 ? 0.18 : 0.14 }));
    } else for (const i of idx) {                       // one stop: its intervals as whiskers
      if (sr.band90) band.append(s("line", { x1: pos(i), x2: pos(i), y1: Y(sr.cells[i][0]), y2: Y(sr.cells[i][4]), stroke: sr.color, "stroke-width": 3, opacity: 0.2, "stroke-linecap": "round" }));
      band.append(s("line", { x1: pos(i), x2: pos(i), y1: Y(sr.cells[i][1]), y2: Y(sr.cells[i][3]), stroke: sr.color, "stroke-width": 7, opacity: 0.28, "stroke-linecap": "round" }));
    }
    g.prepend(band);                                    // (every band below every line)
    const d = idx.map((i, k) => `${k ? "L" : "M"}${pos(i)},${Y(sr.cells[i][MED])}`).join("");
    const mark = s("g", {});
    mark.append(s("path", { d, fill: "none", stroke: sr.color, "stroke-width": 2, ...(sr.dash ? { "stroke-dasharray": "5 4" } : {}) }));
    for (const i of idx) mark.append(s("circle", { "data-year": yearOf ? yearOf(i) : null, cx: pos(i), cy: Y(sr.cells[i][MED]), r: mini ? 2 : 2.8, fill: sr.color }));
    g.append(mark);
    traces.push({ id: sr.id, band, mark, hit: hidden && idx.length ? s("path", { d: idx.length > 1 ? d : `${d}L${pos(idx[0])},${Y(sr.cells[idx[0]][MED])}`,
      fill: "none", stroke: "transparent", "stroke-width": mini ? 12 : 16, "stroke-linecap": "round", "pointer-events": "stroke", "data-series": sr.id }) : null });
  }
  for (const t of traces) if (t.hit) g.append(t.hit);
  return traces;
}
// The hovered series (or, with none, the selected one) shows its bands; the others fade.
function focusSeries(traces, id, selected) {
  for (const t of traces) {
    if (t.band.hasAttribute("data-range")) t.band.setAttribute("visibility", t.id === (id || selected) ? "visible" : "hidden");
    t.mark.setAttribute("opacity", id && t.id !== id ? 0.3 : 1);
  }
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
  const traces = drawSeries(svg, series, runs.map((_, i) => i), X, Y, mini);
  const kind = series.length === 1 && series[0].id === "unconditional" ? ", unconditional" : "";
  hover(box, svg, W, runs.map((_, i) => i), X, series, o, opts.breakdown, i => `Asked ${runs[i].date} · forecast for ${opts.target}${kind}`, traces);
}

// A ranked dot chart: one row per industry or occupation group, sorted by the
// sort series' median. Conditional on AI progress, each row's three scenario
// medians sit on a thin line, so the line's length is how much the scenario
// matters; unconditional, one median with its 50% interval as a bar. A hollow
// ring marks 2025 where the measure has a 2025 value. Hovering a row shows its
// numbers in a tooltip, as the charts do.
// get(series id, k) -> the year's cell for row k; base(k) -> the 2025 median or null.
function rankChart(box, m, names, series, get, base, sortBy, when) {
  box.replaceChildren();
  const med = (id, k) => (get(id, k) || [])[MED];
  const rows = names.map((n, k) => ({ n, k })).filter(r => series.some(sr => med(sr.id, r.k) != null))
    .sort((a, b) => (med(sortBy, b.k) ?? -Infinity) - (med(sortBy, a.k) ?? -Infinity));
  if (!rows.length) { box.append(h("p", { class: "empty" }, "No forecast for this date.")); return; }
  const vals = rows.flatMap(r => [...series.flatMap(sr => { const c = get(sr.id, r.k) || []; return series.length > 1 ? [c[MED]] : [c[1], c[3]]; }), base(r.k)])
    .filter(v => v != null && isFinite(v));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.06; lo -= pad; hi += pad;
  const axis = h("div", { class: "rank-axis" }, h("span", {}), h("div", { class: "rank-track" }));
  const list = rows.map(r => ({ r, el: h("div", { class: "rank-row", tabindex: "0" }, h("span", { class: "rank-name" }, r.n.name), h("div", { class: "rank-track" })) }));
  const tip = h("div", { class: "tip", style: "display: none" });
  box.append(axis, ...list.map(x => x.el), tip);
  const TW = Math.max(axis.lastChild.clientWidth || 300, 120), RH = 22;
  const X = v => 6 + (v - lo) / (hi - lo) * (TW - 12);
  const ticks = niceTicks(lo, hi, TW < 260 ? 3 : 5);
  const tickFmt = { ...m, decimals: ticks.length > 1 ? Math.max(0, -Math.floor(Math.log10(ticks[1] - ticks[0]) + 1e-9)) : 0 };
  const top = s("svg", { viewBox: `0 0 ${TW} 18`, width: TW, height: 18, "aria-hidden": "true" });
  for (const t of ticks) top.append(s("text", { x: X(t), y: 13, "text-anchor": "middle" }, fmt(tickFmt, t, true)));
  axis.lastChild.append(top);
  for (const { r, el } of list) {
    const svg = s("svg", { viewBox: `0 0 ${TW} ${RH}`, width: TW, height: RH, role: "img",
      "aria-label": `${r.n.name}: ` + series.map(sr => `${sr.label} ${fmt(m, med(sr.id, r.k))}`).join(", ") });
    for (const t of ticks) svg.append(s("line", { x1: X(t), x2: X(t), y1: 0, y2: RH, stroke: "var(--line-soft)" }));
    if (lo < 0 && hi > 0) svg.append(s("line", { x1: X(0), x2: X(0), y1: 0, y2: RH, stroke: "var(--line)" }));
    const g = s("g", { class: "fc" });
    svg.append(g);
    if (series.length > 1) {
      const ms = series.map(sr => med(sr.id, r.k)).filter(v => v != null);
      g.append(s("line", { x1: X(Math.min(...ms)), x2: X(Math.max(...ms)), y1: RH / 2, y2: RH / 2, stroke: "var(--line)", "stroke-width": 2 }));
    } else {
      const c = get(series[0].id, r.k) || [];
      if (c[1] != null) g.append(s("rect", { x: X(c[1]), y: RH / 2 - 4, width: Math.max(X(c[3]) - X(c[1]), 1), height: 8, rx: 4, fill: series[0].color, opacity: 0.2 }));
    }
    const b = base(r.k);
    if (b != null) g.append(s("circle", { cx: X(b), cy: RH / 2, r: 4.5, fill: "var(--panel)", stroke: "var(--ink-faint)", "stroke-width": 1.5 }));
    for (const sr of series) { const v = med(sr.id, r.k); if (v != null) g.append(s("circle", { cx: X(v), cy: RH / 2, r: 4.5, fill: sr.color, stroke: "var(--panel)", "stroke-width": 1 })); }
    el.lastChild.append(svg);
    const show = () => {
      for (const x of list) x.el.classList.toggle("on", x.el === el);
      const grid = h("div", { class: "who", style: `grid-template-columns: auto repeat(${series.length}, minmax(0, auto))` });
      if (series.length > 1) grid.append(h("span", {}), ...series.map(sr => h("i", {}, h("u", { style: `background: ${sr.color}` }), sr.label.replace(" progress", ""))));
      grid.append(h("b", {}, "Ensemble median"), ...series.map(sr => { const c = get(sr.id, r.k) || []; return tipNumber(m, c[MED], c[MED] != null && `50%: ${rangeText(m, c, 1, 3)}`, true); }));
      if (b != null) grid.append(h("i", {}, "2025"), tipNumber(m, b), ...series.slice(1).map(() => h("span", {})));
      tip.replaceChildren(h("b", {}, `${r.n.name} · ${when}`), grid);
      tip.style.display = "block";
      const area = (box.closest("dialog") || document.documentElement).getBoundingClientRect(), br = box.getBoundingClientRect();
      const tw = tip.offsetWidth, want = el.lastChild.offsetLeft + X(b != null ? b : med(sortBy, r.k) ?? lo) + 14;
      tip.style.left = Math.max(Math.max(area.left, 0) + 8 - br.left, Math.min(Math.min(area.right, innerWidth) - 8 - tw - br.left, want)) + "px";
      tip.style.top = (el.offsetTop + el.offsetHeight + 4) + "px";
    };
    const hide = () => { el.classList.remove("on"); tip.style.display = "none"; };
    el.addEventListener("pointerenter", show); el.addEventListener("focus", show);
    el.addEventListener("pointerleave", hide); el.addEventListener("blur", hide);
  }
}

// A tooltip number, right-aligned, with its interval in small type beneath (the survey's tipNumber).
// (detail: a line, or several, such as the 50% and the 90% interval)
function tipNumber(o, value, detail, bold) {
  return h("span", { class: "mono tip-number" }, h(bold ? "b" : "span", { class: "tip-value" }, fmt(o, value)),
    [].concat(detail || []).filter(Boolean).map(line => h("small", {}, line)));
}
const rangeText = (o, c, lo, hi) => c && c[lo] != null ? `${fmt(o, c[lo], true)} to ${fmt(o, c[hi], true)}` : "";

// The tooltip, as the survey's: a column per series shown, the forecaster's
// median with its intervals beneath, then (for the ensemble) each model's
// median. keys: the stops along the x axis (years, or runs), X(key) their
// position; breakdown: {label, models: [model], at(model, series id, stop index) -> cell};
// title(i): the tooltip's heading (default: the year, and the window a growth rate covers);
// traces (from drawSeries): the hovered line shows its bands and the others fade.
// The tooltip sits inside the chart beside a crosshair on the nearest stop, as the survey's.
function hover(box, svg, W, keys, X, series, o, breakdown, title, traces = [], selected) {
  const tip = h("div", { class: "tip", style: "display: none" });
  box.append(tip);
  const xs = keys.map(X);
  const vb = svg.viewBox.baseVal, cross = s("line", { y1: 10, y2: vb.height - 24, stroke: "var(--ink-faint)", "stroke-dasharray": "3 3", visibility: "hidden", "pointer-events": "none" });
  svg.prepend(cross);
  const hide = () => { tip.style.display = "none"; cross.setAttribute("visibility", "hidden"); focusSeries(traces, null, selected); };
  svg.addEventListener("pointermove", ev => {
    focusSeries(traces, ev.target.getAttribute("data-series"), selected);
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
    let i = 0; xs.forEach((x, k) => { if (Math.abs(x - px) < Math.abs(xs[i] - px)) i = k; });
    const shown = series.filter(sr => sr.cells[i] && sr.cells[i][MED] != null);
    if (!shown.length) { hide(); return; }
    cross.setAttribute("x1", xs[i]); cross.setAttribute("x2", xs[i]); cross.setAttribute("visibility", "visible");
    const grid = h("div", { class: "who", style: `grid-template-columns: auto repeat(${shown.length}, minmax(0, auto))` });
    if (shown.length > 1) grid.append(h("span", {}), ...shown.map(sr => h("i", {}, h("u", { style: `background: ${sr.color}` }), sr.label.replace(" progress", ""))));
    grid.append(h("b", {}, `${(breakdown && breakdown.label) || "Median"}`), ...shown.map(sr => {
      const c = sr.cells[i];
      return tipNumber(o, c[MED], [`50%: ${rangeText(o, c, 1, 3)}`, sr.band90 && `90%: ${rangeText(o, c, 0, 4)}`], true);
    }));
    for (const m of (breakdown && breakdown.models) || [])
      grid.append(h("i", {}, m), ...shown.map(sr => tipNumber(o, (breakdown.at(m, sr.id, i) || [])[MED])));
    const y = keys[i], when = y + (o.kind === "growth" && +y > 2030 ? ` (average since ${keys[i - 1]})` : "");
    tip.replaceChildren(h("b", {}, title ? title(i) : shown.length === 1 && shown[0].id === "unconditional" ? `${when} · unconditional` : when), grid);
    tip.style.display = "block";
    // Beside the crosshair, on the side with room; kept inside the window (or the dialog it is in), not the chart.
    const left = xs[i] / W * r.width, tw = tip.offsetWidth;
    const area = (box.closest("dialog") || document.documentElement).getBoundingClientRect();
    const lo = Math.max(area.left, 0) + 8 - r.left, hi = Math.min(area.right, innerWidth) - 8 - tw - r.left;
    tip.style.left = Math.max(lo, Math.min(hi, left + (r.left + left + tw + 14 > Math.min(area.right, innerWidth) ? -tw - 10 : 10))) + "px";
    tip.style.top = "6px";
  });
  svg.addEventListener("pointerleave", hide);
}
