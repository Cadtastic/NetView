// Loads CesiumJS once per page load from the plugin's own bundle route (NetView's CSP allows only same-origin scripts).
// CESIUM_BASE_URL has to exist before Cesium.js runs, so it is set here, in a module, and the script is added afterwards.
let loading = null;

function addTag(tag, attrs) {
  return new Promise((resolve, reject) => {
    const node = document.createElement(tag);
    Object.assign(node, attrs);
    node.onload = () => resolve(node);
    node.onerror = () => reject(new Error(`Could not load ${attrs.src || attrs.href}`));
    document.head.appendChild(node);
  });
}

/** Absolute URL (with trailing slash) of the Cesium bundle: `bundleBaseUrl` is status.bundle.base_url, relative to the plugin API. */
export function cesiumBaseUrl(pluginId, bundleBaseUrl) {
  const url = new URL(bundleBaseUrl, `${location.origin}/api/v1/plugins/${pluginId}/`).href;
  return url.endsWith("/") ? url : `${url}/`;
}

/** Resolves with the global `Cesium`. Later calls share the first load; a failed load can be tried again. */
export function loadCesium(pluginId, bundleBaseUrl) {
  if (window.Cesium) return Promise.resolve(window.Cesium);
  if (loading) return loading;
  const base = cesiumBaseUrl(pluginId, bundleBaseUrl);
  window.CESIUM_BASE_URL = base;
  loading = Promise.all([
    addTag("link", { rel: "stylesheet", href: `${base}Widgets/widgets.css` }),
    addTag("script", { src: `${base}Cesium.js` }),
  ])
    .then(() => {
      // Start module workers from Workers/*.js on our own origin; blob: workers are blocked by the CSP.
      window.CESIUM_WORKERS = undefined;
      return window.Cesium;
    })
    .catch((err) => {
      loading = null;
      throw err;
    });
  return loading;
}
