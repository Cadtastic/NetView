// GeoTrace API helpers: NetView's shared fetch wrappers pointed at this plugin's routes.
import { apiGet, apiSend } from "/static/js/api.js";

/** {gtGet(path), gtSend(method, path, body)}; `path` starts with "/" and is relative to /api/v1/plugins/<pluginId>. */
export function createGtApi(pluginId) {
  const base = `/api/v1/plugins/${pluginId}`;
  return {
    base,
    gtGet: (path) => apiGet(base + path),
    gtSend: (method, path, body) => apiSend(method, base + path, body),
  };
}
