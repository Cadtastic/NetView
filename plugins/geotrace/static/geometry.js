// Pure globe geometry: no Cesium, no DOM. Degrees in, degrees and metres out.
export const STARLINK_ASN = 14593;
export const STARLINK_ALTITUDE_M = 550000;
export const BLEND_FAR_M = 4000000; // the street map is invisible from here up
export const BLEND_NEAR_M = 600000; // and fully faded in from here down
export const STREET_MAX_ALPHA = 0.92;
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

/** Points along the great circle a to b, lifted into a sine arch. Endpoints are returned exactly, at height 0. */
export function arcPoints(a, b, { liftM, steps = 48 } = {}) {
  const ua = unit(a);
  const ub = unit(b);
  const theta = angleBetween(ua, ub);
  const distance = theta * EARTH_RADIUS_M;
  const peak = liftM ?? Math.min(distance * 0.12, 350000) + 2000;
  const out = [];
  for (let i = 0; i <= steps; i++) {
    if (i === 0) out.push({ lon: a.lon, lat: a.lat, h: 0 });
    else if (i === steps) out.push({ lon: b.lon, lat: b.lat, h: 0 });
    else {
      const f = i / steps;
      let p;
      if (theta < 1e-9) p = { lon: a.lon, lat: a.lat };
      else {
        const wa = Math.sin((1 - f) * theta) / Math.sin(theta);
        const wb = Math.sin(f * theta) / Math.sin(theta);
        p = toLonLat([wa * ua[0] + wb * ub[0], wa * ua[1] + wb * ub[1], wa * ua[2] + wb * ub[2]]);
      }
      out.push({ lon: p.lon, lat: p.lat, h: Math.sin(Math.PI * f) * peak });
    }
  }
  return out;
}

/** One polyline through every placed hop. With `starlink`, the first leg arches up to the satellite at 550 000 m. */
export function routePoints(hops, { starlink = false } = {}) {
  const stops = hops.filter(placed);
  if (stops.length === 1) return [{ lon: stops[0].lon, lat: stops[0].lat, h: 0 }];
  let out = [];
  for (let i = 0; i < stops.length - 1; i++) {
    const leg =
      i === 0 && starlink
        ? arcPoints(stops[i], stops[i + 1], { liftM: STARLINK_ALTITUDE_M, steps: 40 })
        : arcPoints(stops[i], stops[i + 1]);
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

/** A camera target that frames the placed hops: {lon, lat, heightM}. No placed hop gives a view of the whole Earth. */
export function fitView(hops) {
  const stops = hops.filter(placed);
  if (stops.length === 0) return { lon: 0, lat: 20, heightM: 22000000 };
  if (stops.length === 1) return { lon: stops[0].lon, lat: stops[0].lat, heightM: 1500000 };
  const sum = stops.map(unit).reduce((s, u) => [s[0] + u[0], s[1] + u[1], s[2] + u[2]], [0, 0, 0]);
  const norm = Math.hypot(...sum);
  const centre = norm < 1e-9 ? { lon: 0, lat: 0 } : toLonLat(sum.map((x) => x / norm));
  const uc = unit(centre);
  const reach = Math.max(...stops.map((s) => angleBetween(uc, unit(s)))) * EARTH_RADIUS_M;
  return { lon: centre.lon, lat: centre.lat, heightM: Math.min(22000000, Math.max(1500000, reach * 2.6)) };
}
