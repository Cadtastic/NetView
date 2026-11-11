// inspection UI: the seven report sections and the "Open ports" column. Ports of LD 919-955 and 684-686, with commas
// where the old dashboard had middle dots. Everything in a report came from a device, so every value goes through esc().
// The module cannot import core files, so the shared helpers arrive as `ui.util` and are passed to makeHelpers.

const SHOWN_PORTS = 3; // the column lists the first three open ports
const LINK = /^https?:\/\//i; // the only URLs that become links; a javascript: or data: URL shows as text

/** Everything that needs the shared helpers (esc, fmtMs); all of it is pure and returns an HTML string. */
export function makeHelpers(util) {
  const { esc, fmtMs } = util;

  const heading = (section) => `<h3>${esc(section.title)}</h3>`;
  const dl = (rows) => `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;

  /** True for a URL that starts with http:// or https://. */
  const safeUrl = (u) => typeof u === "string" && LINK.test(u);

  /** One line about a TLS certificate (LD 919-922); "" when there is neither a certificate nor a TLS version. */
  function certLine(c, tls) {
    if (!c || c.subject == null) return tls ? `TLS ${tls}` : "";
    const org = c.subject_org ? ` (${c.subject_org})` : "";
    const parts = [`TLS ${tls || ""}`.trim(), `certificate ${c.subject || "(no name)"}${org}`, `issued by ${c.issuer_org || c.issuer || "?"}`];
    if (c.self_signed) parts.push("self-signed");
    parts.push(`expires ${c.not_after || "?"}`);
    if (c.san && c.san.length) parts.push(`also ${c.san.join(", ")}`);
    return parts.join(", ");
  }

  /** What an open port answered, as the "What answered" cell (LD 946-949). */
  function answered(o) {
    if (o.banner) return `<span class="mono">${esc(o.banner)}</span>`;
    if (o.skipped) return `<span class="detail">Open, not analyzed</span>`;
    const x = o.http;
    if (!x) return `<span class="detail">Open, but sends no greeting and doesn't speak HTTP</span>`;
    const bits = [`${String(x.scheme || "http").toUpperCase()}${x.status ? " " + x.status : " (TLS only, no HTTP reply)"}`];
    if (x.title) bits.push(`“${x.title}”`);
    if (x.server) bits.push(x.server);
    const cert = certLine(x.cert, x.tls);
    return esc(bits.join(", ")) + (x.cert ? `<div class="detail">${esc(cert)}</div>` : "");
  }

  /** "What it probably is": the hints list, or a note when nothing matched. */
  function summaryHtml(section) {
    const hints = (section.data && section.data.hints) || [];
    const body = hints.length ? `<ul class="hints">${hints.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="empty">No clear match.</p>`;
    return heading(section) + body;
  }

  /** "Identity": MAC, ping, names and NetBIOS as a key and value list (LD 926-933). */
  function identityHtml(section) {
    const d = section.data || {};
    const names = d.names || [];
    const rows = [
      ["MAC", esc(d.mac ? `${d.mac}${d.vendor ? ", " + d.vendor : ""}` : "unknown (not on this subnet?)")],
      ["Ping", esc(d.rtt_ms != null ? `${fmtMs(d.rtt_ms)} ms${d.ttl ? `, TTL ${d.ttl} (${d.os_hint || "?"})` : ""}` : "no reply")],
      ["Names", esc(names.length ? names.join(", ") : "none (reverse DNS, NetBIOS, mDNS and UPnP all silent)")],
    ];
    if (d.netbios) rows.push(["NetBIOS", esc(`${d.netbios.name}${d.netbios.workgroup ? ", workgroup " + d.netbios.workgroup : ""}`)]);
    return heading(section) + dl(rows);
  }

  /** "Web interfaces": a link per page (only for http and https URLs), then its details (LD 934-941). */
  function webHtml(section) {
    const items = (section.data && section.data.items) || [];
    const rows = items.map((w) => {
      const bits = [
        w.status ? `${w.status}${w.reason ? " " + w.reason : ""}` : "",
        w.title && `“${w.title}”`,
        w.server && `server: ${w.server}`,
        w.powered_by && `powered by ${w.powered_by}`,
        w.generator,
        w.realm && `login: ${w.realm}`,
        w.location && `redirects to ${w.location}`,
      ].filter(Boolean);
      const url = safeUrl(w.url)
        ? `<a href="${esc(w.url)}" target="_blank" rel="noopener noreferrer">${esc(w.url)}</a>`
        : `<span class="addr">${esc(w.url)}</span>`;
      const cert = w.cert ? `<span class="detail wide">${esc(certLine(w.cert, w.tls))}</span>` : "";
      return `<div class="weblink">${url}<span class="detail">${esc(bits.join(", "))}</span>${cert}</div>`;
    });
    return heading(section) + `<div class="weblinks">${rows.join("")}</div>`;
  }

  /** "Open TCP ports": the totals line, then a Port, Usually and What answered table (LD 942-951). */
  function portsHtml(section) {
    const d = section.data || {};
    const open = d.open || [];
    const first = `<p class="note">${esc(Number(d.scanned || 0).toLocaleString())} TCP ports in ${esc(d.duration_s)} s: ${open.length} open, ${esc(d.refused)} refused, ${esc(Number(d.no_answer || 0).toLocaleString())} no answer</p>`;
    if (!open.length) return heading(section) + first + `<p class="empty">None of the scanned ports are open.</p>`;
    const rows = open
      .map((o) => `<tr><td class="num">${esc(o.port)}</td><td>${esc(o.name || "–")}</td><td>${answered(o)}</td></tr>`)
      .join("");
    return (
      heading(section) +
      first +
      `<div class="tablewrap"><table><thead><tr><th class="num">Port</th><th>Usually</th><th>What answered</th></tr></thead><tbody>${rows}</tbody></table></div>`
    );
  }

  /** "mDNS and Bonjour": the host name and each service with its readable TXT keys (LD 952-953). */
  function mdnsHtml(section) {
    const d = section.data || {};
    const rows = [["Host name", esc(d.hostname || "–")]];
    for (const s of d.services || []) {
      const txt = Object.entries(s.txt || {})
        .map(([k, v]) => `${k}=${v}`)
        .join("  ");
      rows.push([s.type, esc((s.instances || []).join(", ") || "–") + (txt ? `<div class="detail">${esc(txt)}</div>` : "")]);
    }
    return heading(section) + dl(rows);
  }

  /** "UPnP and SSDP": each answer's friendly name, maker and model, with the server and description URL (LD 954). */
  function upnpHtml(section) {
    const entries = (section.data && section.data.entries) || [];
    const rows = entries.map((u) => {
      const what = [u.manufacturer, u.modelName, u.modelNumber, u.modelDescription].filter(Boolean).join(", ") || "–";
      const where = `${u.server || ""}${u.location ? ", " + u.location : ""}`;
      return [u.friendlyName || "Device", esc(what) + `<div class="detail">${esc(where)}</div>`];
    });
    return heading(section) + dl(rows);
  }

  /** "Discovery protocols": shown only when nothing answered. */
  function discoveryHtml(section) {
    return heading(section) + `<p class="empty">No answer to mDNS, UPnP/SSDP or NetBIOS.</p>`;
  }

  /** The "Open ports" cell (LD 684-686): "" when the device was never inspected. */
  function portsCell(ports) {
    if (!Array.isArray(ports)) return "";
    const label = (p) => p.port + (p.name ? " " + p.name : "");
    const title = esc(ports.map(label).join(", "));
    if (!ports.length) return `<div class="scope" title="${title}">no open ports found</div>`;
    const more = ports.length > SHOWN_PORTS ? ` +${ports.length - SHOWN_PORTS} more` : "";
    return `<div class="scope" title="${title}">open: ${esc(ports.slice(0, SHOWN_PORTS).map(label).join(", "))}${more}</div>`;
  }

  /** Sort key for the column: how many open ports were found, -1 when never inspected. */
  const portsCount = (ports) => (Array.isArray(ports) ? ports.length : -1);

  return { safeUrl, certLine, summaryHtml, identityHtml, webHtml, portsHtml, mdnsHtml, upnpHtml, discoveryHtml, portsCell, portsCount };
}

export default function register(ui) {
  const h = makeHelpers(ui.util);
  let openPorts = {};
  let loading = false;
  let lastState = null;

  function refresh() {
    if (loading) return;
    loading = true;
    ui.apiGet(`${ui.apiBase}/open-ports`)
      .then((p) => {
        openPorts = p && typeof p === "object" ? p : {};
      })
      .catch(() => {})
      .finally(() => {
        loading = false;
        ui.requestRender();
      });
  }
  refresh();

  // Refetch once per state update; the re-render requested above passes the same state object, so it starts no new fetch.
  function seen(state) {
    if (state !== lastState) {
      lastState = state;
      refresh();
    }
  }

  const renderers = {
    summary: h.summaryHtml,
    identity: h.identityHtml,
    web: h.webHtml,
    ports: h.portsHtml,
    mdns: h.mdnsHtml,
    upnp: h.upnpHtml,
    discovery: h.discoveryHtml,
  };
  for (const [section, html] of Object.entries(renderers)) {
    ui.slot("report.section", {
      section,
      draw(el, data) {
        el.innerHTML = html(data); // every value is escaped in the helper
      },
    });
  }

  ui.slot("devices.column", {
    id: "ports",
    label: "Open ports",
    render(d, state) {
      seen(state);
      return h.portsCell(openPorts[d.ip]);
    },
    sortKey(d, state) {
      seen(state);
      return h.portsCount(openPorts[d.ip]);
    },
  });
}
