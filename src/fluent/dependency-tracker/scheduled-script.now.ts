import { ScheduledScript } from '@servicenow/sdk/core'

// Nightly full rebuild of the dependency graph, so the Chrome extension
// reads precomputed edges instead of scanning on every request. Kick it off
// on demand instead via POST /api/x_demo_claude_app/dependency_tracker/rescan
// (see rest-api.now.ts) - the extension's "Rescan" button calls that route.
ScheduledScript({
    $id: Now.ID['dependency-tracker-nightly-rebuild'],
    name: 'Dependency Tracker - Nightly Rebuild',
    script: Now.include('../../server/dependency-tracker/nightly-rebuild.server.js'),
    frequency: 'daily',
    executionTime: { hours: 2, minutes: 0 },
})
