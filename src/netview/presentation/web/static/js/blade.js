// Blade layout shared by the Admin page and the Settings dialog: a breadcrumb, a searchable side menu,
// a page with a command bar, and a child blade that slides in from the right.
// Nothing here touches the DOM until createBlade is called, so the pure helpers can be tested directly.

import { esc } from "./util.js";
import { chevronsLeft, chevronDown, close as closeIcon } from "./icons.js";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Menu entries whose label contains `query` (case-insensitive). Groups left empty are dropped. */
export function filterMenu(menu, query) {
  const q = String(query ?? "").trim().toLowerCase();
  if (!q) return menu;
  return menu
    .map((g) => ({ ...g, items: g.items.filter((i) => String(i.label).toLowerCase().includes(q)) }))
    .filter((g) => g.items.length);
}

/** HTML for the menu body (group headings and items). `collapsed` holds the names of folded groups. */
export function menuHtml(menu, activeId, collapsed = new Set()) {
  return menu
    .map((g) => {
      const folded = !!g.group && collapsed.has(g.group);
      const head = g.group
        ? `<button type="button" class="blade-gh" data-blade-group="${esc(g.group)}" aria-expanded="${folded ? "false" : "true"}">${chevronDown}<span>${esc(g.group)}</span></button>`
        : "";
      const items = folded
        ? ""
        : g.items
            .map((i) => {
              const on = i.id === activeId;
              const count = i.count != null ? `<span class="blade-n">${esc(i.count)}</span>` : "";
              return `<button type="button" class="blade-item${on ? " on" : ""}" data-blade-item="${esc(i.id)}" title="${esc(i.label)}"${on ? ' aria-current="page"' : ""}>${i.icon ?? ""}<span class="blade-label">${esc(i.label)}</span>${count}</button>`;
            })
            .join("");
      return head + items;
    })
    .join("");
}

/** Breadcrumb HTML: every part but the last is a link carrying its index. */
export function crumbHtml(parts) {
  return parts
    .map((p, i) => (i === parts.length - 1 ? `<b>${esc(p)}</b>` : `<a data-crumb="${i}">${esc(p)}</a>`))
    .join(" › ");
}

/** Page title, optional subtitle and an optional command bar. Commands are `{ id, label, icon }`. */
export function pageHeadHtml({ title, sub = "", commands = [] }) {
  const cmds = commands.length
    ? `<div class="blade-cmd">${commands.map((c) => `<button type="button" data-cmd="${esc(c.id)}">${c.icon ?? ""}<span>${esc(c.label)}</span></button>`).join("")}</div>`
    : "";
  return `<h1>${esc(title)}</h1>${sub ? `<p class="blade-sub">${esc(sub)}</p>` : ""}${cmds}`;
}

/** Whether a keydown inside the child blade should close just the child (Esc, with a child open). */
export function shouldCloseChild(key, childOpen) {
  return key === "Escape" && childOpen;
}

function readCollapsed(storageKey) {
  if (!storageKey) return new Set();
  try {
    const raw = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return new Set(Array.isArray(raw) ? raw.filter((x) => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function writeCollapsed(storageKey, set) {
  if (!storageKey) return;
  try {
    localStorage.setItem(storageKey, JSON.stringify([...set]));
  } catch {
    /* storage unavailable: the choice just isn't remembered */
  }
}

/**
 * Mount a blade layout into `root`.
 * `menu` is `[{ group?, items: [{ id, label, icon, count? }] }]`. `onSelect(id, pageEl, api, { push })` fills the page;
 * `push` is true for a user selection and false for the initial mount, so callers can pushState only on real navigation.
 * With `crumbHost` the breadcrumb renders there instead of above the blade.
 */
export function createBlade(root, { crumbRoot, menu, initial, onSelect, crumbHost = null, storageKey = null }) {
  let currentMenu = menu;
  let current = initial ?? menu.find((g) => g.items.length)?.items[0]?.id ?? null;
  let childTitle = null;
  let opener = null;
  let query = "";
  const collapsed = readCollapsed(storageKey);

  root.innerHTML = `${crumbHost ? "" : '<div class="blade-crumb"></div>'}
    <div class="blade-wrap">
      <nav class="blade-menu" aria-label="${esc(crumbRoot)} sections">
        <button type="button" class="blade-collapse" aria-label="Collapse menu" aria-expanded="true" title="Collapse menu">${chevronsLeft}</button>
        <input type="search" class="blade-search" placeholder="Search" aria-label="Search ${esc(crumbRoot)}">
        <div class="blade-items"></div>
      </nav>
      <section class="blade-page"></section>
      <aside class="blade-child" aria-hidden="true" aria-label="Details"></aside>
    </div>`;

  const crumbEl = crumbHost ?? root.querySelector(".blade-crumb");
  const wrap = root.querySelector(".blade-wrap");
  const items = root.querySelector(".blade-items");
  const search = root.querySelector(".blade-search");
  const collapseBtn = root.querySelector(".blade-collapse");
  const page = root.querySelector(".blade-page");
  const child = root.querySelector(".blade-child");

  const label = (id) => currentMenu.flatMap((g) => g.items).find((i) => i.id === id)?.label ?? String(id ?? "");

  function drawMenu() {
    const active = items.contains(document.activeElement) ? document.activeElement : null;
    const focusedGroup = active?.closest?.("[data-blade-group]")?.dataset.bladeGroup;
    const focusedItem = active?.closest?.("[data-blade-item]")?.dataset.bladeItem;
    items.innerHTML = menuHtml(filterMenu(currentMenu, query), current, query.trim() ? new Set() : collapsed);
    if (focusedGroup != null) {
      [...items.querySelectorAll("[data-blade-group]")].find((b) => b.dataset.bladeGroup === focusedGroup)?.focus();
    } else if (focusedItem != null) {
      [...items.querySelectorAll("[data-blade-item]")].find((b) => b.dataset.bladeItem === focusedItem)?.focus();
    }
  }

  function drawCrumb() {
    const parts = [crumbRoot, label(current)];
    if (childTitle != null) parts.push(childTitle);
    crumbEl.innerHTML = crumbHtml(parts);
  }

  /** Draw the menu and call `onSelect(id, page, api, { push })`. Menu clicks and `select(id)` push; the mount-time select does not. */
  function select(id, { push = true } = {}) {
    closeChild({ restoreFocus: false });
    current = id;
    drawMenu();
    drawCrumb();
    page.innerHTML = "";
    onSelect?.(id, page, api, { push });
  }

  function openChild({ title, body, foot, opener: from = null }) {
    opener = from;
    childTitle = title;
    child.innerHTML = `<div class="blade-ch-head"><h2>${esc(title)}</h2><button type="button" class="blade-x" data-blade-close aria-label="Close" title="Close">${closeIcon}</button></div>
      <div class="blade-ch-body"></div><div class="blade-ch-foot"></div>`;
    const closeIt = () => closeChild();
    body?.(child.querySelector(".blade-ch-body"));
    foot?.(child.querySelector(".blade-ch-foot"), closeIt);
    child.setAttribute("aria-hidden", "false");
    child.classList.add("open");
    drawCrumb();
    (child.querySelector(".blade-ch-body").querySelector(FOCUSABLE) ?? child.querySelector(FOCUSABLE))?.focus();
    return { close: closeIt };
  }

  function closeChild({ restoreFocus = true } = {}) {
    if (childTitle == null) return;
    childTitle = null;
    child.classList.remove("open");
    child.setAttribute("aria-hidden", "true");
    drawCrumb();
    const back = opener;
    opener = null;
    if (restoreFocus && back && typeof back.focus === "function") back.focus();
  }

  function setMenu(next) {
    currentMenu = next;
    drawMenu();
    drawCrumb();
  }

  const onItemsClick = (e) => {
    const g = e.target.closest("[data-blade-group]");
    if (g) {
      const name = g.dataset.bladeGroup;
      if (collapsed.has(name)) collapsed.delete(name);
      else collapsed.add(name);
      writeCollapsed(storageKey, collapsed);
      drawMenu();
      return;
    }
    const it = e.target.closest("[data-blade-item]");
    if (it) select(it.dataset.bladeItem);
  };
  const onSearch = () => {
    query = search.value;
    drawMenu();
  };
  const onCollapse = () => {
    const rail = wrap.classList.toggle("blade-rail");
    collapseBtn.setAttribute("aria-expanded", rail ? "false" : "true");
    collapseBtn.setAttribute("aria-label", rail ? "Expand menu" : "Collapse menu");
    collapseBtn.title = rail ? "Expand menu" : "Collapse menu";
  };
  const onChildClick = (e) => {
    if (e.target.closest("[data-blade-close]")) closeChild();
  };
  const onChildKey = (e) => {
    if (shouldCloseChild(e.key, childTitle != null)) {
      e.stopPropagation();
      e.preventDefault(); // a modal <dialog> would otherwise treat Esc as its own cancel request
      closeChild();
    }
  };
  const onCrumbClick = (e) => {
    const a = e.target.closest("[data-crumb]");
    if (a && a.dataset.crumb === "1") closeChild();
  };

  items.addEventListener("click", onItemsClick);
  search.addEventListener("input", onSearch);
  collapseBtn.addEventListener("click", onCollapse);
  child.addEventListener("click", onChildClick);
  child.addEventListener("keydown", onChildKey);
  crumbEl.addEventListener("click", onCrumbClick);

  function destroy() {
    crumbEl.removeEventListener("click", onCrumbClick);
    if (crumbHost) crumbHost.innerHTML = "";
    root.innerHTML = "";
  }

  const api = { select, openChild, closeChild, setMenu, destroy };
  select(current, { push: false });
  return api;
}
