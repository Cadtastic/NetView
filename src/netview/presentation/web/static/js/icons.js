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
export const chevronsLeft = svg('<path d="M8.5 4L4.5 8l4 4M12.5 4l-4 4 4 4"/>');
export const chevronDown = svg('<path d="M4 6l4 4 4-4"/>');
export const adjustments = svg('<path d="M3 4.5h5M11 4.5h2M3 11.5h2M8 11.5h5"/><circle cx="9.5" cy="4.5" r="1.5"/><circle cx="6.5" cy="11.5" r="1.5"/>');
export const users = svg('<circle cx="6" cy="5.5" r="2.3"/><path d="M1.8 13.5c.4-2.6 2.1-4 4.2-4s3.8 1.4 4.2 4M10.5 3.5a2.3 2.3 0 010 4.2M12 9.7c1.4.5 2.2 1.7 2.4 3.8"/>');
export const idBadge = svg('<rect x="3" y="1.8" width="10" height="12.4" rx="1.4"/><circle cx="8" cy="6.5" r="1.6"/><path d="M5.4 11.3c.3-1.3 1.2-2 2.6-2s2.3.7 2.6 2"/>');
export const layoutDashboard = svg('<rect x="2" y="2" width="5" height="6" rx="1"/><rect x="9" y="2" width="5" height="3.5" rx="1"/><rect x="9" y="7.5" width="5" height="6.5" rx="1"/><rect x="2" y="10" width="5" height="4" rx="1"/>');
export const palette = svg('<path d="M8 1.8a6.2 6.2 0 100 12.4c1 0 1.5-.7 1.5-1.4 0-1-.9-1.2-.9-2 0-.8.6-1.3 1.4-1.3h1.6A2.2 2.2 0 0014.2 7.3C14.2 4.2 11.5 1.8 8 1.8z"/><circle cx="5" cy="7" r=".6" fill="currentColor"/><circle cx="7.5" cy="4.8" r=".6" fill="currentColor"/><circle cx="10.5" cy="5.2" r=".6" fill="currentColor"/>');
export const puzzle = svg('<path d="M6 2.5h2a1.2 1.2 0 012.4 0H13v3a1.2 1.2 0 010 2.4V13.5H9.5a1.2 1.2 0 00-2.4 0H2.5V9.5a1.2 1.2 0 000-2.4V2.5z"/>');
export const download = svg('<path d="M8 2v8M4.8 7.2L8 10.4l3.2-3.2M2.5 13.5h11"/>');
