// The Commands view: the ECP cheat sheet with every command filled in for the selected TV.
// Free of browser-only imports so the node tests can load it; the toast helper is passed in.
import { esc } from "./html.js";
import { READ, CONTROL, KEYS, APPS, RECIPES, ACCESS_MODES, RESPONSES } from "./cheatsheet-data.js";

export const SHELLS = [
  ["ps", "PowerShell", "Windows PowerShell 5.1 and PowerShell 7"],
  ["cmd", "Command Prompt", "Windows Command Prompt (uses the curl built into Windows 10 and 11)"],
  ["curl", "macOS / Linux", "bash or zsh on macOS and Linux"],
];
export const COPY_BLOCKED = "Copy is blocked here. The command is selected; press Ctrl+C.";
export const LIMITED_403 = "This TV's Network access setting is Limited, so every POST command below returns 403. Reads of device-info and active-app still work.";

/** Default shell for a browser platform string: PowerShell on Windows, curl elsewhere. */
export function defaultShell(platform) {
  return /win/i.test(platform || "") ? "ps" : "curl";
}

/** One command for a request, exactly as the cheat sheet builds it. out names an output file for a GET. */
export function buildCommand(shell, method, url, out) {
  if (shell === "curl" || shell === "cmd") {
    // Command Prompt runs the curl.exe built into Windows 10 and 11; same syntax as on macOS and Linux.
    if (method === "POST") return `curl -X POST "${url}"`;
    return out ? `curl -o ${out} "${url}"` : `curl "${url}"`;
  }
  // -UseBasicParsing keeps Windows PowerShell 5.1 from needing Internet Explorer's engine; PowerShell 7 ignores it.
  if (method === "POST") return `(Invoke-WebRequest "${url}" -Method Post -UseBasicParsing).StatusCode`;
  return out
    ? `Invoke-WebRequest "${url}" -OutFile ${out} -UseBasicParsing`
    : `(Invoke-WebRequest "${url}" -UseBasicParsing).Content`;
}

/** Prints the text of one XML element from a GET, in each shell. */
export function readField(shell, url, tag) {
  if (shell === "curl") return `curl -s "${url}" | grep -o "<${tag}[ >][^<]*" | sed "s/.*>//"`;
  if (shell === "cmd") return `curl -s "${url}" | findstr /c:"<${tag}"`;
  return `(Select-Xml -Content (Invoke-WebRequest "${url}" -UseBasicParsing).Content -XPath "//${tag}").Node.InnerText`;
}

function encChar(ch) {
  return encodeURIComponent(ch).replace(/[!'()*~]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());
}

/** The type-text command: one Lit_ keypress per character. base is http://ip:8060. */
export function buildTypeText(shell, base, text) {
  if (!text) return shell === "cmd" ? "rem Enter some text above" : "# Enter some text above";
  if (shell === "curl") {
    const parts = Array.from(text).map(encChar).join(" ");
    return `for c in ${parts}; do\n  curl -s -X POST "${base}/keypress/Lit_$c"\ndone`;
  }
  if (shell === "cmd") {
    return Array.from(text).map((ch) => `curl -s -X POST "${base}/keypress/Lit_${encChar(ch)}"`).join("\n");
  }
  return `'${text.replace(/'/g, "''")}'.ToCharArray() | ForEach-Object {\n  Invoke-WebRequest "${base}/keypress/Lit_$([uri]::EscapeDataString($_))" -Method Post -UseBasicParsing | Out-Null\n}`;
}

function patternHtml(p) {
  return p
    .split(/(\{[^}]+\})/)
    .filter(Boolean)
    .map((part) => (/^\{/.test(part) ? `<span class="ph">${esc(part)}</span>` : esc(part)))
    .join("");
}

const cmdBox = (code, tag = "code") =>
  `<div class="cmd"><${tag} data-cmd>${esc(code)}</${tag}><button type="button" class="small" data-copy>Copy</button></div>`;

function selectNode(node) {
  try {
    const r = document.createRange();
    r.selectNodeContents(node);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  } catch (e) {
    // nothing to select with
  }
}

/** The TV's installed apps as [name, id] pairs when it listed them, else the common list. */
export function appRows(tv) {
  const apps = tv.status && tv.status.apps;
  if (Array.isArray(apps) && apps.length) {
    return { known: true, rows: apps.filter((a) => a.type !== "tvin").map((a) => [String(a.name), String(a.id)]) };
  }
  return { known: false, rows: APPS };
}

/**
 * Draw the Commands view for one TV into el.
 * opts: {shell, onShell(shell), toast(message, kind), state?: {key, text}} (state survives redraws).
 * Returns {destroy()}.
 */
export function renderCommands(el, tv, opts = {}) {
  const shell = SHELLS.some((s) => s[0] === opts.shell) ? opts.shell : "curl";
  const toast = opts.toast || (() => {});
  const state = opts.state || { key: "Home", text: "star trek" };
  if (!state.key) state.key = "Home";
  if (state.text == null) state.text = "star trek";
  const base = `http://${tv.ip}:8060`;
  const build = (m, path, out) => buildCommand(shell, m, base + path, out);
  const limited = String((tv.status && tv.status.mode) || "").toLowerCase() === "limited";
  const isTv = tv.tv !== false;
  const tvTag = '<span class="tag plain">Roku TV</span>';
  const apps = appRows(tv);

  const row = (r) => `<div class="row">
      <span class="rk-badge ${r.m.toLowerCase()}">${r.m}</span>
      <div class="body">
        <div class="ep">${patternHtml(r.p)}${r.ok ? '<span class="tag works">Works in Limited</span>' : ""}${r.blocked ? '<span class="tag blocked">403 in Limited</span>' : ""}${r.tv ? tvTag : ""}</div>
        <div class="desc">${esc(r.d)}</div>
        ${cmdBox(build(r.m, r.ex || r.p, r.out))}
      </div></div>`;
  const show = (r) => isTv || !r.tv;

  const recipes = RECIPES.map((r) => {
    const code = r.read ? readField(shell, base + r.read[0], r.read[1]) : build(r.m, r.p);
    return `<div class="recipe"><div class="name">${esc(r.t)}</div>${cmdBox(code)}</div>`;
  }).join("");

  const keyGroups = KEYS.filter(show)
    .map(
      (g) => `<div class="kgroup"><h3>${esc(g.g)}${g.tv ? tvTag : ""}</h3><div class="rk-chips">${g.k
        .map((k) => `<button type="button" class="rk-chip" data-key="${esc(k)}" aria-pressed="${k === state.key}">${esc(k)}</button>`)
        .join("")}</div>${g.n ? `<div class="note">${esc(g.n)}</div>` : ""}</div>`,
    )
    .join("");

  const appBody = apps.rows
    .map(
      ([name, id], i) => `<tr><td>${esc(name)}</td><td class="num">${esc(id)}</td><td><button type="button" class="small" data-launch="${i}">Copy launch command</button><code class="launch-cmd" data-launch-cmd="${i}" hidden>${esc(build("POST", "/launch/" + id))}</code></td></tr>`,
    )
    .join("");

  const access = ACCESS_MODES.map(
    (m) => `<tr><td><b>${esc(m.name)}</b></td><td class="${m.reads[0]}">${esc(m.reads[1])}</td><td class="${m.posts[0]}">${esc(m.posts[1])}</td><td>${esc(m.who)}</td></tr>`,
  ).join("");
  const responses = RESPONSES.map(
    ([code, head, body]) => `<div class="code-row"><b>${esc(code)}</b><span><strong>${esc(head)}</strong> ${esc(body)}</span></div>`,
  ).join("");

  const sec = (id, title, intro, body) =>
    `<section class="card" id="rk-${id}"><div class="card-head"><h2>${esc(title)}</h2></div>${intro ? `<p class="note">${intro}</p>` : ""}${body}</section>`;

  el.innerHTML = `<div class="rk-cmds">${limited ? `<div class="callout" data-limited><b>POST commands return 403.</b> ${esc(LIMITED_403)}</div>` : ""}
    <div class="cmdbar card">
      <span class="lbl">Commands for</span>
      <div class="seg" role="group" aria-label="Commands for">${SHELLS.map(
        ([id, label, tip]) => `<button type="button" data-shell="${id}" class="${id === shell ? "on" : ""}" aria-pressed="${id === shell}" title="${esc(tip)}">${esc(label)}</button>`,
      ).join("")}</div>
      <span class="target">Every command targets <b>${esc(tv.title)}</b> at <b>${esc(tv.ip)}:8060</b></span>
      <nav class="jump" aria-label="Sections"><a href="#rk-recipes" data-jump="recipes">Recipes</a><a href="#rk-read" data-jump="read">Read state</a><a href="#rk-control" data-jump="control">Control</a><a href="#rk-keys" data-jump="keys">Remote keys</a><a href="#rk-apps" data-jump="apps">App IDs</a><a href="#rk-access" data-jump="access">Network access</a><a href="#rk-errors" data-jump="errors">Responses</a></nav>
    </div>
    ${sec("recipes", "Recipes", "The things you'll run most often.", `<div class="recipes">${recipes}</div>`)}
    ${sec("read", "Read state", "GET requests return XML and change nothing on the TV. Tags show which reads a Roku TV in Limited mode allowed in testing.", `<div class="rows">${READ.filter(show).map(row).join("")}</div>`)}
    ${sec("control", "Control", "POST requests with an empty body. A GET to any of these returns 404. In Limited mode every one returns 403.", `<div class="rows">${CONTROL.filter(show).map(row).join("")}</div>`)}
    ${sec(
      "keys",
      "Remote keys",
      "Use with <code>/keypress/</code>, <code>/keydown/</code> and <code>/keyup/</code>. Key names are case-sensitive. Click a key to show its keypress command.",
      `<div class="preview">${cmdBox(build("POST", "/keypress/" + state.key))}</div>
       <div class="kgroups">${keyGroups}</div>
       <div class="typer"><label for="rk-type-text">Type text into a search box</label>
         <input id="rk-type-text" data-type-text value="${esc(state.text)}" spellcheck="false" autocomplete="off">
         <div class="note">Sends one <code>Lit_</code> keypress per character, URL-encoded. Open the app's search box first.</div>
         ${cmdBox(buildTypeText(shell, base, state.text), "pre")}</div>`,
    )}
    ${sec(
      "apps",
      apps.known ? "App IDs on this TV" : "Common app IDs",
      apps.known
        ? "The channels installed on this TV, from <code>/query/apps</code>."
        : "Channel IDs are the same on every Roku. To confirm, or to find others, run <code>/query/apps</code> once Network access allows it.",
      `<div class="tablewrap"><table><thead><tr><th scope="col">Channel</th><th scope="col">ID</th><th scope="col">Launch</th></tr></thead><tbody>${appBody}</tbody></table></div>`,
    )}
    ${sec(
      "access",
      "Network access settings",
      "Set on the TV under Settings → System → Advanced system settings → Control by mobile apps → Network access. There is no token or pairing; this setting is the only access control.",
      `<div class="tablewrap"><table><thead><tr><th scope="col">Setting</th><th scope="col">Reads (GET)</th><th scope="col">Commands (POST)</th><th scope="col">Who can connect</th></tr></thead><tbody>${access}</tbody></table></div>`,
    )}
    ${sec("errors", "What the responses mean", "", `<div class="codes">${responses}</div>`)}</div>`;

  function clipboardWrite(text) {
    return navigator.clipboard && navigator.clipboard.writeText
      ? navigator.clipboard.writeText(text)
      : Promise.reject(new Error("no clipboard"));
  }
  /** Copy node's text; on failure select it (and show it if it was hidden) and say how to copy by hand. */
  function copyFrom(node) {
    clipboardWrite(node.textContent).then(
      () => toast("Copied"),
      () => {
        node.hidden = false;
        selectNode(node);
        toast(COPY_BLOCKED);
      },
    );
  }
  function updateKeyPreview() {
    // Only the key preview changes on a key click; update it in place so the page doesn't jump.
    const box = el.querySelector(".preview [data-cmd]");
    if (box) box.textContent = build("POST", "/keypress/" + state.key);
    for (const c of el.querySelectorAll(".rk-chip")) c.setAttribute("aria-pressed", String(c.dataset.key === state.key));
  }

  const onClick = (e) => {
    const t = e.target;
    if (!t || !t.closest) return;
    const sh = t.closest("[data-shell]");
    if (sh) {
      if (sh.dataset.shell !== shell && opts.onShell) opts.onShell(sh.dataset.shell);
      return;
    }
    const jump = t.closest("[data-jump]");
    if (jump) {
      e.preventDefault();
      const target = el.querySelector(`#rk-${jump.dataset.jump}`);
      if (target && target.scrollIntoView) target.scrollIntoView({ block: "start" });
      return;
    }
    const chip = t.closest(".rk-chip");
    if (chip) {
      state.key = chip.dataset.key;
      updateKeyPreview();
      const node = el.querySelector(".preview [data-cmd]");
      if (node) copyFrom(node);
      return;
    }
    const launch = t.closest("[data-launch]");
    if (launch) {
      const node = el.querySelector(`[data-launch-cmd="${launch.dataset.launch}"]`);
      if (node) copyFrom(node);
      return;
    }
    const copy = t.closest("[data-copy]");
    if (copy) {
      const node = copy.parentElement && copy.parentElement.querySelector("[data-cmd]");
      if (node) copyFrom(node);
    }
  };
  const onInput = (e) => {
    if (!(e.target.matches && e.target.matches("[data-type-text]"))) return;
    state.text = e.target.value;
    const out = e.target.parentElement.querySelector("[data-cmd]");
    if (out) out.textContent = buildTypeText(shell, base, state.text);
  };
  el.addEventListener("click", onClick);
  el.addEventListener("input", onInput);
  return {
    busy: () => false,
    tick() {},
    destroy() {
      el.removeEventListener("click", onClick);
      el.removeEventListener("input", onInput);
    },
  };
}
