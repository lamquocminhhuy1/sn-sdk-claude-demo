/**
 * Pure URL -> { table, sysId } detection, with no chrome.* dependency so it
 * can run in the content script AND be unit tested directly under Node
 * (see context-detector.test.js). Loaded before content-script.js via
 * manifest.json's content_scripts "js" array (plain script concatenation,
 * no bundler / ES modules).
 */
(function (root) {
    'use strict';

    var SYS_ID_RE = '[0-9a-f]{32}';
    var TABLE_RE = '[a-z][a-z0-9_]*';

    // Classic UI form, direct navigation or bookmarked:
    //   https://instance.service-now.com/sys_script_include.do?sys_id=<32hex>
    var CLASSIC_FORM = new RegExp('^/(' + TABLE_RE + ')\\.do$');

    // Classic UI form reached through the nav_to.do wrapper (the top-level
    // tab URL when navigating via the application menu / a list link):
    //   .../nav_to.do?uri=sys_script_include.do%3Fsys_id%3D<32hex>
    var NAV_TO_URI = new RegExp('^(' + TABLE_RE + ')\\.do$');

    // Agent Workspace / UX record route:
    //   .../now/workspace/agent/record/sys_script_include/<32hex>
    //   .../now/nav/ui/classic/params/target/sys_script_include.do%3Fsys_id%3D<32hex>
    var WORKSPACE_RECORD = new RegExp('/record/(' + TABLE_RE + ')/(' + SYS_ID_RE + ')(?:[/?].*)?$');

    function fromClassicForm(pathname, search) {
        var match = CLASSIC_FORM.exec(pathname);
        if (!match) {
            return null;
        }
        var params = new URLSearchParams(search);
        var sysId = params.get('sys_id');
        if (!sysId || !new RegExp('^' + SYS_ID_RE + '$').test(sysId)) {
            return null;
        }
        return { table: match[1], sysId: sysId };
    }

    function fromNavToWrapper(pathname, search) {
        if (pathname !== '/nav_to.do') {
            return null;
        }
        var params = new URLSearchParams(search);
        var uri = params.get('uri');
        if (!uri) {
            return null;
        }
        var uriParts = uri.split('?');
        var tableMatch = NAV_TO_URI.exec(uriParts[0]);
        if (!tableMatch) {
            return null;
        }
        var innerParams = new URLSearchParams(uriParts[1] || '');
        var sysId = innerParams.get('sys_id');
        if (!sysId || !new RegExp('^' + SYS_ID_RE + '$').test(sysId)) {
            return null;
        }
        return { table: tableMatch[1], sysId: sysId };
    }

    function fromWorkspaceRoute(pathname) {
        var match = WORKSPACE_RECORD.exec(pathname);
        if (!match) {
            return null;
        }
        return { table: match[1], sysId: match[2] };
    }

    /**
     * @param {string} href - a full URL (location.href)
     * @returns {{table: string, sysId: string} | null}
     */
    function detectContext(href) {
        var url;
        try {
            url = new URL(href);
        } catch (err) {
            return null;
        }
        return (
            fromWorkspaceRoute(url.pathname) ||
            fromClassicForm(url.pathname, url.search) ||
            fromNavToWrapper(url.pathname, url.search) ||
            null
        );
    }

    var api = { detectContext: detectContext };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    } else {
        root.DepTrackerContextDetector = api;
    }
})(typeof window !== 'undefined' ? window : this);
