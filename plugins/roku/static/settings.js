// Settings > Roku: scan control, the saved TV list as editable JSON, and the do-it-yourself scan scripts.
const POLL_MS = 1000;
const LIB_WIN = "python R:\\source\\scripts\\network-tools\\scripts\\find_rokus.py --out rokus.json";
const LIB_UNIX = "python3 find_rokus.py --out rokus.json";
const OPTIONS =
  "Options: --subnet 192.168.1.0/24 to scan another network, --timeout 2 for slow TVs, --no-sweep or --no-ssdp to skip one method, --out rokus.json to also write a file.";

/** One line about the last scan. `fmt` turns epoch milliseconds into a time of day. */
export function scanSummary(scan, fmt = (ms) => new Date(ms).toLocaleTimeString()) {
  if (!scan || !scan.finished_ms) return "No scan yet.";
  const both = scan.by_ssdp || 0;
  const only = Math.max(0, (scan.by_sweep || 0) - both);
  const secs = Number(scan.duration_s || 0).toFixed(1);
  return `Last scan ${fmt(scan.finished_ms)}: ${scan.found || 0} found (${both} by SSDP and address check, ${only} by address check only). Took ${secs} s.`;
}

/** The command that runs `script` from a terminal without saving a file. */
export function pasteWrapper(os, script) {
  return os === "win" ? `@'\n${script}\n'@ | python -` : `python3 - <<'EOF'\n${script}\nEOF`;
}

async function fetchText(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.text();
}

export function renderRokuSettings(body, { apiBase, apiGet, apiSend, util }, store) {
  const esc = util.esc;
  const fmt = (ms) => (util.fmtTime ? util.fmtTime(ms) : new Date(ms).toLocaleTimeString());
  let os = /Mac|Linux|X11/.test((typeof navigator !== "undefined" && navigator.platform) || "") ? "unix" : "win";
  let scripts = null; // {py, ps} once fetched

  body.innerHTML =
    `<div class="roku-settings">` +
    `<section class="roku-sect"><h4>Scan</h4>` +
    `<p class="sub" data-r="summary">No scan yet.</p>` +
    `<div class="formfoot"><button type="button" class="primary small" data-r="scan">Scan for TVs now</button>` +
    `<span class="err" role="status" aria-live="polite" data-r="scanmsg"></span></div></section>` +
    `<section class="roku-sect"><h4>Saved TVs</h4>` +
    `<p class="sub">Saving replaces the whole list with what is in the box; pasting a scan result from the script below merges it instead, adding new TVs and updating known ones by address or serial number. Scans never remove or rename a TV.</p>` +
    `<textarea class="roku-doc" data-r="doc" rows="12" spellcheck="false" aria-label="Saved TVs as JSON"></textarea>` +
    `<div class="formfoot"><button type="button" class="primary small" data-r="save">Save</button>` +
    `<button type="button" class="small quiet" data-r="revert">Revert</button>` +
    `<button type="button" class="small quiet" data-r="download">Download</button>` +
    `<span class="err" role="status" aria-live="polite" data-r="docmsg"></span></div></section>` +
    `<section class="roku-sect"><h4>Run the scan yourself</h4>` +
    `<p class="sub">If NetView cannot see the TVs' network, run the same scan on a computer that can.</p>` +
    `<div class="seg" role="group" aria-label="Operating system">` +
    `<button type="button" data-os="win">Windows</button><button type="button" data-os="unix">macOS / Linux</button></div>` +
    `<div data-r="cmds"></div>` +
    `<p class="note">Paste what it prints into Saved TVs above and press Save.</p></section></div>`;

  const q = (k) => body.querySelector(`[data-r=${k}]`);
  const scanBtn = q("scan");
  const doc = q("doc");
  const docMsg = q("docmsg");
  let docText = "";

  const showSummary = (scan) => {
    q("summary").textContent = scanSummary(scan, fmt);
  };
  if (store.get()) showSummary(store.get().scan);

  async function loadDoc() {
    try {
      docText = JSON.stringify(await apiGet(`${apiBase}/tvs/document`), null, 2);
      doc.value = docText;
    } catch (e) {
      docMsg.classList.remove("ok");
      docMsg.textContent = "⚠ " + (e && e.message ? e.message : "could not load the saved list");
    }
  }

  // ---- scan ----
  async function poll() {
    if (!body.isConnected) return;
    let s;
    try {
      s = await apiGet(`${apiBase}/scan`);
    } catch (e) {
      s = { running: false, error: e && e.message ? e.message : "failed" };
    }
    if (s.running) {
      setTimeout(poll, POLL_MS);
      return;
    }
    scanBtn.disabled = false;
    q("scanmsg").textContent = s.error ? "⚠ " + s.error : "";
    await store.load();
    if (!s.error) showSummary(s);
    await loadDoc();
  }
  scanBtn.addEventListener("click", async () => {
    scanBtn.disabled = true;
    q("scanmsg").textContent = "Scanning…";
    try {
      await apiSend("POST", `${apiBase}/scan`, {});
    } catch (e) {
      // 409: a scan is already running; polling picks it up
      if (!/already/i.test(e && e.message ? e.message : "")) {
        scanBtn.disabled = false;
        q("scanmsg").textContent = "⚠ " + (e && e.message ? e.message : "failed");
        return;
      }
    }
    setTimeout(poll, POLL_MS);
  });

  // ---- saved list ----
  q("save").addEventListener("click", async () => {
    docMsg.classList.remove("ok");
    docMsg.textContent = "Saving…";
    try {
      const r = await apiSend("PUT", `${apiBase}/tvs/document`, { text: doc.value });
      docMsg.classList.add("ok");
      docMsg.textContent = "✓ " + ((r && r.message) || "Saved");
      await store.load();
      await loadDoc();
    } catch (e) {
      docMsg.textContent = "⚠ " + (e && e.message ? e.message : "failed");
    }
  });
  q("revert").addEventListener("click", () => {
    doc.value = docText;
    docMsg.classList.remove("ok");
    docMsg.textContent = "";
  });
  q("download").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([doc.value], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "tvs.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  // ---- manual scan ----
  function block(id, text) {
    return (
      `<div class="roku-code"><pre data-code="${id}">${esc(text)}</pre>` +
      `<button type="button" class="small" data-copy="${id}">Copy</button></div>`
    );
  }
  async function copy(btn) {
    const text = q("cmds").querySelector(`[data-code=${btn.dataset.copy}]`).textContent;
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied";
    } catch (e) {
      btn.textContent = "Copy failed";
    }
    setTimeout(() => {
      btn.textContent = "Copy";
    }, 1500);
  }
  function drawCmds() {
    for (const b of body.querySelectorAll("[data-os]")) b.classList.toggle("on", b.dataset.os === os);
    const lib = os === "win" ? LIB_WIN : LIB_UNIX;
    const wrapper = scripts ? pasteWrapper(os, scripts.py) : "Loading…";
    q("cmds").innerHTML =
      `<p class="sub">With the script saved on disk:</p>${block("lib", lib)}` +
      `<p class="sub">${esc(OPTIONS)}</p>` +
      `<p class="sub">Or paste the whole script into a terminal (nothing is saved):</p>${block("paste", wrapper)}` +
      `<details><summary>PowerShell only (no Python needed)</summary>${block("ps", scripts ? scripts.ps : "Loading…")}</details>`;
    for (const b of q("cmds").querySelectorAll("[data-copy]")) b.addEventListener("click", () => copy(b));
  }
  for (const b of body.querySelectorAll("[data-os]")) {
    b.addEventListener("click", () => {
      os = b.dataset.os;
      drawCmds();
    });
  }
  drawCmds();
  Promise.all([
    fetchText(`${apiBase}/scripts/find_rokus.py`),
    fetchText(`${apiBase}/scripts/find_rokus.ps1`),
  ])
    .then(([py, ps]) => {
      scripts = { py: py.trim(), ps: ps.trim() };
    })
    .catch(() => {
      scripts = { py: "(could not load the script)", ps: "(could not load the script)" };
    })
    .then(drawCmds);

  loadDoc();
  const unsub = store.subscribe(() => {
    if (!body.isConnected) return unsub();
    if (store.get()) showSummary(store.get().scan);
  });
}
