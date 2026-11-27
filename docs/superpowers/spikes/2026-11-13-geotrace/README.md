# GeoTrace spikes S1-S3 (run 2026-11-26)

Spec §14 asked for three spikes before building. Results:

| Spike | Result | Stop? |
|---|---|---|
| S1: OSM tiles through the server | Works. Blocked tiles are recognisable. | No |
| S2: Cesium in the NetView shell under the real CSP | Works with **no CSP change**, after two exact patches to our Cesium copy and two loader settings. | No |
| S3: command captures | Windows captured. IPv6 success fixtures synthesized (no IPv6 route on this LAN). Linux captures pending from the user. | No |

## S1: OpenStreetMap through the server

`osm_probe.py` fetched four tiles (`3/1/3`, `8/53/97`, `14/3372/6261`, `17/26987/50097`) from `https://tile.openstreetmap.org/` with plain `urllib` and `User-Agent: NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)`, with no Referer.

- **All four returned 200 `image/png` real tiles.** The Denver/Colorado Springs and North America tiles were checked by eye.
- Cache headers: `Cache-Control: max-age=19165…95727, stale-while-revalidate=604800, stale-if-error=604800`, plus `Expires` and `ETag`. So revalidation with `If-None-Match` is available.
- **Blocked tiles** came back for a request with the library's default User-Agent, and for a browser User-Agent with a `http://localhost:…` Referer (which is what the mockup's browser did). Both were **200 `image/png`** (6,725 and 6,672 bytes) with:
  - `x-blocked: Access denied. See https://operations.osmfoundation.org/policies/tiles/`
  - `cache-control: no-cache`

**Rule for the tile cache (Part 2 Task 10):** a response carrying an `x-blocked` header is a failure. It is not cached, it returns 502, and the plugin status records "OpenStreetMap refused the request". No hash list is needed.

## S2: CesiumJS 1.144 in the NetView shell

Setup: `Cesium-1.144.zip` (128,477,966 bytes, SHA-256 `7c8e2297…0a614`, from the CesiumGS GitHub release) was unpacked in the scratchpad. A throwaway folder plugin served `Build/Cesium` from its static folder. NetView (this branch, `--mode home`, scratch data dir) ran on port 8775, and the page slot loaded `Cesium.js` and logged every `securitypolicyviolation`. The loader that worked is kept here as `spike_globe_ui.js`.

**First load, unmodified, with `Cesium.Viewer`: broken.**

1. `script-src` blocked `eval` in the bundled **knockout** library: `var t=this||(0,eval)("this")`. It runs while `Cesium.js` builds its exports, so the `EvalError` is uncaught and `window.Cesium` is never set. Knockout's binding engine also compiles `data-bind` expressions with `new Function`; the `Viewer` UI widgets use those.
2. `worker-src` (falling back to `script-src`) blocked three `blob:` workers. The single-file `Cesium.js` embeds its worker code as a `CESIUM_WORKERS` string and starts classic workers from blob URLs when it is defined.
3. `script-src` blocked five `WebAssembly.instantiate` calls (`wasm-eval`). These are meshoptimizer encoder/decoder modules that initialise eagerly for compressed glTF. GeoTrace draws no glTF. The errors are unhandled promise rejections, not fatal.

**What made it work with zero violations and the CSP untouched:**

| Change | Where | Why it is safe |
|---|---|---|
| Patch `var t=this\|\|(0,eval)("this")` → `var t=this\|\|globalThis` (exactly 1 occurrence) | bundle tool | Same value in every browser NetView supports |
| Patch `if(typeof WebAssembly!="object")return{supported:!1}` → `return{supported:!1}` (exactly 5 occurrences) | bundle tool | Turns off meshopt WASM only (compressed 3D models); GeoTrace uses imagery, points, labels and polylines |
| Use `Cesium.CesiumWidget`, never `Cesium.Viewer` | `globe.js` | `CesiumWidget` has `entities`, camera and imagery, but no knockout UI, so no `new Function` |
| Set `window.CESIUM_WORKERS = undefined` right after `Cesium.js` loads, before creating the widget | loader | Cesium then starts **module workers** from `Workers/*.js` on NetView's own origin, which `script-src 'self'` allows |

Result: `CesiumWidget` with a Natural Earth II base layer, a polyline and points. `tilesLoaded === true`, the globe drew in the shell (screenshot checked), and the violation list was empty.

**Consequences for Part 2:**

- Task 11's bundle tool applies both patches, each with an exact-count check. It **fails** if a count differs, for example after a Cesium upgrade. It drops `index.js` and `index.cjs` (ESM/CJS entry points we don't serve).
- Trimmed sizes before trimming `Assets/`: `Cesium.js` 5.7 MB, `Workers/` 1.4 MB, `ThirdParty/` 1.1 MB, `Widgets/` 0.65 MB, `Assets/` 4.7 MB (of which `IAU2006_XYS` is 1.8 MB and only used for ICRF/precise Earth orientation, so the tool may drop it). Roughly 10-12 MB unzipped.
- Nothing needs to be added to the CSP, not even on worker responses, so the "worker-only directive" branch of spec §12 is not used.
- Tile layers through `/api/v1/plugins/<id>/tiles/...` are same-origin `img`/`connect` requests, allowed by the CSP.

## S3: command captures

Captured on this PC (Windows 11, English) on 2026-11-26. The route now runs `10.27.10.1` (OPNsense) → `192.168.1.1` (Starlink router) → `100.64.0.1` (Starlink CGNAT) → transit. The house's public address does not appear in any capture (CGNAT), and the transit router addresses are kept as captured.

| File | Source |
|---|---|
| `tracert_win_reached.txt` | `tracert -d -h 30 -w 1000 1.1.1.1`, 10 hops, reached |
| `tracert_win_unreachable_target.txt` | `tracert -d -h 30 -w 1000 192.0.2.1`, 2 hops then 28 silent rows |
| `tracert_win_silent_tail.txt` | to `microsoft.com` (150.171.110.9): silent hops **mid-route** (8-9, 12-15), and the destination answers |
| `tracert_win_ipv6_no_route.txt` | `tracert -6 …`: `Transmit error: code 1231` on hop 1 (no IPv6 route) |
| `tracert_win_ipv6.txt` | **synthesized** in the Windows `-6` format (marked `# edited`) |
| `ping6_win_unreachable.txt` | `ping -6`: `PING: transmit failed. General failure.` (no route; no time → `None`) |
| `ping6_win_reply.txt` | **synthesized** reply line `Reply from …: time=24ms` (marked `# edited`) |
| `traceroute_linux_*.txt`, `tracepath_linux.txt`, `ping6_linux_reply.txt` | synthesized (marked `# edited`) from the captured Windows route; replace with real captures from the Proxmox host when available |

**Finding for the user:** this LAN has **no IPv6 route** today. The PC has only ULA addresses (`fd27:cad:1::/64`, `fde3:…`), so IPv6 targets fail until OPNsense provides IPv6. Per-target IPv6 is still built (user decision). On this network such traces fail with a plain-words error.
