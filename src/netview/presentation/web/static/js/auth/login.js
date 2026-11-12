// The sign-in page.
import { apiSend } from "../api.js";
import { safeNext } from "../auth.js";

const form = document.getElementById("login-form");
const msg = document.getElementById("login-msg");
const button = document.getElementById("login-submit");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msg.textContent = "";
  button.disabled = true;
  try {
    await apiSend("POST", "/api/v1/auth/login", {
      username: form.elements.username.value,
      password: form.elements.password.value,
    });
    location.href = safeNext(new URLSearchParams(location.search).get("next"));
  } catch (err) {
    msg.textContent = err.message;
    form.elements.password.value = "";
    button.disabled = false;
  }
});
