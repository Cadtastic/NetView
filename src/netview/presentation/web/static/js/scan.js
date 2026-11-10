// "Scan now" button logic. Pure helpers, so they can be tested without a DOM.

/** Label, disabled flag and tooltip for the button, from the latest state and whether a click is in flight. */
export function scanButtonState(state, scanning) {
  const jobRunning = !!(state && (state.jobs || []).some((j) => j.owner === "core" && j.name === "scan" && j.running));
  if (scanning || jobRunning) return { disabled: true, label: "Scanning…", title: "" };
  if (!state) return { disabled: true, label: "Scan now", title: "" };
  if (!(state.capabilities || []).includes("discovery")) {
    return { disabled: true, label: "Scan now", title: "No discovery plugin is turned on" };
  }
  return { disabled: false, label: "Scan now", title: "" };
}

/** The toast text for a failed scan request: the server's message, else a plain default for the status. */
export function scanErrorMessage(err) {
  if (err && err.message) return err.message;
  if (err && err.status === 409) return "A scan is already running";
  if (err && err.status === 503) return "There is no network to scan";
  return "The scan failed";
}
