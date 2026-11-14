// Calls for the dashboard layout: the signed-in user's own, and the admin default.
import { apiGet, apiSend } from "../api.js";

const BASE = "/api/v1";

/** `{layout, source, updated_ms, default}` for the signed-in user. */
export const getLayout = () => apiGet(`${BASE}/dashboard/layout`);
/** Save `layout` as the signed-in user's own. */
export const saveLayout = (layout) => apiSend("PUT", `${BASE}/dashboard/layout`, layout);
/** Drop the signed-in user's own layout, so they get the default again. */
export const resetLayout = () => apiSend("DELETE", `${BASE}/dashboard/layout`);

/** `{layout, users_with_own_layout, roles_with_permission}` for the admin default. */
export const getDefault = () => apiGet(`${BASE}/admin/dashboard/default`);
/** Save the default layout; `clearMine` also removes every user's own layout. */
export const saveDefault = (layout, clearMine) => apiSend("PUT", `${BASE}/admin/dashboard/default`, { layout, clear_mine: !!clearMine });
/** Remove every user's own layout. -> `{removed}` */
export const resetEveryone = () => apiSend("DELETE", `${BASE}/admin/dashboard/layouts`);
