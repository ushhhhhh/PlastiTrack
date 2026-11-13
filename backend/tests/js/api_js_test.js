// Unit tests for the frontend helper api.js (run by test_frontend_js.py).
// Usage: node api_js_test.js <project_root>
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = process.argv[2];
const SOURCE = fs.readFileSync(path.join(ROOT, "api.js"), "utf8");

function load(options) {
  const calls = [];
  const ctx = {
    window: {
      location: { protocol: (options && options.protocol) || "http:" },
      fetch: (url, opts) => {
        calls.push({ url, opts });
        return options.fetch(url, opts);
      },
      AbortController,
    },
    setTimeout, clearTimeout, encodeURIComponent, JSON, Promise,
  };
  vm.runInNewContext(SOURCE, ctx);
  return { api: ctx.window.PlastiAPI, calls };
}

function reply(status, body) {
  return Promise.resolve({
    ok: status >= 200 && status < 300, status,
    text: () => Promise.resolve(body === undefined ? "" : JSON.stringify(body)),
  });
}

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

// ---- user ids
test("user ids are trimmed and lowercased", () => {
  const { api } = load({ fetch: () => reply(200, {}) });
  assert.deepStrictEqual(api.normaliseUserId("  Riya_22 ").value, "riya_22");
  assert.strictEqual(api.normaliseUserId("  Riya_22 ").ok, true);
});
test("invalid and reserved user ids rejected", () => {
  const { api } = load({ fetch: () => reply(200, {}) });
  for (const bad of ["", "  ", "ab", "has space", "a".repeat(41), "x<y>", null, undefined]) {
    assert.strictEqual(api.normaliseUserId(bad).ok, false, String(bad));
  }
  const reserved = api.normaliseUserId("Sample_Aarav");
  assert.strictEqual(reserved.ok, false);
  assert.match(reserved.error, /reserved/);
});

// ---- quantity validation (same rules as backend)
test("quantities: empty = 0, decimals ok, limit 10000 inclusive", () => {
  const { api } = load({ fetch: () => reply(200, {}) });
  const r = api.validateQuantities({ bottle: "7", bag: "", straw: "1.5", cup: "10000" });
  assert.strictEqual(r.ok, true);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(r.quantities)),
                         { bottle: 7, bag: 0, straw: 1.5, cup: 10000 });
});
test("quantities: negative, too large, non-numeric rejected", () => {
  const { api } = load({ fetch: () => reply(200, {}) });
  const r = api.validateQuantities({ bottle: "-1", bag: "10001", cup: "abc", wrap: "Infinity" });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.errors.bottle, "must not be negative");
  assert.match(r.errors.bag, /10000/);
  assert.strictEqual(r.errors.cup, "must be a number");
  assert.strictEqual(r.errors.wrap, "must be a number");
});
test("field errors use item names", () => {
  const { api } = load({ fetch: () => reply(200, {}) });
  // JSON round-trip: arrays from the vm sandbox are a different realm.
  assert.deepStrictEqual(JSON.parse(JSON.stringify(
    api.describeFieldErrors({ straw: "must not be negative" }, { straw: "Plastic straw" }))),
    ["Plastic straw: must not be negative"]);
});

// ---- requests
test("POST sends JSON body and content type", async () => {
  const { api, calls } = load({ fetch: () => reply(201, { record: { id: 1 } }) });
  const res = await api.saveFootprint("riya_22", { bottle: 7 });
  assert.strictEqual(res.record.id, 1);
  assert.strictEqual(calls[0].url, "/api/history");
  assert.strictEqual(calls[0].opts.method, "POST");
  assert.strictEqual(calls[0].opts.headers["Content-Type"], "application/json");
  assert.deepStrictEqual(JSON.parse(calls[0].opts.body),
                         { user_id: "riya_22", quantities: { bottle: 7 } });
});
test("query strings are URL-encoded", async () => {
  const { api, calls } = load({ fetch: () => reply(200, {}) });
  await api.getHistory("a&b=c", 5);
  assert.strictEqual(calls[0].url, "/api/history?user_id=a%26b%3Dc&limit=5");
  await api.getLeaderboard(false);
  assert.strictEqual(calls[1].url, "/api/campus/leaderboard?include_sample=false");
  await api.getSummary(true);
  assert.strictEqual(calls[2].url, "/api/campus/summary?include_sample=true");
});
test("400 validation error carries message and details", async () => {
  const { api } = load({ fetch: () => reply(400, {
    error: "Invalid weekly quantities.", status: 400, details: { bottle: "must not be negative" } }) });
  await assert.rejects(api.calculate({ bottle: -1 }), (e) =>
    e.kind === "http" && e.status === 400 && e.message === "Invalid weekly quantities." &&
    e.details.bottle === "must not be negative");
});
test("409 conflict message passed through", async () => {
  const { api } = load({ fetch: () => reply(409, { error: "This challenge is already completed." }) });
  await assert.rejects(api.completeChallenge("riya_22", 1),
    (e) => e.status === 409 && /already completed/.test(e.message));
});
test("500 and 503 give friendly messages, non-JSON body tolerated", async () => {
  const bad = load({ fetch: () => Promise.resolve({ ok: false, status: 500,
    text: () => Promise.resolve("<html>oops</html>") }) });
  await assert.rejects(bad.api.health(), (e) => e.status === 500 && /try again/i.test(e.message));
  const busy = load({ fetch: () => reply(503, { error: "busy" }) });
  await assert.rejects(busy.api.health(), (e) => e.status === 503 && /busy/i.test(e.message));
});
test("network failure gives server hint", async () => {
  const { api } = load({ fetch: () => Promise.reject(new TypeError("Failed to fetch")) });
  await assert.rejects(api.health(), (e) => e.kind === "network" && /127\.0\.0\.1:5000/.test(e.message));
});
test("timeout aborts and reports", async () => {
  const { api } = load({ fetch: (url, opts) => new Promise((resolve, reject) => {
    opts.signal.addEventListener("abort", () => {
      const err = new Error("aborted"); err.name = "AbortError"; reject(err);
    });
  }) });
  api.TIMEOUT_MS = 50;  // shorten for the test (default 8000 ms)
  const started = Date.now();
  await assert.rejects(api.health(), (e) => e.kind === "timeout");
  assert.ok(Date.now() - started < 2000, "timeout should fire quickly");
});
test("file:// page never calls fetch", async () => {
  const { api, calls } = load({ protocol: "file:", fetch: () => reply(200, {}) });
  await assert.rejects(api.health(), (e) => e.kind === "offline");
  assert.strictEqual(calls.length, 0);
});
test("passport 404 resolves to null, other errors still reject", async () => {
  const missing = load({ fetch: () => reply(404, { error: "No data" }) });
  assert.strictEqual(await missing.api.getPassport("new_user"), null);
  const broken = load({ fetch: () => reply(400, { error: "bad" }) });
  await assert.rejects(broken.api.getPassport("x"), (e) => e.status === 400);
});

(async () => {
  let failed = 0;
  for (const t of tests) {
    try { await t.fn(); console.log("ok   " + t.name); }
    catch (e) { failed++; console.log("FAIL " + t.name + "\n     " + (e && e.stack || e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
