// The GeoTrace globe: a CesiumWidget (never Cesium.Viewer, whose UI needs `new Function`) with route arcs, hop labels,
// a moving packet, a satellite bounce for Starlink, and a street map that fades in as the camera comes down.
//
// From a blade:  import { globeControl } from "./globe.js";
//   globeControl.showTrace(trace, {style: "solid" | "dashed", color: "var(--accent)"});  globeControl.flyToHop(hop);
// Calls made before the globe exists (the bundle is still downloading) are replayed once it does.
import { loadCesium } from "./cesium-base.js";
import { arcPoints, routePoints, streetAlpha, fitView, STARLINK_ALTITUDE_M, STARLINK_ASN, STREET_MAX_ALPHA } from "./geometry.js";
import { shell } from "./shell.js";

export const DB_IP_TEXT = "IP geolocation by DB-IP";
export const DB_IP_HREF = "https://db-ip.com";
const OSM_CREDIT = "© OpenStreetMap contributors";
const EOX_CREDIT = "Sentinel-2 cloudless – https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2020)";
const NE_CREDIT = "Natural Earth";
const ASSUMED_NOTE = "placed at the ground station";
const IMPLAUSIBLE_NOTE = "location from the database doesn't fit the response time";

const placed = (h) => h != null && Number.isFinite(h.lat) && Number.isFinite(h.lon);

function fmtAltitude(m) {
  if (m > 10000) return `${Math.round(m / 1000).toLocaleString()} km`;
  if (m > 1000) return `${(m / 1000).toFixed(1)} km`;
  return `${Math.round(m)} m`;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** Turns a theme token ("--ok", "var(--ok)") or any CSS colour into a Cesium colour. No colour literals live in this file. */
function colourResolver(Cesium, host) {
  const style = getComputedStyle(host);
  const probe = document.createElement("canvas").getContext("2d");
  return (value, fallback = Cesium.Color.WHITE) => {
    let css = String(value || "").trim();
    const token = /^var\(\s*(--[\w-]+)\s*\)$/.exec(css) || /^(--[\w-]+)$/.exec(css);
    if (token) css = style.getPropertyValue(token[1]).trim();
    if (!css || !probe) return fallback;
    probe.fillStyle = css; // the canvas turns hsl(), rgb() and names into one form Cesium can read
    return Cesium.Color.fromCssColorString(probe.fillStyle) || fallback;
  };
}

function hopLabel(hop) {
  const place = [hop.city, hop.region].filter(Boolean).join(", ") || hop.country || hop.ip || "";
  const rtts = (hop.rtts_ms || []).filter(Number.isFinite);
  const head = `${hop.n}  ${place}${rtts.length ? `  ·  ${Math.round(Math.min(...rtts))} ms` : ""}`;
  const notes = [];
  if (hop.placement === "assumed") notes.push(ASSUMED_NOTE);
  if (hop.plausible === false) notes.push(IMPLAUSIBLE_NOTE);
  return notes.length ? `${head}\n${notes.join("\n")}` : head;
}

/**
 * createGlobe(host, {Cesium, tilesUrl, settings}) -> {showTrace, clear, flyToHop, fitRoute, flyAlong, setBase, destroy}.
 * tilesUrl is the plugin's "/api/v1/plugins/<id>/tiles/"; Cesium itself was already loaded from the bundle.
 * settings: {base_imagery: "natural_earth" | "eox_s2", tile_source: "osm" | "custom"}.
 */
export function createGlobe(host, { Cesium = window.Cesium, tilesUrl, settings = {} } = {}) {
  Cesium.Ion.defaultAccessToken = "";
  const colour = colourResolver(Cesium, host);
  const fonts = getComputedStyle(host).getPropertyValue("--font-text").trim() || "sans-serif";
  const palette = {
    home: colour("--ok"),
    dest: colour("--bad"),
    route: colour("--accent"),
    text: colour("--text"),
    surface: colour("--surface"),
  };
  const labelBg = palette.surface.withAlpha(0.8);

  const stage = el("div", "gt-globe-stage");
  const hud = el("div", "gt-globe-hud");
  const altitude = el("span", "gt-globe-alt", "–");
  const meterBar = el("i");
  const meter = el("div", "gt-globe-meter");
  meter.appendChild(meterBar);
  const meterText = el("span", "gt-globe-blend", "Street map 0%");
  hud.append(altitude, meter, meterText);
  const credits = el("div", "gt-credits");
  const tileCredit = el("span", "gt-credit-tiles");
  const cesiumCredit = el("span", "gt-credit-cesium");
  const dbip = el("a", "gt-credit-dbip", DB_IP_TEXT);
  dbip.href = DB_IP_HREF;
  dbip.target = "_blank";
  dbip.rel = "noopener noreferrer";
  credits.append(tileCredit, dbip, cesiumCredit);
  host.append(stage, hud, credits);

  const widget = new Cesium.CesiumWidget(stage, {
    baseLayer: Cesium.ImageryLayer.fromProviderAsync(
      Cesium.TileMapServiceImageryProvider.fromUrl(Cesium.buildModuleUrl("Assets/Textures/NaturalEarthII")),
    ),
    creditContainer: cesiumCredit,
  });
  const { scene, camera } = widget;
  const layers = scene.imageryLayers;
  const naturalEarth = layers.get(0);

  const template = (source) => `${tilesUrl}${source}/{z}/{x}/{y}`;
  const satellite = layers.addImageryProvider(
    new Cesium.UrlTemplateImageryProvider({ url: template("eox-s2"), maximumLevel: 14 }),
  );
  const streetSource = settings.tile_source === "custom" ? "custom" : "osm";
  const street = layers.addImageryProvider(
    new Cesium.UrlTemplateImageryProvider({ url: template(streetSource), maximumLevel: 19 }),
  );
  street.alpha = 0;
  street.show = false;

  let base = "natural_earth";
  let lastCredit = "";
  function setBase(kind) {
    base = kind === "eox_s2" ? "eox_s2" : "natural_earth";
    satellite.show = base === "eox_s2";
    naturalEarth.show = base === "natural_earth";
    lastCredit = "";
  }
  setBase(settings.base_imagery);

  // --- traces ---
  const traces = new Map(); // id -> {entities, hops}
  let primary = null;
  const add = (spec) => widget.entities.add(spec);

  function clear(id) {
    const ids = id === undefined ? [...traces.keys()] : [id];
    for (const key of ids) {
      const t = traces.get(key);
      if (!t) continue;
      t.entities.forEach((e) => widget.entities.remove(e));
      traces.delete(key);
      if (primary === key) primary = null;
    }
  }

  function showTrace(trace, { style = "solid", color } = {}) {
    clear(trace.id);
    const hops = trace.hops || [];
    const stops = hops.filter(placed);
    const tint = color ? colour(color, palette.route) : palette.route;
    const solid = style !== "dashed";
    const starlink = hops.some((h) => h.asn === STARLINK_ASN);
    const entities = [];

    for (let i = 0; i < stops.length - 1; i++) {
      const dashed = !solid || stops[i].plausible === false || stops[i + 1].plausible === false;
      const lift = i === 0 && starlink ? { liftM: STARLINK_ALTITUDE_M, steps: 40 } : {};
      const flat = arcPoints(stops[i], stops[i + 1], lift).flatMap((p) => [p.lon, p.lat, p.h]);
      entities.push(
        add({
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArrayHeights(flat),
            width: solid ? 4 : 3,
            arcType: Cesium.ArcType.NONE,
            material: dashed
              ? new Cesium.PolylineDashMaterialProperty({ color: tint, dashLength: 14 })
              : new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.18, color: tint }),
          },
        }),
      );
    }

    stops.forEach((hop, i) => {
      const home = hop.placement === "home";
      const dest = i === stops.length - 1 && stops.length > 1;
      const fill = home ? palette.home : dest ? palette.dest : tint;
      const hollow = hop.plausible === false;
      entities.push(
        add({
          position: Cesium.Cartesian3.fromDegrees(hop.lon, hop.lat, 0),
          point: {
            pixelSize: home || dest ? 12 : 8,
            color: hollow ? fill.withAlpha(0) : fill,
            outlineColor: hollow ? fill : palette.surface,
            outlineWidth: hollow ? 3 : 2,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: solid
            ? {
                text: hopLabel(hop),
                font: `12px ${fonts}`,
                fillColor: palette.text,
                showBackground: true,
                backgroundColor: labelBg,
                backgroundPadding: new Cesium.Cartesian2(6, 4),
                pixelOffset: new Cesium.Cartesian2(0, -20),
                disableDepthTestDistance: Number.POSITIVE_INFINITY,
                translucencyByDistance: new Cesium.NearFarScalar(4e6, 1, 1.2e7, 0),
              }
            : undefined,
        }),
      );
    });

    if (solid && starlink && stops.length > 1) {
      const mid = arcPoints(stops[0], stops[1], { liftM: STARLINK_ALTITUDE_M, steps: 2 })[1];
      entities.push(
        add({
          position: Cesium.Cartesian3.fromDegrees(mid.lon, mid.lat, mid.h),
          point: { pixelSize: 7, color: palette.text, outlineColor: tint, outlineWidth: 2 },
          label: {
            text: "Starlink satellite ~550 km",
            font: `11px ${fonts}`,
            fillColor: palette.text,
            showBackground: true,
            backgroundColor: labelBg,
            pixelOffset: new Cesium.Cartesian2(0, -16),
            translucencyByDistance: new Cesium.NearFarScalar(1e6, 1, 6e6, 0),
          },
        }),
      );
    }

    if (solid && stops.length > 1) {
      const path = routePoints(hops, { starlink }).map((p) => Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.h));
      entities.push(
        add({
          position: new Cesium.CallbackProperty(() => path[Math.floor((Date.now() / 18) % path.length)], false),
          point: {
            pixelSize: 7,
            color: palette.text,
            outlineColor: tint.withAlpha(0.6),
            outlineWidth: 6,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        }),
      );
    }

    traces.set(trace.id, { entities, hops: stops });
    if (solid) primary = trace.id;
  }

  // --- camera ---
  let flightToken = 0;
  const flyTo = (options) => new Promise((resolve) => camera.flyTo({ ...options, complete: resolve, cancel: resolve }));

  function flyToHop(hop) {
    if (!placed(hop)) return;
    camera.cancelFlight();
    flightToken++;
    camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(hop.lon, hop.lat - 0.09, 9000),
      duration: 3,
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-48), roll: 0 },
    });
  }

  // Degrees of longitude to move the camera so the route sits in the part of the page the blades do not cover.
  function bladeShiftDeg(target) {
    try {
      const blades = host.parentElement && host.parentElement.querySelector(".gt-blades");
      const right = blades ? blades.getBoundingClientRect().right - host.getBoundingClientRect().left : 0;
      if (right <= 0 || !host.clientWidth) return 0;
      const width = 2 * target.heightM * Math.tan(camera.frustum.fovy / 2) * camera.frustum.aspectRatio;
      const metres = (right / 2 / host.clientWidth) * width;
      return metres / (111320 * Math.max(0.2, Math.cos((target.lat * Math.PI) / 180)));
    } catch {
      return 0;
    }
  }

  function fitRoute(duration = 3) {
    const target = fitView([...traces.values()].flatMap((t) => t.hops));
    camera.cancelFlight();
    flightToken++;
    camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(target.lon - bladeShiftDeg(target), target.lat, target.heightM),
      duration,
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
    });
  }

  async function flyAlong() {
    const trace = traces.get(primary);
    if (!trace) return;
    camera.cancelFlight();
    const token = ++flightToken;
    for (const hop of trace.hops) {
      await flyTo({
        destination: Cesium.Cartesian3.fromDegrees(hop.lon, hop.lat - 0.6, 160000),
        duration: 2.2,
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(-55), roll: 0 },
      });
      if (token !== flightToken) return;
      await new Promise((r) => setTimeout(r, 500));
      if (token !== flightToken) return;
    }
  }

  // --- altitude, street-map blend, credits ---
  function onPostRender() {
    const height = camera.positionCartographic.height;
    const alpha = streetAlpha(height);
    street.alpha = alpha;
    street.show = alpha > 0;
    const pct = Math.round((alpha / STREET_MAX_ALPHA) * 100);
    altitude.textContent = fmtAltitude(height);
    meterBar.style.width = `${pct}%`;
    meterText.textContent = `Street map ${pct}%`;
    const streetName = streetSource === "custom" ? "Map tiles: custom server" : OSM_CREDIT;
    const text = [base === "eox_s2" ? EOX_CREDIT : NE_CREDIT, alpha > 0 ? streetName : ""].filter(Boolean).join(" · ");
    if (text !== lastCredit) {
      lastCredit = text;
      tileCredit.textContent = text;
    }
  }
  scene.postRender.addEventListener(onPostRender);

  camera.setView({ destination: Cesium.Cartesian3.fromDegrees(-60, 25, 24000000) });

  let destroyed = false;
  return {
    showTrace,
    clear,
    flyToHop,
    fitRoute,
    flyAlong,
    setBase,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      flightToken++;
      scene.postRender.removeEventListener(onPostRender);
      try {
        camera.cancelFlight();
      } catch {
        // the widget may already be going away
      }
      widget.destroy();
      stage.remove();
      hud.remove();
      credits.remove();
    },
  };
}

// --- the page-facing side: a control that outlives remounts, and the shell registration ---
let active = null;
const pendingTraces = new Map();
let pendingFit = false;

/** What blades call. Safe before the globe exists: traces and a fit request are kept and replayed. */
export const globeControl = {
  showTrace(trace, opts) {
    if (active) active.showTrace(trace, opts);
    else pendingTraces.set(trace.id, [trace, opts]);
  },
  clear(id) {
    if (active) active.clear(id);
    else if (id === undefined) pendingTraces.clear();
    else pendingTraces.delete(id);
  },
  flyToHop: (hop) => active && active.flyToHop(hop),
  fitRoute() {
    if (active) active.fitRoute();
    else pendingFit = true;
  },
  flyAlong: () => active && active.flyAlong(),
  setBase: (kind) => active && active.setBase(kind),
};

// The page snapshot carries no settings, so the globe reads them the way the settings dialog does: GET /api/v1/plugins.
async function readSettings(pluginId) {
  try {
    const { apiGet } = await import("/static/js/api.js");
    const info = (await apiGet("/api/v1/plugins")).find((p) => p.id === pluginId);
    return (info && info.settings) || {};
  } catch {
    return {};
  }
}

/** The spec for shell.registerGlobe: loads Cesium once the bundle is ready, then builds the globe in the page's host element. */
export function createGlobeSpec(pluginId) {
  return {
    mount(host, ctx) {
      let handle = null;
      let starting = false;
      let gone = false;

      async function start(bundle) {
        starting = true;
        try {
          const [Cesium, settings] = await Promise.all([loadCesium(pluginId, bundle.base_url), readSettings(pluginId)]);
          if (gone) return;
          handle = createGlobe(host, { Cesium, tilesUrl: `/api/v1/plugins/${pluginId}/tiles/`, settings });
          active = handle;
          for (const [trace, opts] of pendingTraces.values()) handle.showTrace(trace, opts);
          pendingTraces.clear();
          if (pendingFit) handle.fitRoute();
          pendingFit = false;
        } catch (err) {
          starting = false;
          console.error("GeoTrace globe failed to start", err);
          if (!gone) host.replaceChildren(el("p", "gt-globe-msg", "The globe could not be started."));
        }
      }

      function update(snapshot) {
        const bundle = snapshot && snapshot.status && snapshot.status.bundle;
        if (!handle && !starting && bundle && bundle.state === "ready") start(bundle);
      }

      update(ctx.snapshot());
      return {
        update,
        destroy() {
          gone = true;
          if (handle) {
            if (active === handle) active = null;
            handle.destroy();
            handle = null;
          }
        },
      };
    },
  };
}

export function registerGlobe(pluginId) {
  shell.registerGlobe(createGlobeSpec(pluginId));
}
