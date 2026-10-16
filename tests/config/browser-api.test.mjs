import assert from "node:assert/strict";
import test from "node:test";
import { base64, LocalApi, receiptUrl } from "../../web/api.ts";

test("CSV encoding preserves BOM, Unicode and chunk boundaries", () => {
  const bytes = new TextEncoder().encode("\ufeffpost,text\r\nx,lesson 🌿\r\n" + "a".repeat(70000));
  assert.equal(base64(bytes), Buffer.from(bytes).toString("base64"));
});

test("receipt links remain same-origin and encode keys as query data", () => {
  const selection = { dataset_id: "s9-dataset-" + "a".repeat(32), snapshot_id: "b".repeat(64) };
  const url = new URL(receiptUrl(selection, "test?key=other&path=../", "csv"), "http://127.0.0.1:21300");
  assert.equal(url.origin, "http://127.0.0.1:21300");
  assert.equal(url.pathname, "/api/download/csv");
  assert.deepEqual([...url.searchParams.keys()].sort(), ["dataset_id", "key", "snapshot_id"]);
  assert.equal(url.searchParams.get("key"), "test?key=other&path=../");
});

test("mutations cannot run before the local session handshake", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", () => { throw new Error("unexpected network"); });
  await assert.rejects(new LocalApi().post("export", {}), /local_service_unavailable/);
  assert.equal(fetch.mock.callCount(), 0);
});

test("browser mutations bind same-origin credentials, CSRF and explicit payload", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify(url === "/api/session"
      ? { csrf: "synthetic-token", execution_origin: "authored_synthetic_mock" }
      : { state: "approved" }), { headers: { "Content-Type": "application/json" } });
  });
  const api = new LocalApi();
  await api.connect();
  const payload = { approve: true, expected_sequence: 3 };
  assert.deepEqual(await api.post("decide", payload), { state: "approved" });
  assert.equal(calls[1].url, "/api/decide");
  assert.equal(calls[1].options.credentials, "same-origin");
  assert.equal(calls[1].options.cache, "no-store");
  assert.equal(calls[1].options.headers["X-CSRF-Token"], "synthetic-token");
  assert.deepEqual(JSON.parse(calls[1].options.body), payload);
});

test("a server refusal remains a refusal rather than success-shaped data", async (t) => {
  t.mock.method(globalThis, "fetch", async (url) => new Response(JSON.stringify(
    url === "/api/session" ? { csrf: "synthetic-token", execution_origin: "authored_synthetic_mock" }
      : { code: "current_approval_required" }), { status: url === "/api/session" ? 200 : 409 }));
  const api = new LocalApi();
  await api.connect();
  await assert.rejects(api.post("export", {}), /current_approval_required/);
});
