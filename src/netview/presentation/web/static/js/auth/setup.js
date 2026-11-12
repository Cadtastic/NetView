// The first-run setup page.
import { apiGet, apiSend } from "../api.js";
import { afterSignIn } from "../auth.js";

const form = document.getElementById("setup-form");
const msg = document.getElementById("setup-msg");
const button = document.getElementById("setup-submit");
const codeRow = document.getElementById("code-row");
const FIELDS = ["code", "username", "password", "confirm"];

function showErrors(errors) {
  for (const name of FIELDS) {
    const el = document.getElementById("err-" + name);
    if (el) el.textContent = errors[name] || "";
  }
}

apiGet("/api/v1/setup")
  .then((s) => {
    codeRow.hidden = !s.code_required;
    form.elements.code.required = !!s.code_required;
  })
  .catch(() => {});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msg.textContent = "";
  showErrors({});
  const password = form.elements.password.value;
  if (password !== form.elements.confirm.value) {
    showErrors({ confirm: "The passwords don't match" });
    return;
  }
  button.disabled = true;
  try {
    await apiSend("POST", "/api/v1/setup", {
      code: codeRow.hidden ? null : form.elements.code.value.trim(),
      username: form.elements.username.value,
      password,
    });
    location.href = afterSignIn(location.search, location.hash);
  } catch (err) {
    const fields = err.fields || {};
    const known = Object.fromEntries(Object.entries(fields).filter(([k]) => FIELDS.includes(k)));
    showErrors(known);
    if (!Object.keys(known).length) msg.textContent = err.message;
    button.disabled = false;
  }
});
