// Pure helpers for the plugin galleries: status, ordering, filtering and card markup.
import { needsSetup } from "../nav.js";

const firstLine = (s) => String(s ?? "").split(/\r?\n/, 1)[0];

/**
 * The status dot of a plugin: {kind, tip}. Precedence: failed, then pending or restart required,
 * then off, then needs configuring, then active.
 */
export function pluginStatus(info) {
  if (info.state === "failed") return { kind: "bad", tip: `Failed: ${firstLine(info.error)}` };
  if (info.state === "pending" || info.restart_required) return { kind: "restart", tip: "Awaiting restart" };
  if (!info.enabled || info.state === "disabled") return { kind: "off", tip: "Off" };
  if (needsSetup(info)) return { kind: "warn", tip: "Needs configuring" };
  return { kind: "ok", tip: "Active" };
}

/** What deserves a dot on the Installed rail entry: "bad", "warn" or null. */
export function attention(list) {
  if (list.some((p) => p.state === "failed" || p.state === "pending" || p.restart_required)) return "bad";
  if (list.some(needsSetup)) return "warn";
  return null;
}
