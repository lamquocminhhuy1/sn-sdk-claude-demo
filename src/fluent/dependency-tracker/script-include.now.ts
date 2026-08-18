import '@servicenow/sdk/global'
import { ScriptInclude } from '@servicenow/sdk/core'

// Scans this application's Script Includes, Business Rules, Client Scripts,
// UI Pages, UI Actions, Scheduled Jobs, Scripted REST resources, and Widgets
// for calls between them, and rebuilds the x_demo_claude_app_dep_node /
// x_demo_claude_app_dep_edge graph the REST API and Chrome extension read
// from. See src/server/dependency-tracker/dependency-scanner.js for the
// actual logic.
export const DependencyScanner = ScriptInclude({
    $id: Now.ID['DependencyScanner'],
    name: 'DependencyScanner',
    script: Now.include('../../server/dependency-tracker/dependency-scanner.js'),
    description:
        'Scans this application scope for calls between Script Includes, Business Rules, Client Scripts, UI Pages, UI Actions, Scheduled Jobs, Scripted REST resources, and Widgets, and rebuilds the dependency graph tables.',
    accessibleFrom: 'package_private',
})
