/**
 * Service worker: opens the side panel from the toolbar icon, and keeps the
 * latest reported context (table/sysId/origin/title) per tab so the panel
 * can ask "what's the active tab looking at right now" without needing to
 * know which frame the record form actually loaded into.
 */

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(function () {});

// tabId (number) -> last reported context payload from content-script.js
var tabContexts = {};

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
    if (!message || !message.type) {
        return false;
    }

    if (message.type === 'DEP_TRACKER_CONTEXT' && sender.tab) {
        tabContexts[sender.tab.id] = message;
        // Best-effort push to an already-open side panel; if none is open
        // this simply has no listener and resolves to nothing.
        chrome.runtime.sendMessage({ type: 'DEP_TRACKER_CONTEXT_UPDATED', tabId: sender.tab.id, context: message }).catch(function () {});
        return false;
    }

    if (message.type === 'DEP_TRACKER_GET_CONTEXT') {
        sendResponse(tabContexts[message.tabId] || null);
        return true;
    }

    return false;
});

chrome.tabs.onRemoved.addListener(function (tabId) {
    delete tabContexts[tabId];
});
