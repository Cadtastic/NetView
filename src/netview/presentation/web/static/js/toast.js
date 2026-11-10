// Toasts. A modal <dialog> sits in the top layer above the page, so while one is open the toast goes inside it.
import * as icons from "./icons.js";

const SHOW_MS = 4000;

/** Show a short message. kind is "ok" (default), "warn" or "bad". */
export function toast(message, kind = "ok") {
  const host = document.querySelector("dialog[open]") || document.body;
  let box = host.querySelector(":scope > .toasts");
  if (!box) {
    box = document.createElement("div");
    box.className = "toasts";
    box.setAttribute("role", "status");
    host.appendChild(box);
  }
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  const icon = document.createElement("span");
  icon.innerHTML = kind === "ok" ? icons.check : icons.alert; // fixed strings from icons.js
  const text = document.createElement("span");
  text.textContent = message;
  el.append(icon, text);
  box.appendChild(el);
  setTimeout(() => {
    el.remove();
    if (!box.children.length) box.remove();
  }, SHOW_MS);
}
