// Plain Node test, no framework/deps: `node context-detector.test.js`.
var assert = require('assert');
var detectContext = require('./context-detector.js').detectContext;

var SI_ID = 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4';
var BR_ID = 'b1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4';

var cases = [
    {
        name: 'classic form URL',
        url: 'https://dev12345.service-now.com/sys_script_include.do?sys_id=' + SI_ID,
        expect: { table: 'sys_script_include', sysId: SI_ID }
    },
    {
        name: 'classic form URL with extra params',
        url: 'https://dev12345.service-now.com/sys_script.do?sys_id=' + BR_ID + '&sysparm_view=default',
        expect: { table: 'sys_script', sysId: BR_ID }
    },
    {
        name: 'nav_to.do wrapper (top-level tab URL for UI16 iframe form)',
        url: 'https://dev12345.service-now.com/nav_to.do?uri=sys_script_client.do%3Fsys_id%3D' + SI_ID,
        expect: { table: 'sys_script_client', sysId: SI_ID }
    },
    {
        name: 'Agent Workspace record route',
        url: 'https://dev12345.service-now.com/now/workspace/agent/record/sys_ui_page/' + SI_ID,
        expect: { table: 'sys_ui_page', sysId: SI_ID }
    },
    {
        name: 'Agent Workspace record route with trailing query',
        url: 'https://dev12345.service-now.com/now/workspace/app/record/sys_ws_operation/' + SI_ID + '?view=my_view',
        expect: { table: 'sys_ws_operation', sysId: SI_ID }
    },
    {
        name: 'new/unsaved record (sys_id -1) is correctly rejected',
        url: 'https://dev12345.service-now.com/sys_script_include.do?sys_id=-1',
        expect: null
    },
    {
        name: 'list view (no sys_id) is correctly rejected',
        url: 'https://dev12345.service-now.com/sys_script_include_list.do',
        expect: null
    },
    {
        name: 'Studio SPA route (not yet supported) is correctly rejected, not mis-detected',
        url: 'https://dev12345.service-now.com/now/studio/application/abc/overview',
        expect: null
    },
    {
        name: 'URL shape matches regardless of host (host_permissions/content_scripts gate injection, not this function)',
        url: 'https://example.com/sys_script_include.do?sys_id=' + SI_ID,
        expect: { table: 'sys_script_include', sysId: SI_ID }
    }
];

var failures = 0;
cases.forEach(function (c) {
    var actual = detectContext(c.url);
    try {
        assert.deepStrictEqual(actual, c.expect);
        console.log('PASS  ' + c.name);
    } catch (err) {
        failures++;
        console.log('FAIL  ' + c.name);
        console.log('      expected: ' + JSON.stringify(c.expect));
        console.log('      actual:   ' + JSON.stringify(actual));
    }
});

if (failures > 0) {
    console.log('\n' + failures + ' failure(s)');
    process.exit(1);
}
console.log('\nAll ' + cases.length + ' cases passed.');
