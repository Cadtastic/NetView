// A small modal for the Admin page: a title, a body the caller fills, and a footer the caller fills.
import { esc } from "../../util.js";

/**
 * Open a modal dialog. `body(el)` and `foot(el, dlg)` fill the two panes. Returns {dlg, close}.
 * The dialog removes itself when closed; `returnFocus` gets focus back.
 */
export function openAdminDialog({ title, body, foot, returnFocus = null }) {
  const dlg = document.createElement("dialog");
  dlg.className = "dlg small admin-dlg";
  dlg.setAttribute("aria-labelledby", "adm-dlg-title");
  dlg.innerHTML = `<div class="dlg-head"><h2 id="adm-dlg-title">${esc(title)}</h2></div>
    <div class="dlg-pane"></div><div class="dlg-foot"></div>`;
  const close = () => {
    if (dlg.open) dlg.close();
  };
  dlg.addEventListener("close", () => {
    dlg.remove();
    if (returnFocus && returnFocus.isConnected) returnFocus.focus();
  });
  document.body.appendChild(dlg);
  body(dlg.querySelector(".dlg-pane"));
  foot(dlg.querySelector(".dlg-foot"), dlg);
  dlg.showModal();
  return { dlg, close };
}

/** Show the message (and any per-field messages) from a failed API call in `box`. */
export function showError(box, err) {
  const fields = err && err.fields ? Object.values(err.fields).join(" ") : "";
  box.textContent = fields || (err && err.message) || "Something went wrong";
}
