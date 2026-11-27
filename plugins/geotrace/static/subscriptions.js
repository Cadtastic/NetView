// Page-level change listeners with one scope per blade: closing a blade drops everything it subscribed (pure, tested).
export function createSubscriptions() {
  const all = new Set();
  return {
    emit(value) {
      for (const fn of [...all]) {
        try {
          fn(value);
        } catch (e) {
          console.error("GeoTrace listener failed", e);
        }
      }
    },
    /** {onChange(fn) -> off, dispose()}; after dispose() a late onChange registers nothing. */
    forBlade() {
      const mine = new Set();
      let disposed = false;
      return {
        onChange(fn) {
          const off = () => {
            mine.delete(fn);
            all.delete(fn);
          };
          if (!disposed) {
            mine.add(fn);
            all.add(fn);
          }
          return off;
        },
        dispose() {
          disposed = true;
          for (const fn of mine) all.delete(fn);
          mine.clear();
        },
      };
    },
  };
}
