/**
 * Runs in every frame of every ServiceNow page (see manifest.json
 * content_scripts, all_frames: true) - this is what lets it detect the
 * record form even when it's loaded inside the classic UI16 gsft_main
 * iframe, whose own location.href already has the clean <table>.do?sys_id=
 * shape regardless of what the parent tab's nav_to.do wrapper URL says.
 *
 * Reports on every tick rather than only on change: the background service
 * worker keeps only the latest context per tab (last write wins), and the
 * periodic message doubles as a keepalive so a Manifest V3 service worker
 * idle-eviction doesn't leave the side panel showing stale data for a tab
 * the user is still sitting on.
 */
(function () {
    'use strict';

    function currentTitle() {
        // Best-effort record title: classic UI's breadcrumb / form header
        // holds it; workspace has other selectors. Fall back to document.title.
        var el =
            document.querySelector('#ni\\.breadcrumb .active_breadcrumb') ||
            document.querySelector('.form_header') ||
            document.querySelector('[data-name="header-title"]');
        var text = el ? el.textContent.trim() : '';
        return text || document.title || '';
    }

    function buildPayload() {
        var context = window.DepTrackerContextDetector.detectContext(window.location.href);
        if (!context) {
            return { type: 'DEP_TRACKER_CONTEXT', origin: window.location.origin, table: null, sysId: null, title: null };
        }
        return {
            type: 'DEP_TRACKER_CONTEXT',
            origin: window.location.origin,
            table: context.table,
            sysId: context.sysId,
            title: currentTitle()
        };
    }

    function report() {
        chrome.runtime.sendMessage(buildPayload()).catch(function () {
            // Extension page not listening yet (rare, right after install/reload) - ignore.
        });
    }

    chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
        if (message && message.type === 'DEP_TRACKER_REQUEST_CONTEXT') {
            sendResponse(buildPayload());
        }
    });

    report();
    setInterval(report, 800);
})();
