// The economy model's page: window.__EEAI_MODEL__ (eeai/model/build.py). Plain DOM.
// Its own small copy of the survey page's helpers (web/10-chart.js), so the
// survey's script is left as it is.
const NS = "http://www.w3.org/2000/svg";
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid);
  return el;
}
function s(tag, attrs, text) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}
// A number in an outcome's unit: decimals from the outcome, "%" for percent units, "$" for dollars.
function fmt(o, v, bare) {
  if (v == null || !isFinite(v)) return "–";
  const n = v.toLocaleString("en-US", { minimumFractionDigits: o.decimals, maximumFractionDigits: o.decimals });
  if (o.unit.startsWith("US$")) return bare ? n : "$" + n;
  return o.unit.startsWith("%") && !bare ? n + "%" : n;
}
function niceTicks(lo, hi, n) {
  const span = hi - lo || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(m => m >= raw);
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-6; t += step) out.push(+t.toFixed(10));
  return out;
}
const SCEN = [
  { id: "slow", label: "Slow progress", color: "var(--slow)" },
  { id: "moderate", label: "Moderate progress", color: "var(--moderate)" },
  { id: "rapid", label: "Rapid progress", color: "var(--rapid)" },
];
const UNCOND = { id: "unconditional", label: "Unconditional", color: "var(--uncond)" };
// A summary cell is [q05, q25, q50, q75, q95].
const MED = 2;
