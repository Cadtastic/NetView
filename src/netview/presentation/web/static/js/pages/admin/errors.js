// Shared by the Admin sections: show a failed API call's message in a box.

/** Show the message (and any per-field messages) from a failed API call in `box`. */
export function showError(box, err) {
  const fields = err && err.fields ? Object.values(err.fields).join(" ") : "";
  box.textContent = fields || (err && err.message) || "Something went wrong";
}
