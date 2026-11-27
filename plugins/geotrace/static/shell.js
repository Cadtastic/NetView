// Mount points for the page's parts. Later modules call these at load time; the page reads them when it mounts.
//   registerBlade(base, {title, render(body, ctx) -> {update?(), destroy?()} | void})
//       `base` is the part of a blade key before the first ":" ("targets", "compare", "trends", "trace", "target" for "target:7").
//   registerGlobe({mount(host, ctx) -> {update?(), destroy?()} | void})
// ctx (see page.js): {api, key, params, open(key, {level, wide}), close(key), snapshot(), onChange(fn) -> off}.
const blades = new Map();
let globe = null;

export const shell = {
  registerBlade(base, spec) {
    blades.set(base, spec);
  },
  registerGlobe(spec) {
    globe = spec;
  },
  blade: (base) => blades.get(base) || null,
  globe: () => globe,
};
