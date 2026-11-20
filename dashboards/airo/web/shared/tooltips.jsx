// One app-wide surface and placement policy for text, HTML and React tooltips.
function appTooltip(target, options = {}) {
  return window.tippy(target, {
    theme: "airo", arrow: true, maxWidth: 360, offset: [0, 8],
    placement: "right", appendTo: () => document.body, animation: false,
    ...options,
  });
}

// React owns content; Popper owns viewport-aware placement. Coordinates are SVG
// user units, transformed through the actual screen matrix (including resize).
function PointTooltip({ anchor, box, x, y, children, maxWidth = 360, interactive = false, motion = false }) {
  const [content] = useState(() => document.createElement("div"));
  const tooltip = React.useRef(null);
  const position = React.useRef(null);
  position.current = { anchor, box, x, y };
  React.useLayoutEffect(() => {
    const p = position.current;
    const target = p.anchor || (p.box && p.box.current);
    if (!target || !window.tippy) return;
    const instance = appTooltip(target, {
      // React owns visibility, including pinned tooltips; Tippy only places them.
      content, trigger: "manual", hideOnClick: false, onHide: () => false, maxWidth, interactive,
      moveTransition: motion ? "transform 160ms cubic-bezier(0.2, 0.8, 0.2, 1)" : "",
      popperOptions: { modifiers: [{ name: "preventOverflow", options: { altAxis: true, padding: 8 } }] },
      getReferenceClientRect: () => {
        const p = position.current;
        if (p.anchor) return p.anchor.getBoundingClientRect();
        const svg = p.box.current.querySelector("svg");
        const point = svg.createSVGPoint();
        point.x = p.x; point.y = p.y;
        const screen = point.matrixTransform(svg.getScreenCTM());
        return { x: screen.x, y: screen.y, left: screen.x, right: screen.x,
          top: screen.y, bottom: screen.y, width: 0, height: 0 };
      },
    });
    if (motion) instance.popper.dataset.forecastMotion = "";
    tooltip.current = instance;
    instance.show();
    return () => { instance.destroy(); tooltip.current = null; };
  }, [anchor, box, content, maxWidth, interactive, motion]);
  React.useLayoutEffect(() => {
    if (tooltip.current && tooltip.current.popperInstance) tooltip.current.popperInstance.update();
  });
  return ReactDOM.createPortal(children, content);
}
