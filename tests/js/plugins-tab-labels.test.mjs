import assert from "node:assert/strict";
import { test } from "node:test";

import { PERMISSION_LABELS } from "../../src/netview/presentation/web/static/js/settings/plugins-tab.js";

test("network:internet has a gallery label", () => {
  assert.equal(PERMISSION_LABELS["network:internet"], "Connects to the internet");
});
