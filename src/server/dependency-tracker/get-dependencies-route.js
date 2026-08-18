// GET /api/x_demo_claude_app/dependency_tracker/dependencies?table=<table>&sys_id=<sys_id>
// Returns the precomputed depends-on / used-by lists for one scanned record.
(function process(request, response) {
    var table = request.queryParams.table;
    var sysId = request.queryParams.sys_id;

    if (!table || !sysId) {
        response.setStatus(400);
        response.setBody({ error: 'table and sys_id query parameters are required' });
        return;
    }

    var scanner = new DependencyScanner();
    var result = scanner.getDependencies(table, sysId);

    if (!result.scanned) {
        response.setStatus(404);
    }
    response.setBody(result);
})(request, response);
