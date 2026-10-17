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
//
// Browsers keep CSS Color 4 values in their own form in computed styles (Chrome 111+ and
// Firefox return oklch(), oklab(), lab(), lch() and color() as written, and Tailwind v4's
// palette is oklch), so every one of them is converted to sRGB here (out-of-gamut channels
// are clamped), never dropped. A colour function this snippet cannot convert throws, so a
// page it cannot read is reported rather than measured as if those colours were absent.
function measureColours(root) {
  const scope = root || document;
  const clamp01 = (x) => Math.min(1, Math.max(0, x));
  const mul = (m, v) => m.map((row) => row[0] * v[0] + row[1] * v[1] + row[2] * v[2]);
  const encode = (c) => {
    const s = Math.sign(c) || 1;
    const a = Math.abs(c);
    return s * (a > 0.0031308 ? 1.055 * Math.pow(a, 1 / 2.4) - 0.055 : 12.92 * a);
  };
  const decode = (c) => {
    const s = Math.sign(c) || 1;
    const a = Math.abs(c);
    return s * (a <= 0.04045 ? a / 12.92 : Math.pow((a + 0.055) / 1.055, 2.4));
  };
  const XYZ_D65_TO_SRGB = [
    [3.2409699419045226, -1.537383177570094, -0.4986107602930034],
    [-0.9692436362808796, 1.8759675015077202, 0.04155505740717559],
    [0.05563007969699366, -0.20397695888897652, 1.0569715142428786],
  ];
  const D50_TO_D65 = [
    [0.9554734527042182, -0.023098536874261423, 0.0632593086610217],
    [-0.028369706963208136, 1.0099954580058226, 0.021041398966943008],
    [0.012314001688319899, -0.020507696433477912, 1.3303659366080753],
  ];
  const P3_TO_XYZ_D65 = [
    [0.4865709486482162, 0.26566769316909306, 0.1982172852343625],
    [0.2289745640697488, 0.6917385218365064, 0.079286914093745],
    [0.0, 0.04511338185890264, 1.043944368900976],
  ];
  const oklabToLinear = (L, a, b) => {
    const l = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3);
    const m = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3);
    const s = Math.pow(L - 0.0894841775 * a - 1.291485548 * b, 3);
    return [
      4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
    ];
  };
  const labToLinear = (L, a, b) => {
    const eps = 216 / 24389;
    const kappa = 24389 / 27;
    const fy = (L + 16) / 116;
    const fx = a / 500 + fy;
    const fz = fy - b / 200;
    const f = (t) => (t * t * t > eps ? t * t * t : (116 * t - 16) / kappa);
    const xyz50 = [0.96422 * f(fx), L > kappa * eps ? fy * fy * fy : L / kappa, 0.82521 * f(fz)];
    return mul(XYZ_D65_TO_SRGB, mul(D50_TO_D65, xyz50));
  };
  const hueDegrees = (token) => {
    const m = /^(-?[\d.]+(?:e-?\d+)?)(deg|rad|grad|turn)?$/.exec(token);
    if (!m) return NaN;
    const unit = { deg: 1, rad: 180 / Math.PI, grad: 0.9, turn: 360 }[m[2] || "deg"];
    return parseFloat(m[1]) * unit;
  };
  // A number, a percentage of `full`, or `none` (a missing component is 0).
  const component = (token, full) => {
    if (token === "none") return 0;
    if (token.endsWith("%")) return (parseFloat(token) / 100) * full;
    return /^-?[\d.]+(?:e-?\d+)?$/.test(token) ? parseFloat(token) : NaN;
  };
  const toHex = (value) => {
    const text = (value || "").trim().toLowerCase();
    const call = /^(rgba?|oklab|oklch|lab|lch|color|hwb|hsla?|color-mix|light-dark)\((.*)\)$/.exec(text);
    if (!call) return null; // none, url(#gradient), transparent keywords: not a colour
    const [fn, body] = [call[1], call[2]];
    const [main, alpha] = body.split("/").map((s) => s.trim());
    const tokens = main.split(/[\s,]+/).filter(Boolean);
    let alphaToken = alpha;
    if (alphaToken === undefined && fn.startsWith("rgb") && tokens.length === 4) alphaToken = tokens.pop();
    if (alphaToken !== undefined && component(alphaToken, 1) !== 1) return null; // translucent
    const unreadable = () => {
      throw new Error("measureColours cannot read the computed colour " + JSON.stringify(value));
    };
    let linear;
    if (fn === "rgb" || fn === "rgba") {
      if (tokens.length !== 3) unreadable();
      const channels = tokens.map((t) => component(t, 255));
      if (channels.some((c) => Number.isNaN(c))) unreadable();
      linear = channels.map((c) => decode(clamp01(c / 255)));
    } else if (fn === "oklab" || fn === "oklch") {
      if (tokens.length !== 3) unreadable();
      const L = component(tokens[0], 1);
      const second = component(tokens[1], 0.4);
      let third;
      if (fn === "oklch") third = hueDegrees(tokens[2] === "none" ? "0" : tokens[2]);
      else third = component(tokens[2], 0.4);
      if ([L, second, third].some((c) => Number.isNaN(c))) unreadable();
      if (fn === "oklch") {
        const h = (third * Math.PI) / 180;
        linear = oklabToLinear(L, second * Math.cos(h), second * Math.sin(h));
      } else {
        linear = oklabToLinear(L, second, third);
      }
    } else if (fn === "lab" || fn === "lch") {
      if (tokens.length !== 3) unreadable();
      const L = component(tokens[0], 100);
      const second = component(tokens[1], fn === "lab" ? 125 : 150);
      let third;
      if (fn === "lch") third = hueDegrees(tokens[2] === "none" ? "0" : tokens[2]);
      else third = component(tokens[2], 125);
      if ([L, second, third].some((c) => Number.isNaN(c))) unreadable();
      if (fn === "lch") {
        const h = (third * Math.PI) / 180;
        linear = labToLinear(L, second * Math.cos(h), second * Math.sin(h));
      } else {
        linear = labToLinear(L, second, third);
      }
    } else if (fn === "color" && tokens.length === 4 && ["srgb", "srgb-linear", "display-p3"].includes(tokens[0])) {
      const c = tokens.slice(1).map((t) => component(t, 1));
      if (c.some((v) => Number.isNaN(v))) unreadable();
      if (tokens[0] === "srgb") linear = c.map(decode);
      else if (tokens[0] === "srgb-linear") linear = c;
      else linear = mul(XYZ_D65_TO_SRGB, mul(P3_TO_XYZ_D65, c.map(decode)));
    } else {
      unreadable();
    }
    return "#" + linear.map((c) => Math.round(clamp01(encode(c)) * 255).toString(16).padStart(2, "0")).join("");
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
