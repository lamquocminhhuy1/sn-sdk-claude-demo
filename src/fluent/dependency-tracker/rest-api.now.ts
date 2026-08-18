import { RestApi } from '@servicenow/sdk/core'

// Unversioned API: /api/x_demo_claude_app/dependency_tracker/...
// GET  /dependencies?table=<table>&sys_id=<sys_id>  -> depends-on / used-by for one record
// POST /rescan                                       -> rebuild the whole graph now
//
// Read by the "ServiceNow Dependency Tracker" Chrome extension's side panel.
RestApi({
    $id: Now.ID['dependency-tracker-api'],
    name: 'Dependency Tracker API',
    serviceId: 'dependency_tracker',
    consumes: 'application/json',
    produces: 'application/json',
    routes: [
        {
            $id: Now.ID['dependency-tracker-get-dependencies-route'],
            name: 'Get Dependencies',
            path: '/dependencies',
            method: 'GET',
            script: Now.include('../../server/dependency-tracker/get-dependencies-route.js'),
            authentication: true,
            authorization: true,
        },
        {
            $id: Now.ID['dependency-tracker-rescan-route'],
            name: 'Rescan',
            path: '/rescan',
            method: 'POST',
            script: Now.include('../../server/dependency-tracker/rescan-route.js'),
            authentication: true,
            authorization: true,
        },
    ],
})
