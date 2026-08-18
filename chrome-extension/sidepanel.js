(function () {
    'use strict';

    var API_PATH = '/api/x_demo_claude_app/dependency_tracker';

    var currentTabId = null;
    var currentContext = null; // { origin, table, sysId, title }

    var els = {
        loading: document.getElementById('state-loading'),
        noContext: document.getElementById('state-no-context'),
        notScanned: document.getElementById('state-not-scanned'),
        notScannedTitle: document.getElementById('not-scanned-title'),
        error: document.getElementById('state-error'),
        errorText: document.getElementById('error-text'),
        result: document.getElementById('state-result'),
        recordBadge: document.getElementById('record-badge'),
        recordName: document.getElementById('record-name'),
        dependsList: document.getElementById('depends-list'),
        dependsCount: document.getElementById('depends-count'),
        usedByList: document.getElementById('usedby-list'),
        usedByCount: document.getElementById('usedby-count'),
        rescanBtn: document.getElementById('rescan-btn'),
        rescanBtn2: document.getElementById('rescan-btn-2')
    };

    function showState(name) {
        ['loading', 'noContext', 'notScanned', 'error', 'result'].forEach(function (key) {
            var el = key === 'result' ? els.result : els[key];
            el.hidden = key !== name;
        });
    }

    function badgeType(scriptType) {
        return (scriptType || '').toLowerCase().replace(/\s+/g, '_');
    }

    function renderList(listEl, countEl, items, emptyLabel) {
        listEl.innerHTML = '';
        countEl.textContent = '(' + items.length + ')';
        if (items.length === 0) {
            var li = document.createElement('li');
            li.className = 'empty';
            li.textContent = emptyLabel;
            listEl.appendChild(li);
            return;
        }
        items.forEach(function (item) {
            var li = document.createElement('li');

            var badge = document.createElement('span');
            badge.className = 'badge ' + badgeType(item.scriptType);
            badge.textContent = item.scriptType || '';

            var name = document.createElement('span');
            name.className = 'name';
            name.textContent = item.name || '(untitled)';

            li.appendChild(badge);
            li.appendChild(name);
            li.title = 'Open in ServiceNow';
            li.addEventListener('click', function () {
                if (currentContext && currentContext.origin && item.sourceTable && item.sourceSysId) {
                    chrome.tabs.update(currentTabId, {
                        url: currentContext.origin + '/' + item.sourceTable + '.do?sys_id=' + item.sourceSysId
                    });
                }
            });
            listEl.appendChild(li);
        });
    }

    function renderResult(data) {
        showState('result');
        els.recordBadge.className = 'badge ' + badgeType(data.node.scriptType);
        els.recordBadge.textContent = data.node.scriptType || '';
        els.recordName.textContent = data.node.name || '';
        renderList(els.dependsList, els.dependsCount, data.dependsOn, 'Nothing detected.');
        renderList(els.usedByList, els.usedByCount, data.usedBy, 'Nothing detected.');
    }

    function fetchDependencies(context) {
        showState('loading');
        var url =
            context.origin + API_PATH + '/dependencies?table=' + encodeURIComponent(context.table) +
            '&sys_id=' + encodeURIComponent(context.sysId);

        fetch(url, { credentials: 'include', headers: { Accept: 'application/json' } })
            .then(function (response) {
                if (response.status === 404) {
                    return response.json().then(function () {
                        showState('notScanned');
                        els.notScannedTitle.textContent = context.title || context.table;
                    });
                }
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.json().then(renderResult);
            })
            .catch(function (err) {
                showState('error');
                els.errorText.textContent = 'Could not load dependencies: ' + err.message;
            });
    }

    function applyContext(context) {
        currentContext = context;
        if (!context || !context.table || !context.sysId) {
            showState('noContext');
            return;
        }
        fetchDependencies(context);
    }

    function loadForActiveTab() {
        chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
            var tab = tabs[0];
            if (!tab) {
                showState('noContext');
                return;
            }
            currentTabId = tab.id;
            chrome.runtime.sendMessage({ type: 'DEP_TRACKER_GET_CONTEXT', tabId: tab.id }, function (context) {
                applyContext(context);
            });
        });
    }

    function rescan() {
        if (!currentContext || !currentContext.origin) {
            return;
        }
        showState('loading');
        fetch(currentContext.origin + API_PATH + '/rescan', {
            method: 'POST',
            credentials: 'include',
            headers: { Accept: 'application/json' }
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.json();
            })
            .then(function () {
                fetchDependencies(currentContext);
            })
            .catch(function (err) {
                showState('error');
                els.errorText.textContent = 'Rescan failed: ' + err.message;
            });
    }

    els.rescanBtn.addEventListener('click', rescan);
    els.rescanBtn2.addEventListener('click', rescan);

    chrome.tabs.onActivated.addListener(function (activeInfo) {
        currentTabId = activeInfo.tabId;
        chrome.runtime.sendMessage({ type: 'DEP_TRACKER_GET_CONTEXT', tabId: activeInfo.tabId }, function (context) {
            applyContext(context);
        });
    });

    chrome.runtime.onMessage.addListener(function (message) {
        if (message && message.type === 'DEP_TRACKER_CONTEXT_UPDATED' && message.tabId === currentTabId) {
            // Avoid re-fetching on every 800ms heartbeat: only react when the
            // (table, sysId) pair actually changed.
            var next = message.context;
            var changed =
                !currentContext ||
                currentContext.table !== next.table ||
                currentContext.sysId !== next.sysId;
            if (changed) {
                applyContext(next);
            } else {
                currentContext = next; // keep title/origin fresh
            }
        }
    });

    showState('loading');
    loadForActiveTab();
})();
