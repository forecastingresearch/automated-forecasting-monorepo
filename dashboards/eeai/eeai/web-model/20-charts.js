// One chart: an outcome over the years, as a median line with its 50% and 90%
// bands (one series: the unconditional forecast) or three medians with their
// 50% bands (split by AI progress). The years are uneven -- each year to 2030,
// then 2035, 2040, 2050 -- so the x axis gives 2025-2030 half the width and
// 2030-2050 the other half, with a faint rule where the scale changes.
const xFrac = y => y <= 2030 ? (y - 2025) / 10 : 0.5 + (y - 2030) / 40;

function fanChart(box, o, years, series, opts) {
  box.replaceChildren();
  const mini = opts.size === "mini";
  const W = Math.max(box.clientWidth || 300, 240), H = mini ? 150 : 260;
  const m = { l: mini ? 40 : 52, r: 12, t: 10, b: 24 };
  const pts = series.flatMap(sr => sr.cells.flatMap((c, i) => c && c[MED] != null ? [sr.band90 ? c[0] : c[1], sr.band90 ? c[4] : c[3]] : []))
    .filter(v => v != null && isFinite(v));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${o.label}, ${years[0]} to ${years[years.length - 1]}` });
  box.append(svg);
  if (!pts.length) { svg.append(s("text", { x: W / 2, y: H / 2, "text-anchor": "middle" }, "No forecast")); return; }
  let lo = Math.min(...pts), hi = Math.max(...pts);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08; lo -= pad; hi += pad;
  const X = y => m.l + xFrac(+y) * (W - m.l - m.r), Y = v => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const ticks = niceTicks(lo, hi, mini ? 3 : 5);
  // Tick labels carry as many decimals as the step needs, not the outcome's own.
  const tickFmt = { ...o, decimals: ticks.length > 1 ? Math.max(0, -Math.floor(Math.log10(ticks[1] - ticks[0]) + 1e-9)) : 0 };
  for (const t of ticks) {
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: "var(--line-soft)" }));
    svg.append(s("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end" }, fmt(tickFmt, t, true)));
  }
  if (lo < 0 && hi > 0) svg.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: "var(--line)" }));
  svg.append(s("line", { x1: X(2030), x2: X(2030), y1: m.t, y2: H - m.b, stroke: "var(--line)", "stroke-dasharray": "2 3" }));
  for (const y of years) {
    if (mini && ![2025, 2030, 2050].includes(+y)) continue;          // a small chart has room for three labels
    svg.append(s("text", { x: X(y), y: H - 6, "text-anchor": "middle" }, y));
  }
  if (opts.year) svg.append(s("line", { x1: X(opts.year), x2: X(opts.year), y1: m.t, y2: H - m.b, stroke: "var(--ink-faint)", "stroke-width": 1, opacity: 0.5 }));
  const g = s("g", { class: "fc" });
  svg.append(g);
  for (const sr of series) {
    const idx = sr.cells.map((c, i) => c && c[MED] != null ? i : -1).filter(i => i >= 0);
    const area = (a, b) => idx.map((i, k) => `${k ? "L" : "M"}${X(years[i])},${Y(sr.cells[i][a])}`).join("")
      + idx.slice().reverse().map(i => `L${X(years[i])},${Y(sr.cells[i][b])}`).join("") + "Z";
    if (sr.band90) g.append(s("path", { d: area(0, 4), fill: sr.color, opacity: 0.08 }));
    g.append(s("path", { d: area(1, 3), fill: sr.color, opacity: sr.band90 ? 0.18 : 0.12 }));
    g.append(s("path", { d: idx.map((i, k) => `${k ? "L" : "M"}${X(years[i])},${Y(sr.cells[i][MED])}`).join(""),
      fill: "none", stroke: sr.color, "stroke-width": 2 }));
    for (const i of idx) g.append(s("circle", { cx: X(years[i]), cy: Y(sr.cells[i][MED]), r: mini ? 2 : 2.8, fill: sr.color }));
  }
  hover(box, svg, W, years, X, series, o);
}

// The tooltip: the nearest year's median and intervals, one row per series shown.
function hover(box, svg, W, years, X, series, o) {
  const tip = h("div", { class: "tip", style: "display: none" });
  box.append(tip);
  const xs = years.map(X);
  svg.addEventListener("pointermove", ev => {
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
    let i = 0; xs.forEach((x, k) => { if (Math.abs(x - px) < Math.abs(xs[i] - px)) i = k; });
    const rows = series.filter(sr => sr.cells[i] && sr.cells[i][MED] != null).map(sr => {
      const c = sr.cells[i];
      return h("div", { class: "row" }, h("i", {}, sr.label), h("span", { class: "mono" },
        `${fmt(o, c[MED])}  50%: ${fmt(o, c[1], true)} to ${fmt(o, c[3], true)}` + (sr.band90 ? `  90%: ${fmt(o, c[0], true)} to ${fmt(o, c[4], true)}` : "")));
    });
    if (!rows.length) { tip.style.display = "none"; return; }
    tip.replaceChildren(h("b", {}, years[i] + (o.kind === "growth" && +years[i] > 2030 ? ` (average since ${years[i - 1]})` : "")), ...rows);
    tip.style.display = "block";
    const left = xs[i] / W * r.width;
    tip.style.left = Math.min(Math.max(left - tip.offsetWidth / 2, 0), r.width - tip.offsetWidth) + "px";
    tip.style.top = "-8px";
    tip.style.transform = "translateY(-100%)";
  });
  svg.addEventListener("pointerleave", () => { tip.style.display = "none"; });
}
