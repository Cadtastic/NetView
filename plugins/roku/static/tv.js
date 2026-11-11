// The TV drawing: a picture of a physical object, so its fills are fixed colours rather than theme tokens.
import { esc } from "./html.js";

const TILE_COLS = [
  ["#c4302b", "#146eb4", "#b20710"],
  ["#1a8b4c", "#113ccf", "#c7860c"],
  ["#4a1fb8", "#1a9c48", "#0064ff"],
];
const MENU_W = [58, 46, 64, 40, 52];

function onScreen() {
  const menu = MENU_W.map(
    (w, i) => `<rect x="42" y="${88 + i * 24}" width="${w}" height="6" rx="3" fill="#d9c7ef" fill-opacity=".75"/>`,
  ).join("");
  const tiles = TILE_COLS.map((row, r) =>
    row
      .map((fill, c) => {
        const x = 146 + c * 102;
        const y = 60 + r * 64;
        const ring =
          r === 0 && c === 0
            ? `<rect x="${x - 3}" y="${y - 3}" width="100" height="62" rx="7" fill="none" stroke="#fff" stroke-width="2.5"/>`
            : "";
        return `<rect x="${x}" y="${y}" width="94" height="56" rx="5" fill="${fill}"/>${ring}`;
      })
      .join(""),
  ).join("");
  return `
    <defs><linearGradient id="rk-home" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6f3fa3"/><stop offset="1" stop-color="#2e1648"/></linearGradient></defs>
    <rect x="22" y="18" width="436" height="246" fill="url(#rk-home)"/>
    <text x="40" y="44" fill="#fff" font-family="Segoe UI, sans-serif" font-size="13" font-weight="700" letter-spacing="1">HOME</text>
    <text x="440" y="44" fill="#e9dcf7" font-family="Segoe UI, sans-serif" font-size="11" text-anchor="end">7:42 pm</text>
    <rect x="34" y="60" width="96" height="20" rx="3" fill="#ffffff" fill-opacity=".22"/>
    <rect x="42" y="67" width="50" height="6" rx="3" fill="#fff"/>
    ${menu}${tiles}`;
}

function offScreen() {
  return `
    <defs><linearGradient id="rk-glass" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b1d22"/><stop offset="1" stop-color="#08090b"/></linearGradient></defs>
    <rect x="22" y="18" width="436" height="246" fill="url(#rk-glass)"/>
    <polygon points="22,18 250,18 120,264 22,264" fill="#ffffff" fill-opacity=".035"/>`;
}

/** The inline SVG of a TV, on (generic home screen) or off (blank glass and a red standby light). */
export function tvSvg({ on, name }) {
  const label = `${name} is ${on ? "on" : "off"}`;
  return `<svg viewBox="0 0 480 330" role="img" aria-label="${esc(label)}">
    <ellipse cx="240" cy="318" rx="190" ry="6" fill="#000" fill-opacity=".18"/>
    <path d="M86 284 L66 316 L78 316 L100 284 Z M394 284 L414 316 L402 316 L380 284 Z" fill="#3c3f46"/>
    <rect x="12" y="8" width="456" height="280" rx="8" fill="#141518" stroke="#2b2d33" stroke-width="2"/>
    ${on ? onScreen() : offScreen()}
    <text x="240" y="280" fill="#8a8d95" font-family="Segoe UI, sans-serif" font-size="9" font-weight="700" text-anchor="middle" letter-spacing="1.5">ROKU TV</text>
    <circle cx="440" cy="277" r="2.6" fill="${on ? "#3b3e44" : "#e0463a"}"/>
    ${on ? "" : '<circle cx="440" cy="277" r="6" fill="#e0463a" fill-opacity=".18"/>'}
  </svg>`;
}
