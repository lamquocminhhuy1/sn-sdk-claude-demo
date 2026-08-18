# ServiceNow Dependency Tracker (Chrome extension)

Phase 1 of the Chrome extension idea: a thin client over the ServiceNow-side
Dependency Tracker (`../src/fluent/dependency-tracker/`). Open a Script
Include, Business Rule, Client Script, UI Page, UI Action, Scheduled Job,
Scripted REST resource, or Widget record and the side panel shows what it
**depends on** and what's **used by** it, from the precomputed graph — no
live scanning on your machine, no CORS setup needed.

## How it works

- **`context-detector.js`** — pure `URL -> {table, sysId}` detection (classic
  UI form URLs, the `nav_to.do` wrapper, and Agent Workspace record routes).
  No `chrome.*` calls, so it's unit-tested directly under Node —
  `node context-detector.test.js` covers 9 cases including new/unsaved
  records and list views, which must NOT match.
- **`content-script.js`** — injected into every frame of every
  `*.service-now.com` page (`all_frames: true`, so it runs inside the
  classic UI16 `gsft_main` form iframe too, not just the wrapping tab).
  Reports its detected context to the background worker roughly every
  800ms; the periodic report also keeps the Manifest V3 service worker from
  going idle while you're looking at a record.
- **`background.js`** — service worker. Opens the side panel on toolbar-icon
  click, keeps the latest reported context per tab, and answers the side
  panel's "what's the active tab looking at" query.
- **`sidepanel.html`/`.css`/`.js`** — fetches
  `GET {origin}/api/x_demo_claude_app/dependency_tracker/dependencies?table=...&sys_id=...`
  with `credentials: 'include'` and renders Depends On / Used By as
  clickable cards (clicking one navigates your ServiceNow tab there). The
  Rescan button calls the `POST .../rescan` route for an on-demand rebuild
  instead of waiting for the nightly job.

### Why a Chrome extension can call the API without CORS headaches

`host_permissions` in `manifest.json` (`https://*.service-now.com/*`) grants
the extension's own network requests an elevated, CORS-exempt channel to any
matching origin — including the session cookies for that origin, since the
user is already logged into ServiceNow in the same browser profile. A plain
web page trying the same cross-origin fetch would be blocked by ServiceNow's
CORS policy; the extension isn't, which is a big part of why this is a
reasonable architecture for an in-browser dev tool.

## Install (unpacked, for development)

1. Deploy the ServiceNow side first — see `../src/fluent/dependency-tracker/README.md`.
2. Chrome → `chrome://extensions` → enable **Developer mode** (top right).
3. **Load unpacked** → select this `chrome-extension/` folder.
4. Open any Script Include (or Business Rule, Client Script, ...) record on
   your instance, e.g. `https://your-instance.service-now.com/sys_script_include.do?sys_id=...`.
5. Click the extension's toolbar icon to open the side panel.

If your instance's records aren't scanned yet, the panel shows "This record
hasn't been scanned yet" with a **Rescan now** button.

## Scoping to one instance

`host_permissions` is set to `https://*.service-now.com/*` so the extension
works against any instance out of the box. Before distributing this beyond
your own machine, narrow it to your actual instance(s) — e.g.
`https://your-company.service-now.com/*` — in `manifest.json`.

## Known limitations (documented, not silently glossed over)

- **Studio's Application Explorer isn't detected.** Studio is a client-routed
  SPA (`/now/studio/...`) whose URL doesn't carry `table`/`sys_id` the way
  classic UI or Workspace do. `context-detector.js` correctly returns `null`
  for Studio URLs rather than guessing wrong — the panel shows the "open a
  record" prompt there. Supporting Studio would need to read its internal
  route state, which is out of scope for Phase 1.
- **One record type is a dependency target.** Only Script Includes are things
  other code calls by name (their `name` field is a real API identifier);
  Business Rules, Client Scripts, etc. can depend on things but nothing
  depends on them by name, so their "Used by" list is always empty. This
  mirrors the ServiceNow-side scanner, not a client-side limitation.
- **Detection is regex/identifier matching, not a JS parser.** Same caveat as
  everywhere else this technique is used in this project: it can't tell
  `CalcUtils` used as a real call apart from `CalcUtils` appearing in a
  comment or string, and can't currently narrow to "which function" was
  called — see the Phase 2 discussion (AST-based, per-function analysis) for
  that.

## Testing without a live instance

`context-detector.js` has no `chrome.*` dependency, so its URL-matching logic
was unit tested directly. The side panel's rendering, state transitions
(loading / no-context / not-scanned / error / result), and click-to-navigate
behavior were verified end-to-end with Playwright against a small mock REST
server standing in for the ServiceNow API (same JSON shape
`DependencyScanner.getDependencies()` returns) — the extension was loaded
unpacked into real Chromium, not just eyeballed.
