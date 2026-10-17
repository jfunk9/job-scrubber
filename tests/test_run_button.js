// Loop 957 (2026-10-17): the Run the finder button's words, planted both ways.
// Run: node W:\AI\GitHub\job-scrubber\tests\test_run_button.js   (exit 0 = all pass)
const assert = require("assert");
const path = require("path");
const { startMessage, runAppeared } = require(path.join(__dirname, "..", "run_button.js"));

let n = 0;
function t(name, fn) { fn(); n++; console.log("ok", name); }

t("a real yes is the only ok", () => {
  assert.strictEqual(startMessage({ httpStatus: 200, data: { ok: true } }).ok, true);
  assert.strictEqual(startMessage({ httpStatus: 200, data: {} }).ok, false);
});
t("an unreachable starter says so", () => {
  const m = startMessage({ threw: "TypeError: Failed to fetch" });
  assert.strictEqual(m.ok, false);
  assert.match(m.text, /Couldn't reach the starter \(TypeError: Failed to fetch\)/);
});
t("an expired token is named", () => {
  const m = startMessage({ httpStatus: 502, data: { ok: false, status: 401, detail: '{"message":"Bad credentials"}' } });
  assert.strictEqual(m.ok, false);
  assert.match(m.text, /token \(401: Bad credentials\)/);
  assert.match(m.text, /renewing/);
});
t("another GitHub refusal shows its status", () => {
  const m = startMessage({ httpStatus: 502, data: { ok: false, status: 422, detail: "not json" } });
  assert.match(m.text, /GitHub said 422: not json/);
});
t("a run born after the press counts, an old one does not", () => {
  const pressed = Date.parse("2026-10-17T21:12:30Z");
  assert.strictEqual(runAppeared([{ event: "workflow_dispatch", created_at: "2026-10-17T21:12:39Z" }], pressed), true);
  assert.strictEqual(runAppeared([{ event: "workflow_dispatch", created_at: "2026-10-09T18:38:26Z" }], pressed), false);
  assert.strictEqual(runAppeared([{ event: "push", created_at: "2026-10-17T21:12:39Z" }], pressed), false);
  assert.strictEqual(runAppeared(undefined, pressed), false);
});
console.log(n + " of 5 passed");
