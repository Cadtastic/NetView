// Inline SVG icons (fixed strings, no user input). They use currentColor so themes colour them.
const svg = (body) =>
  `<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

export const gear = svg(
  '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M12.6 3.4l-1.3 1.3M4.7 11.3l-1.3 1.3"/>',
);
export const close = svg('<path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/>');
export const check = svg('<path d="M3 8.5l3.2 3.2L13 4.8"/>');
export const alert = svg('<path d="M8 2.2l6.2 11H1.8z"/><path d="M8 6.8v3M8 11.6v.1"/>');
export const live = svg('<circle cx="8" cy="8" r="2" fill="currentColor"/><circle cx="8" cy="8" r="5.2"/>');
