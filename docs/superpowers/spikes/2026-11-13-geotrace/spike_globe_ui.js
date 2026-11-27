// Throwaway spike S2: load CesiumJS inside the NetView shell and log every CSP violation.
const violations = [];
document.addEventListener("securitypolicyviolation", (e) => {
  const v = { directive: e.violatedDirective, blocked: e.blockedURI, source: e.sourceFile, line: e.lineNumber, sample: e.sample };
  violations.push(v);
  console.warn("CSP-VIOLATION", JSON.stringify(v));
});
window.__spikeViolations = violations;

export default function register(ui) {
  const base = `/plugins/${ui.pluginId}/static/cesium/`;
  ui.slot("page", {
    id: "globe",
    title: "Spike Globe",
    mount(el) {
      el.innerHTML = `<div id="spike-globe" style="position:relative;height:calc(100vh - 120px);min-height:400px"></div><p id="spike-status">loading…</p>`;
      const status = el.querySelector("#spike-status");
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = base + "Widgets/widgets.css";
      document.head.appendChild(css);
      window.CESIUM_BASE_URL = base;
      const start = () => {
        try {
          const C = window.Cesium;
          window.CESIUM_WORKERS = undefined; // use Workers/*.js from our origin, not blob: workers
          C.Ion.defaultAccessToken = "";
          const viewer = new C.CesiumWidget("spike-globe", {
            baseLayer: C.ImageryLayer.fromProviderAsync(C.TileMapServiceImageryProvider.fromUrl(C.buildModuleUrl("Assets/Textures/NaturalEarthII"))),
          });
          const pts = [[-104.82, 38.83], [-104.99, 39.74], [-96.8, 32.78], [-118.24, 34.05]];
          viewer.entities.add({ polyline: { positions: C.Cartesian3.fromDegreesArray(pts.flat()), width: 4, material: C.Color.CYAN } });
          pts.forEach(([lon, lat]) => viewer.entities.add({ position: C.Cartesian3.fromDegrees(lon, lat), point: { pixelSize: 9, color: C.Color.WHITE } }));
          viewer.camera.flyTo({ destination: C.Cartesian3.fromDegrees(-108, 22, 3500000), duration: 1 });
          window.__spikeViewer = viewer;
          status.textContent = "viewer created";
        } catch (err) {
          status.textContent = "ERROR " + err;
          console.error("SPIKE-ERROR", err);
        }
      };
      if (window.Cesium) start();
      else {
        const s = document.createElement("script");
        s.src = base + "Cesium.js";
        s.onload = start;
        s.onerror = () => { status.textContent = "Cesium.js failed to load"; };
        document.head.appendChild(s);
      }
      return { destroy() { if (window.__spikeViewer) { window.__spikeViewer.destroy(); window.__spikeViewer = null; } } };
    },
  });
}
