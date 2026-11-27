// Pure globe geometry: no Cesium, no DOM. Degrees in, degrees and metres out.
export const STARLINK_ASN = 14593;
export const STARLINK_ALTITUDE_M = 550000;
export const BLEND_FAR_M = 4000000; // the street map is invisible from here up
export const BLEND_NEAR_M = 600000; // and fully faded in from here down
export const STREET_MAX_ALPHA = 0.92;
export const HOP_BASE_M = 30; // hops, arc ends, the route path and the packet all sit this far above the surface
const EARTH_RADIUS_M = 6371008.8;
const RAD = Math.PI / 180;

const placed = (hop) => hop != null && Number.isFinite(hop.lat) && Number.isFinite(hop.lon);

function unit(p) {
  const lat = p.lat * RAD;
  const lon = p.lon * RAD;
  return [Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)];
}

function angleBetween(u, v) {
  const dot = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  const cross = Math.hypot(u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]);
  return Math.atan2(cross, dot);
}

function toLonLat(v) {
  return { lon: Math.atan2(v[1], v[0]) / RAD, lat: Math.atan2(v[2], Math.hypot(v[0], v[1])) / RAD };
}

/** Points along the great circle a to b, lifted into a sine arch above `baseM`. Endpoints are exact, at height `baseM`. */
export function arcPoints(a, b, { liftM, steps = 48, baseM = 0 } = {}) {
  const ua = unit(a);
  const ub = unit(b);
  const theta = angleBetween(ua, ub);
  const distance = theta * EARTH_RADIUS_M;
  const peak = liftM ?? Math.min(distance * 0.12, 350000) + 2000;
  const out = [];
  for (let i = 0; i <= steps; i++) {
    if (i === 0) out.push({ lon: a.lon, lat: a.lat, h: baseM });
    else if (i === steps) out.push({ lon: b.lon, lat: b.lat, h: baseM });
    else {
      const f = i / steps;
      let p;
      if (theta < 1e-9) p = { lon: a.lon, lat: a.lat };
      else {
        const wa = Math.sin((1 - f) * theta) / Math.sin(theta);
        const wb = Math.sin(f * theta) / Math.sin(theta);
        p = toLonLat([wa * ua[0] + wb * ub[0], wa * ua[1] + wb * ub[1], wa * ua[2] + wb * ub[2]]);
      }
      out.push({ lon: p.lon, lat: p.lat, h: baseM + Math.sin(Math.PI * f) * peak });
    }
  }
  return out;
}

/** One polyline through every placed hop. With `starlink`, the first leg arches up to the satellite at 550 000 m. */
export function routePoints(hops, { starlink = false, baseM = 0 } = {}) {
  const stops = hops.filter(placed);
  if (stops.length === 1) return [{ lon: stops[0].lon, lat: stops[0].lat, h: baseM }];
  let out = [];
  for (let i = 0; i < stops.length - 1; i++) {
    const leg =
      i === 0 && starlink
        ? arcPoints(stops[i], stops[i + 1], { liftM: STARLINK_ALTITUDE_M, steps: 40, baseM })
        : arcPoints(stops[i], stops[i + 1], { baseM });
    out = out.concat(i ? leg.slice(1) : leg);
  }
  return out;
}

/** How much of the street map shows at a camera height: 0 from 4 000 km up, 1 below 600 km. */
export function blend(heightM) {
  const t = (BLEND_FAR_M - heightM) / (BLEND_FAR_M - BLEND_NEAR_M);
  return Math.min(1, Math.max(0, t));
}

/** The street layer's opacity: blend() scaled so the map never fully hides the globe. */
export const streetAlpha = (heightM) => blend(heightM) * STREET_MAX_ALPHA;

/** A camera target that frames the placed hops: {lon, lat, heightM}. No placed hop gives null. */
export function fitView(hops) {
  const stops = hops.filter(placed);
  if (stops.length === 0) return null; // nothing placed: the caller leaves the camera alone
  if (stops.length === 1) return { lon: stops[0].lon, lat: stops[0].lat, heightM: 1500000 };
  const sum = stops.map(unit).reduce((s, u) => [s[0] + u[0], s[1] + u[1], s[2] + u[2]], [0, 0, 0]);
  const norm = Math.hypot(...sum);
  const centre = norm < 1e-9 ? { lon: 0, lat: 0 } : toLonLat(sum.map((x) => x / norm));
  const uc = unit(centre);
  const reach = Math.max(...stops.map((s) => angleBetween(uc, unit(s)))) * EARTH_RADIUS_M;
  return { lon: centre.lon, lat: centre.lat, heightM: Math.min(22000000, Math.max(1500000, reach * 2.6)) };
}

/**
 * How far to turn a straight-down camera toward the blades (to the left) so that what is under it appears in the middle
 * of the part of the screen the blades leave free. A camera looking straight down always shows its target at the
 * centre of the canvas, so moving the camera cannot do this: the view direction has to turn. The target then sits
 * `coveredPx / 2` pixels right of centre, and a pixel offset is a tangent of the angle: atan(offset / focalLength) with
 * focalLength = (canvas height / 2) / tan(fovy / 2). Radians; 0 when nothing is covered.
 */
export function viewTurnRad({ coveredPx, heightPx, fovy }) {
  if (!(coveredPx > 0) || !(heightPx > 0) || !(fovy > 0) || fovy >= Math.PI) return 0;
  const focalPx = heightPx / 2 / Math.tan(fovy / 2);
  return Math.atan(coveredPx / 2 / focalPx);
}

/**
 * Heading/pitch/roll for a camera over its target that looks straight down turned `angleRad` toward the west (the
 * blades), north up on screen. Passed to Cesium as HPR rather than as direction/up: Cesium reads a direction within 1e-3
 * of straight down as nadir and drops the heading and roll, so a small turn would tilt north instead of west.
 * heading 3 pi / 2 is west, pitch -pi/2 is down (so pitch = angle - pi/2), roll pi/2 keeps north up.
 */
export function viewHpr(angleRad) {
  return { heading: (3 * Math.PI) / 2, pitch: angleRad - Math.PI / 2, roll: Math.PI / 2 };
}

/** Great-circle distance in metres between two {lon, lat} points. */
export function distanceM(a, b) {
  return angleBetween(unit(a), unit(b)) * EARTH_RADIUS_M;
}

/** How many steps an arc between a and b gets: one per about 40 km, from 6 to 120. */
export function legSteps(a, b) {
  return Math.min(120, Math.max(6, Math.round(distanceM(a, b) / 40000)));
}

/**
 * Splits an arc into dashes: runs of two consecutive points, every other segment. Dashes are drawn as separate plain
 * lines because Cesium's dash material turns into a large wedge when a segment passes behind the camera.
 */
export function dashRuns(points) {
  const runs = [];
  for (let i = 0; i + 1 < points.length; i += 2) runs.push([points[i], points[i + 1]]);
  return runs;
}

/** Camera height after a zoom step: in is 40 percent closer, out is 120 percent further; never under 100 m. */
export function zoomHeight(heightM, direction) {
  return Math.max(100, direction === "in" ? heightM * 0.6 : heightM * 2.2);
}
