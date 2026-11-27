// Which globe imagery a viewer may pick (pure, unit-tested). Sentinel-2 is offered only when the admin chose it,
// because the server's tile route serves it only then.
export const BASES = [
  ["natural_earth", "Natural Earth (built in)"],
  ["eox_s2", "Sentinel-2 cloudless (EOX, non-commercial)"],
];

/** The [value, label] pairs the Globe imagery picker shows for the admin's base_imagery. */
export function offeredBases(adminBase) {
  return BASES.filter(([value]) => value === "natural_earth" || adminBase === "eox_s2");
}

/** The viewer's pick if the admin still allows it, else the admin's own choice (Natural Earth when unknown). */
export function resolveBase(pick, adminBase) {
  const admin = adminBase === "eox_s2" ? "eox_s2" : "natural_earth";
  return pick && offeredBases(admin).some(([value]) => value === pick) ? pick : admin;
}
