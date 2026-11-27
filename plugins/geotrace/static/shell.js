// Mount points for the page's parts. Later modules call these at load time; the page reads them when it mounts.
//   registerBlade(base, {title: string | (key, snapshot) => string, render(body, ctx) -> {update?(snapshot), destroy?()} | void})
//       `base` is the part of a blade key before the first ":" ("targets", "compare", "trends", "trace", "target" for "target:7").
//   registerGlobe({mount(host, ctx) -> {update?(snapshot), destroy?()} | void})
// update(snapshot) is called after every status/targets refresh (every 30 s while the page is visible).
// ctx (see page.js): {api, key, params, open(key, {level?, wide?}), close(key), snapshot(), onChange(fn) -> off,
//   setTitle(title, sub?)}. open() without a level goes to the end of the stack; open/close are safe to call from render
//   (they run after it). onChange subscriptions are dropped automatically when the blade closes.
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
