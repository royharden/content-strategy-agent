import assert from "node:assert/strict";
import test from "node:test";
import { createFrontendConfig } from "../../scripts/frontend-config.mjs";

test("building static files never requires a listener or a port", () => {
  assert.equal(createFrontendConfig("build", {}).root, "web");
  assert.equal(createFrontendConfig("build", {}).server, undefined);
});

test("serve fails without explicit allocation instead of taking Vite's default port", () => {
  assert.throws(() => createFrontendConfig("serve", {}), /actual agent-ports claim/);
});

test("invalid, malformed and out-of-band ports fail before a listener exists", () => {
  for (const port of ["5173", "19999", "30000", "20000.0", "20e03", "20000;echo x"]) {
    assert.throws(() => createFrontendConfig("serve", { CSA_WEB_PORT: port }));
  }
});

test("an explicit in-band test value binds loopback with no automatic fallback", () => {
  // A configuration test value, not a resource claim or an opened listener.
  const config = createFrontendConfig("serve", { CSA_WEB_PORT: "29998" });
  assert.deepEqual(config.server, { host: "127.0.0.1", port: 29998, strictPort: true });
  assert.deepEqual(config.preview, config.server);
});
