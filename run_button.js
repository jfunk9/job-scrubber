// The "Run the finder" button's words, kept apart from index.html so tests/test_run_button.js can
// hold them. 2026-10-17 (loop 957): his press at about 15:2x started no run and the page said only
// "Couldn't start — opening GitHub", with no reason, for 20 seconds. Now every failure says what
// failed, and a yes from the starter counts only once GitHub shows a run born after the press.
(function (root) {
  function startMessage(res) {
    // res: {threw: "TypeError: Failed to fetch"} or {httpStatus, data}
    if (res.threw) {
      return { ok: false, text: "Couldn't reach the starter (" + res.threw + "). Opening GitHub: press Run workflow there." };
    }
    const d = res.data || {};
    if (res.httpStatus >= 200 && res.httpStatus < 300 && d.ok) {
      return { ok: true, text: "Starter said yes, checking GitHub…" };
    }
    const gh = d.status;
    let detail = "";
    try { detail = (JSON.parse(d.detail || "{}").message || ""); } catch (e) { detail = String(d.detail || "").slice(0, 80); }
    if (gh === 401 || gh === 403) {
      return { ok: false, text: "GitHub refused the starter's token (" + gh + (detail ? ": " + detail : "") + "). The token needs renewing. Opening GitHub." };
    }
    if (gh) {
      return { ok: false, text: "GitHub said " + gh + (detail ? ": " + detail : "") + ". Opening GitHub." };
    }
    return { ok: false, text: "The starter answered " + res.httpStatus + " with no reason. Opening GitHub." };
  }

  // runs: GitHub's /actions/runs list; pressedAt: Date.now() at the press.
  function runAppeared(runs, pressedAt) {
    return (runs || []).some(r => r.event === "workflow_dispatch" &&
      Date.parse(r.created_at) >= pressedAt - 10000);
  }

  const api = { startMessage, runAppeared };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RunButton = api;
})(this);
