// POST /api/x_demo_claude_app/dependency_tracker/rescan
// Rebuilds the whole dependency graph synchronously and returns counts.
// Used by the nightly Scheduled Script and by the Chrome extension's
// "Rescan" button for on-demand refreshes during development.
(function process(request, response) {
    var scanner = new DependencyScanner();
    var result = scanner.rebuildGraph();
    response.setBody(result);
})(request, response);
