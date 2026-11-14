// Inline SVG icons (fixed strings, no user input). They use currentColor so themes colour them.
const svg = (body) =>
  `<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

export const gear = svg(
  '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M12.6 3.4l-1.3 1.3M4.7 11.3l-1.3 1.3"/>',
);
export const user = svg('<circle cx="8" cy="5.5" r="2.7"/><path d="M2.6 14c.5-3 2.7-4.6 5.4-4.6s4.9 1.6 5.4 4.6"/>');
export const shieldLock = svg(
  '<path d="M8 1.6l5.2 2v4c0 3.2-2.2 5.4-5.2 6.8C5 13 2.8 10.8 2.8 7.6v-4z"/><rect x="5.8" y="7" width="4.4" height="3.2" rx=".6"/><path d="M6.8 7V5.8a1.2 1.2 0 012.4 0V7"/>',
);
export const key = svg('<circle cx="5" cy="10.5" r="2.8"/><path d="M7 8.5l6-6M10.5 5l1.8 1.8M12 3.5l1.5 1.5"/>');
export const logout = svg('<path d="M6.5 2.5h-3v11h3M6 8h7.5M11 5.5L13.5 8 11 10.5"/>');
export const close = svg('<path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/>');
export const check = svg('<path d="M3 8.5l3.2 3.2L13 4.8"/>');
export const alert = svg('<path d="M8 2.2l6.2 11H1.8z"/><path d="M8 6.8v3M8 11.6v.1"/>');
export const live = svg('<circle cx="8" cy="8" r="2" fill="currentColor"/><circle cx="8" cy="8" r="5.2"/>');
