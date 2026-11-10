// Thin fetch and EventSource wrappers for the REST API.

export async function apiGet(path) {
  const r = await fetch(path, { cache: "no-store" });
  return parse(r);
}

/** Send JSON with the X-Netview header the server requires on every non-GET request. */
export async function apiSend(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-Netview": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parse(r);
}

/** Pull a readable message out of an error response body. */
export function errorMessage(body, fallback) {
  if (body && typeof body.error === "string") return body.error;
  if (body && typeof body.detail === "string") return body.detail;
  if (body && Array.isArray(body.detail)) return body.detail.map((d) => d.msg || String(d)).join("; ");
  return fallback;
}

async function parse(r) {
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const err = new Error(errorMessage(body, r.statusText || "HTTP " + r.status));
    err.status = r.status;
    throw err;
  }
  return body;
}

const POLL_AFTER_MS = 10000;
const RETRY_MS = 3000;

/**
 * Subscribe to the server-sent event stream, reconnecting when it drops.
 * While it has been down for more than 10 s, /api/v1/state is polled every 10 s instead.
 * onEvent receives {type: "open"} | {type: "state"} | {type: "domain", event} | {type: "poll", state} | {type: "down"}.
 * Returns {close()}.
 */
export function openStream(onEvent) {
  let source = null;
  let closed = false;
  let retryTimer = null;
  let pollTimer = null;
  let downTimer = null;

  const stopFallback = () => {
    clearTimeout(downTimer);
    clearInterval(pollTimer);
    downTimer = pollTimer = null;
  };
  const poll = async () => {
    try {
      onEvent({ type: "poll", state: await apiGet("/api/v1/state") });
    } catch (e) {
      /* still down; the next tick tries again */
    }
  };
  const connect = () => {
    if (closed) return;
    source = new EventSource("/api/v1/stream");
    source.onopen = () => {
      stopFallback();
      onEvent({ type: "open" });
    };
    source.addEventListener("domain", (e) => {
      let event = null;
      try {
        event = JSON.parse(e.data);
      } catch (err) {
        /* ignore a malformed frame */
      }
      onEvent({ type: "domain", event });
    });
    source.addEventListener("state", () => onEvent({ type: "state" }));
    source.onerror = () => {
      source.close();
      onEvent({ type: "down" });
      if (!downTimer && !pollTimer) {
        downTimer = setTimeout(() => {
          poll();
          pollTimer = setInterval(poll, POLL_AFTER_MS);
        }, POLL_AFTER_MS);
      }
      clearTimeout(retryTimer);
      retryTimer = setTimeout(connect, RETRY_MS);
    };
  };
  connect();
  return {
    close() {
      closed = true;
      if (source) source.close();
      clearTimeout(retryTimer);
      stopFallback();
    },
  };
}
