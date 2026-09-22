/**
 * job-scrubber-trigger — a Cloudflare Worker, not part of the static dashboard build.
 *
 * 2026-09-22: Jason wants "Run the finder" to actually run it, not send him to
 * GitHub to click a second button. GitHub Pages is a static site with no server
 * of its own, so the click needs somewhere to land that CAN hold a credential.
 * This Worker is that somewhere: it holds a GitHub token scoped to nothing but
 * "Actions: write" on this one repo, and does the one thing the button needs --
 * fire the workflow_dispatch event. Kit never sees or handles the token; Jason
 * pastes it into Cloudflare's own secret store when he sets this up (same as
 * config/.env for TYPESAFE_API_KEY).
 *
 * This page is public, so anyone could POST here -- worst case they trigger a
 * free scrape run (public repos get unlimited Actions minutes) that the
 * existing keep-previous guard in job_scraper.py protects the dashboard from.
 * No KV/rate-limit dependency in v1 to keep setup to one secret; add one later
 * if spam runs turn out to matter in practice.
 *
 * One-time setup (Cloudflare dashboard, no CLI needed):
 *   1. Workers & Pages -> Create -> Create Worker -> name it job-scrubber-trigger
 *   2. Paste this whole file in as the Worker's code, Deploy
 *   3. Settings -> Variables and Secrets -> Add secret
 *        name:  GH_DISPATCH_TOKEN
 *        value: a fine-grained GitHub PAT -- github.com/settings/personal-access-tokens/new
 *               Resource owner: jfunk9 | Repository access: Only job-scrubber
 *               Permissions: Actions -> Read and write (nothing else)
 *   4. Copy the Worker's URL (https://job-scrubber-trigger.<subdomain>.workers.dev)
 *      and hand it to Kit -- that's the only thing that goes back into index.html.
 */
export default {
  async fetch(request, env) {
    const cors = {
      "access-control-allow-origin": "https://jfunk9.github.io",
      "access-control-allow-methods": "POST, OPTIONS",
    };
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors });
    }
    if (request.method !== "POST") {
      return new Response("POST only", { status: 405, headers: cors });
    }

    const resp = await fetch(
      "https://api.github.com/repos/jfunk9/job-scrubber/actions/workflows/scrape.yml/dispatches",
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.GH_DISPATCH_TOKEN}`,
          "Accept": "application/vnd.github+json",
          "User-Agent": "job-scrubber-trigger-worker",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );

    if (resp.status === 204) {
      return new Response(JSON.stringify({ ok: true }), {
        headers: { ...cors, "content-type": "application/json" },
      });
    }
    const detail = await resp.text();
    return new Response(JSON.stringify({ ok: false, status: resp.status, detail }), {
      status: 502,
      headers: { ...cors, "content-type": "application/json" },
    });
  },
};
