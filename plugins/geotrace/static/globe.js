// The GeoTrace globe: a CesiumWidget (never Cesium.Viewer, whose UI needs `new Function`) with route arcs, hop labels,
// a moving packet, a satellite bounce for Starlink, and a street map that fades in as the camera comes down.
//
// From a blade:  import { globeControl } from "./globe.js";
//   globeControl.showTrace(trace, {style: "solid" | "dashed", color: "var(--accent)"});  globeControl.flyToHop(hop);
// Calls made before the globe exists (the bundle is still downloading) are replayed once it does.
import { loadCesium } from "./cesium-base.js";
import {
  arcPoints,
  routePoints,
  streetAlpha,
  fitView,
  viewTurnRad,
  viewHpr,
  legSteps,
  dashRuns,
  zoomHeight,
  STARLINK_ALTITUDE_M,
  STARLINK_ASN,
  STREET_MAX_ALPHA,
  HOP_BASE_M,
} from "./geometry.js";
import { shell } from "./shell.js";
import { isShown, drawKey } from "./draw-keys.js";

export const DB_IP_TEXT = "IP geolocation by DB-IP";
export const DB_IP_HREF = "https://db-ip.com";
const OSM_CREDIT = "© OpenStreetMap contributors";
const OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright";
const BASE_KEY = "netview.geotrace.base"; // the viewer's own pick of globe imagery
const BASES = [
  ["natural_earth", "Natural Earth (built in)"],
  ["eox_s2", "Sentinel-2 cloudless (EOX, non-commercial)"],
];
const EOX_CREDIT = "Sentinel-2 cloudless – https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2020)";
const NE_CREDIT = "Natural Earth";
const ASSUMED_NOTE = "placed at the ground station";
const IMPLAUSIBLE_NOTE = "location from the database doesn't fit the response time";

const DEFAULT_VIEW = { lon: -60, lat: 25, heightM: 24000000 };
const EARTH_VIEW = { lon: -100, lat: 30, heightM: 22000000 };

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

  // The HUD and credits live in the page (above the blades), not in the globe host that sits under them.
  const overlay = host.parentElement || host;
  const mounted = [];
  const mount = (node) => {
    overlay.appendChild(node);
    mounted.push(node);
    return node;
  };
  const button = (label, text) => {
    const b = el("button", "gt-globe-btn", text);
    b.type = "button";
    b.title = label;
    b.setAttribute("aria-label", label);
    return b;
  };

  const stage = el("div", "gt-globe-stage");
  host.appendChild(stage);
  const hud = mount(el("div", "gt-globe-hud"));
  const altitude = el("span", "gt-globe-alt", "–");
  const meterBar = el("i");
  const meter = el("div", "gt-globe-meter");
  meter.appendChild(meterBar);
  const meterText = el("span", "gt-globe-blend", "Street map 0%");
  const picker = el("select", "gt-globe-select");
  picker.setAttribute("aria-label", "Globe imagery");
  for (const [value, label] of BASES) {
    const option = el("option", "", label);
    option.value = value;
    picker.appendChild(option);
  }
  const zoomRow = el("div", "gt-globe-zoom");
  const zoomIn = button("Zoom in", "+ Zoom");
  const zoomOut = button("Zoom out", "– Zoom");
  const earth = button("Show the whole Earth", "Earth");
  zoomRow.append(zoomIn, zoomOut, earth);
  hud.append(altitude, meter, meterText, picker, zoomRow);

  const credits = mount(el("div", "gt-credits"));
  const tileCredit = el("span", "gt-credit-tiles");
  const osmCredit = el("a", "gt-credit-osm", OSM_CREDIT);
  osmCredit.href = OSM_COPYRIGHT;
  osmCredit.target = "_blank";
  osmCredit.rel = "noopener noreferrer";
  osmCredit.hidden = true;
  const customCredit = el("span", "gt-credit-custom", "Map tiles: custom server");
  customCredit.hidden = true;
  const cesiumCredit = el("span", "gt-credit-cesium");
  const dbip = el("a", "gt-credit-dbip", DB_IP_TEXT);
  dbip.href = DB_IP_HREF;
  dbip.target = "_blank";
  dbip.rel = "noopener noreferrer";
  credits.append(tileCredit, osmCredit, customCredit, dbip, cesiumCredit);

  let widget = null;
  try {
    widget = new Cesium.CesiumWidget(stage, {
      baseLayer: Cesium.ImageryLayer.fromProviderAsync(
        Cesium.TileMapServiceImageryProvider.fromUrl(Cesium.buildModuleUrl("Assets/Textures/NaturalEarthII")),
      ),
      creditContainer: cesiumCredit,
    });
    return build(widget);
  } catch (err) {
    if (widget) {
      try {
        widget.destroy();
      } catch {
        // already broken; the DOM is cleaned below
      }
    }
    stage.remove();
    mounted.forEach((n) => n.remove());
    throw err;
  }

  function build(widget) {
    const { scene, camera } = widget;
    const layers = scene.imageryLayers;

    const template = (source) => `${tilesUrl}${source}/{z}/{x}/{y}`;
    // Natural Earth (layer 0) always stays underneath, so Sentinel-2 gaps and tile errors show the globe, not black.
    const satellite = layers.addImageryProvider(
      new Cesium.UrlTemplateImageryProvider({ url: template("eox-s2"), maximumLevel: 14 }),
    );
    let streetSource = "osm";
    let street = null;
    function setStreetSource(source) {
      const next = source === "custom" ? "custom" : "osm";
      if (street && next === streetSource) return;
      if (street) layers.remove(street, true);
      streetSource = next;
      street = layers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({ url: template(next), maximumLevel: 19 }));
      street.alpha = 0;
      street.show = false;
      lastCredit = "";
    }

    let base = "natural_earth";
    let lastCredit = "";
    function setBase(kind) {
      base = kind === "eox_s2" ? "eox_s2" : "natural_earth";
      satellite.show = base === "eox_s2";
      picker.value = base;
      lastCredit = "";
    }
    picker.addEventListener("change", () => setBase(picker.value));

    // The viewer's own pick of base imagery wins over the saved default: a status refresh never undoes it.
    const storedBase = () => {
      try {
        const v = localStorage.getItem(BASE_KEY);
        return BASES.some(([k]) => k === v) ? v : null;
      } catch {
        return null;
      }
    };
    picker.addEventListener("change", () => {
      try {
        localStorage.setItem(BASE_KEY, picker.value);
      } catch {
        // private window or blocked storage: the pick lasts until the page is left
      }
      viewerPicked = true;
    });
    let viewerPicked = storedBase() !== null;
    let applied = null; // the last {tile_source, base_imagery} applied; null until the first call
    /** Applies the page's status.map: only values that changed since the last call take effect. A missing map is ignored. */
    function setSettings(next) {
      if (!next || typeof next !== "object") return;
      if (applied === null || next.tile_source !== applied.tile_source) setStreetSource(next.tile_source);
      if (applied === null || next.base_imagery !== applied.base_imagery) {
        if (!viewerPicked) setBase(next.base_imagery);
        else if (applied === null) setBase(storedBase() || next.base_imagery);
      }
      applied = { tile_source: next.tile_source, base_imagery: next.base_imagery };
    }
    setSettings(settings);

    // --- traces ---
    const traces = new Map(); // id -> {entities, hops}
    let focus = null; // a Set of drawing keys that stay visible (see setFocus), or null for all
    let drawn = 0;
    const add = (spec) => widget.entities.add(spec);

    function clear(id) {
      const ids = id === undefined ? [...traces.keys()] : [id];
      for (const key of ids) {
        const t = traces.get(key);
        if (!t) continue;
        t.entities.forEach((e) => widget.entities.remove(e));
        traces.delete(key);
      }
    }

    // The newest solid drawing that is showing: what Fit route and Fly along work on.
    function primaryKey() {
      let best = null;
      for (const [key, t] of traces) if (t.solid && isShown(key, focus) && (best === null || t.seq > traces.get(best).seq)) best = key;
      return best;
    }

    /** Show only the drawings under these keys (hidden, not deleted); null shows all again. Drawings made later obey it too. */
    function setFocus(keys) {
      focus = keys ? new Set(keys) : null;
      for (const [key, t] of traces) t.entities.forEach((e) => (e.show = isShown(key, focus)));
    }

    function showTrace(trace, { style = "solid", color, key } = {}) {
      const id = drawKey(trace, key);
      clear(id);
      const hops = trace.hops || [];
      const stops = hops.filter(placed);
      const tint = color ? colour(color, palette.route) : palette.route;
      const solid = style !== "dashed";
      const starlink = hops.some((h) => h.asn === STARLINK_ASN);
      const entities = [];

      for (let i = 0; i < stops.length - 1; i++) {
        const dashed = !solid || stops[i].plausible === false || stops[i + 1].plausible === false;
        const starLeg = i === 0 && starlink;
        const steps = starLeg ? 40 : dashed ? legSteps(stops[i], stops[i + 1]) : 48;
        const points = arcPoints(
          stops[i],
          stops[i + 1],
          starLeg ? { liftM: STARLINK_ALTITUDE_M, steps, baseM: HOP_BASE_M } : { steps, baseM: HOP_BASE_M },
        );
        if (dashed) {
          // Dashes are separate plain lines: Cesium's dash material draws a huge wedge when a segment passes the camera.
          for (const run of dashRuns(points)) {
            entities.push(
              add({
                polyline: {
                  positions: Cesium.Cartesian3.fromDegreesArrayHeights(run.flatMap((p) => [p.lon, p.lat, p.h])),
                  width: 3,
                  arcType: Cesium.ArcType.NONE,
                  material: tint,
                },
              }),
            );
          }
        } else {
          entities.push(
            add({
              polyline: {
                positions: Cesium.Cartesian3.fromDegreesArrayHeights(points.flatMap((p) => [p.lon, p.lat, p.h])),
                width: 4,
                arcType: Cesium.ArcType.NONE,
                material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.18, color: tint }),
              },
            }),
          );
        }
      }

      stops.forEach((hop, i) => {
        const home = hop.placement === "home";
        const dest = trace.reached === true && i === stops.length - 1 && stops.length > 1;
        const fill = home ? palette.home : dest ? palette.dest : tint;
        const hollow = hop.plausible === false;
        entities.push(
          add({
            position: Cesium.Cartesian3.fromDegrees(hop.lon, hop.lat, HOP_BASE_M),
            point: {
              pixelSize: home || dest ? 12 : 8,
              color: hollow ? fill.withAlpha(0) : fill,
              outlineColor: hollow ? fill : palette.surface,
              outlineWidth: hollow ? 3 : 2,
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
                  translucencyByDistance: new Cesium.NearFarScalar(4e6, 1, 1.2e7, 0),
                }
              : undefined,
          }),
        );
      });

      if (solid && starlink && stops.length > 1) {
        const mid = arcPoints(stops[0], stops[1], { liftM: STARLINK_ALTITUDE_M, steps: 2, baseM: HOP_BASE_M })[1];
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
        const path = routePoints(hops, { starlink, baseM: HOP_BASE_M }).map((p) => Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.h));
        entities.push(
          add({
            position: new Cesium.CallbackProperty(() => path[Math.floor((Date.now() / 18) % path.length)], false),
            point: {
              pixelSize: 7,
              color: palette.text,
              outlineColor: tint.withAlpha(0.6),
              outlineWidth: 6,
            },
          }),
        );
      }

      entities.forEach((e) => (e.show = isShown(id, focus)));
      traces.set(id, { entities, hops: stops, solid, seq: ++drawn });
    }

    // --- camera ---
    let flightToken = 0;
    const flyTo = (options) => new Promise((resolve) => camera.flyTo({ ...options, complete: resolve, cancel: resolve }));

    function flyToHop(hop) {
      if (!placed(hop)) return;
      camera.cancelFlight();
      flightToken++;
      autoView = false;
      camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(hop.lon, hop.lat - 0.09, 9000),
        duration: 3,
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(-48), roll: 0 },
      });
    }

    // The page's blades cover the left of the canvas. A straight-down camera always shows its target in the middle of the
    // canvas, so to put the target in the free area the view direction is turned toward the blades (see viewTurnRad).
    function viewTurn() {
      try {
        const blades = host.parentElement && host.parentElement.querySelector(".gt-blades");
        const covered = blades ? blades.getBoundingClientRect().right - host.getBoundingClientRect().left : 0;
        return viewTurnRad({ coveredPx: covered, heightPx: host.clientHeight, fovy: camera.frustum.fovy });
      } catch {
        return 0;
      }
    }

    // While the camera is where the page put it (the default view, Earth or a fitted route) it follows the blades and the
    // window size; any move by the user, and every fly-to-hop, switches that off. `wanted` is the view last asked for.
    let autoView = true;
    let wanted = { kind: "earth", view: DEFAULT_VIEW };
    function placeView(view, duration) {
      const destination = Cesium.Cartesian3.fromDegrees(view.lon, view.lat, view.heightM);
      const orientation = viewHpr(viewTurn()); // the same for every turn size, including none
      camera.cancelFlight();
      flightToken++;
      if (duration > 0) camera.flyTo({ destination, duration, orientation });
      else camera.setView({ destination, orientation });
    }

    function fitRoute(duration = 3) {
      const target = fitView([...traces].filter(([key]) => isShown(key, focus)).flatMap(([, t]) => t.hops));
      if (!target) return; // no placed hops: stay where we are
      autoView = true;
      wanted = { kind: "route" };
      placeView(target, duration);
    }

    // Re-apply the view last asked for after the blades or the window changed size: a short flight, not a jump.
    function refit() {
      if (wanted.kind === "route") {
        const target = fitView([...traces].filter(([key]) => isShown(key, focus)).flatMap(([, t]) => t.hops));
        if (target) placeView(target, 0.6);
      } else placeView(wanted.view, 0.6);
    }

    async function flyAlong() {
      const trace = traces.get(primaryKey());
      if (!trace) return;
      camera.cancelFlight();
      autoView = false;
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

    // --- zoom buttons ---
    const heightNow = () => camera.positionCartographic.height;
    const stopFlight = () => {
      camera.cancelFlight();
      flightToken++; // also ends a running flyAlong
    };
    zoomIn.addEventListener("click", () => {
      stopFlight();
      autoView = false;
      camera.zoomIn(Math.max(0, heightNow() - zoomHeight(heightNow(), "in")));
    });
    zoomOut.addEventListener("click", () => {
      stopFlight();
      autoView = false;
      camera.zoomOut(zoomHeight(heightNow(), "out") - heightNow());
    });
    earth.addEventListener("click", () => {
      autoView = true;
      wanted = { kind: "earth", view: EARTH_VIEW };
      placeView(EARTH_VIEW, 2.5);
    });

    // --- altitude, street-map blend, credits ---
    let creditState = "";
    function onPostRender() {
      const height = heightNow();
      const alpha = streetAlpha(height);
      street.alpha = alpha;
      street.show = alpha > 0;
      const pct = Math.round((alpha / STREET_MAX_ALPHA) * 100);
      altitude.textContent = fmtAltitude(height);
      meterBar.style.width = `${pct}%`;
      meterText.textContent = `Street map ${pct}%`;
      const state = `${base}|${streetSource}|${alpha > 0}`;
      if (state !== creditState || lastCredit === "") {
        creditState = state;
        lastCredit = state;
        tileCredit.textContent = base === "eox_s2" ? EOX_CREDIT : NE_CREDIT;
        osmCredit.hidden = !(alpha > 0 && streetSource === "osm");
        customCredit.hidden = !(alpha > 0 && streetSource === "custom");
      }
    }
    scene.postRender.addEventListener(onPostRender);

    placeView(DEFAULT_VIEW, 0);
    const stopAuto = () => {
      autoView = false;
    };
    const canvas = scene.canvas;
    const manual = ["pointerdown", "wheel", "touchstart"];
    manual.forEach((name) => canvas.addEventListener(name, stopAuto, { passive: true }));
    let watcher = null;
    if (typeof ResizeObserver !== "undefined") {
      watcher = new ResizeObserver(() => {
        if (autoView && !destroyed) refit();
      });
      watcher.observe(host);
      const blades = host.parentElement && host.parentElement.querySelector(".gt-blades");
      if (blades) watcher.observe(blades);
    }

    // One click on the Earth (not the end of a drag) gives the point under it, in degrees; cancel() stops listening.
    function pickOnce(callback) {
      let down = null;
      let done = false;
      const onDown = (e) => {
        down = [e.clientX, e.clientY];
      };
      const onUp = (e) => {
        if (done || !down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
        const box = canvas.getBoundingClientRect();
        const spot = camera.pickEllipsoid(new Cesium.Cartesian2(e.clientX - box.left, e.clientY - box.top), scene.globe.ellipsoid);
        if (!spot) return; // a click beside the globe is not a pick
        const at = Cesium.Cartographic.fromCartesian(spot);
        done = true;
        cancel();
        callback({ lat: Cesium.Math.toDegrees(at.latitude), lon: Cesium.Math.toDegrees(at.longitude) });
      };
      const cancel = () => {
        done = true;
        canvas.removeEventListener("pointerdown", onDown);
        canvas.removeEventListener("pointerup", onUp);
      };
      canvas.addEventListener("pointerdown", onDown);
      canvas.addEventListener("pointerup", onUp);
      return cancel;
    }

    let destroyed = false;
    return {
      pickOnce,
      showTrace,
      clear,
      setFocus,
      flyToHop,
      fitRoute,
      flyAlong,
      setBase,
      setSettings,
      destroy() {
        if (destroyed) return;
        destroyed = true;
        if (watcher) watcher.disconnect();
        manual.forEach((name) => canvas.removeEventListener(name, stopAuto));
        flightToken++;
        scene.postRender.removeEventListener(onPostRender);
        try {
          camera.cancelFlight();
        } catch {
          // the widget may already be going away
        }
        widget.destroy();
        stage.remove();
        mounted.forEach((n) => n.remove());
      },
    };
  }
}

// --- the page-facing side: a control that outlives remounts, and the shell registration ---
let active = null;
const pendingTraces = new Map();
let pendingFit = false;
let pendingFocus = null;
let pendingPick = null; // {callback, cancel}: a pick asked for before the globe exists

/** What blades call. Safe before the globe exists: traces and a fit request are kept and replayed. */
export const globeControl = {
  showTrace(trace, opts) {
    if (active) active.showTrace(trace, opts);
    else pendingTraces.set(drawKey(trace, opts && opts.key), [trace, opts]);
  },
  setFocus(keys) {
    pendingFocus = keys ? [...keys] : null;
    if (active) active.setFocus(keys);
  },
  clear(id) {
    if (active) active.clear(id);
    else if (id === undefined) pendingTraces.clear();
    else pendingTraces.delete(id);
  },
  /** Wait for one click on the globe: callback({lat, lon}). Returns cancel. Works before the globe exists (it starts then). */
  pickOnce(callback) {
    const request = { callback, cancel: () => {} };
    if (active) request.cancel = active.pickOnce(callback);
    else pendingPick = request;
    return () => {
      if (pendingPick === request) pendingPick = null;
      request.cancel();
    };
  },
  flyToHop: (hop) => active && active.flyToHop(hop),
  fitRoute() {
    if (active) active.fitRoute();
    else pendingFit = true;
  },
  flyAlong: () => active && active.flyAlong(),
  setBase: (kind) => active && active.setBase(kind),
};

/**
 * The spec for shell.registerGlobe: loads Cesium once the bundle is ready, then builds the globe in the page's host element.
 * The map choices (tile source, default base imagery) come from the page's status snapshot (status.map), which the page
 * refreshes every 30 s and whenever it becomes visible again, so a change made in Settings reaches the live globe.
 */
export function createGlobeSpec(pluginId) {
  return {
    mount(host, ctx) {
      let handle = null;
      let starting = false;
      let gone = false;
      let message = null;

      async function start(snapshot) {
        starting = true;
        let made = null;
        try {
          const Cesium = await loadCesium(pluginId, snapshot.status.bundle.base_url);
          if (gone) return;
          if (message) message.remove();
          message = null;
          made = createGlobe(host, {
            Cesium,
            tilesUrl: `/api/v1/plugins/${pluginId}/tiles/`,
            settings: snapshot.status.map || {},
          });
          handle = made;
          active = made;
          if (pendingFocus) made.setFocus(pendingFocus);
          for (const [trace, opts] of pendingTraces.values()) made.showTrace(trace, opts);
          pendingTraces.clear();
          if (pendingFit) made.fitRoute();
          pendingFit = false;
          if (pendingPick) {
            pendingPick.cancel = made.pickOnce(pendingPick.callback);
            pendingPick = null;
          }
        } catch (err) {
          if (made) {
            try {
              made.destroy();
            } catch {
              // best effort: the retry builds a fresh one
            }
          }
          if (active === made) active = null;
          handle = null;
          starting = false;
          console.error("GeoTrace globe failed to start", err);
          if (!gone && !message) {
            message = el("p", "gt-globe-msg", "The globe could not be started.");
            host.appendChild(message);
          }
        }
      }

      function update(snapshot) {
        const status = snapshot && snapshot.status;
        if (!status) return;
        if (handle) handle.setSettings(status.map);
        else if (!starting && status.bundle && status.bundle.state === "ready") start(snapshot);
      }

      update(ctx.snapshot());
      return {
        update,
        destroy() {
          gone = true;
          pendingTraces.clear(); // a globe that never started leaves nothing queued for the next page
          pendingFit = false;
          pendingPick = null;
          if (handle) {
            if (active === handle) active = null;
            handle.destroy();
            handle = null;
          }
          if (message) message.remove();
        },
      };
    },
  };
}

export function registerGlobe(pluginId) {
  shell.registerGlobe(createGlobeSpec(pluginId));
}
