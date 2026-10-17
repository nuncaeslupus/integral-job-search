// T342: count the computed colours on the employer's page.
//
// Run in the browser console on the employer's own site (a page that shows its brand,
// not a cookie wall), then save the printed JSON and give it to
//   uv run python -m integral.brand_measure --site <url> --counts <file>
//
//   copy(JSON.stringify(measureColours()))
//
// It returns {"#rrggbb": elements}: for each rendered element, each distinct opaque
// colour it carries once (text colour, background, a visible border, an SVG fill or
// stroke). Translucent colours are skipped, as the colour seen depends on what is behind.
function measureColours(root) {
  const scope = root || document;
  const pattern = /^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)\s*(?:[,/]\s*([\d.]+%?)\s*)?\)$/;
  const toHex = (value) => {
    const m = pattern.exec((value || "").trim());
    if (!m) return null;
    if (m[4] !== undefined) {
      const alpha = m[4].endsWith("%") ? parseFloat(m[4]) / 100 : parseFloat(m[4]);
      if (alpha !== 1) return null;
    }
    const channels = [m[1], m[2], m[3]].map(Number);
    if (channels.some((c) => c > 255)) return null;
    return "#" + channels.map((c) => c.toString(16).padStart(2, "0")).join("");
  };
  const counts = {};
  for (const element of scope.querySelectorAll("body, body *")) {
    if (!element.getClientRects().length) continue; // not rendered
    const style = getComputedStyle(element);
    const found = [style.color, style.backgroundColor];
    if (element.namespaceURI === "http://www.w3.org/2000/svg") found.push(style.fill, style.stroke);
    for (const side of ["Top", "Right", "Bottom", "Left"]) {
      if (style["border" + side + "Style"] !== "none" && parseFloat(style["border" + side + "Width"]) > 0) {
        found.push(style["border" + side + "Color"]);
      }
    }
    for (const hex of new Set(found.map(toHex).filter(Boolean))) {
      counts[hex] = (counts[hex] || 0) + 1;
    }
  }
  return counts;
}

if (typeof module !== "undefined") module.exports = measureColours;
