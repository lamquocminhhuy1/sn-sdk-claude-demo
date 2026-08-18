var DependencyScanner = Class.create();
DependencyScanner.prototype = {
    initialize: function () {
        this.nodeTable = 'x_demo_claude_app_dep_node';
        this.edgeTable = 'x_demo_claude_app_dep_edge';

        // Every table this scanner treats as source code. 'identifierField'
        // is only set for components other code calls by name - right now
        // that's just Script Includes (their 'name' IS the class name used
        // in 'new ClassName()' elsewhere), matching what ServiceNow already
        // stores, so no heuristic name-guessing is needed.
        this.sources = [
            { table: 'sys_script_include', fields: ['script'], label: 'Script Include', identifierField: 'name' },
            { table: 'sys_script', fields: ['script'], label: 'Business Rule', identifierField: null },
            { table: 'sys_script_client', fields: ['script'], label: 'Client Script', identifierField: null },
            { table: 'sys_ui_page', fields: ['html', 'client_script', 'processing_script'], label: 'UI Page', identifierField: null },
            { table: 'sys_ui_action', fields: ['script'], label: 'UI Action', identifierField: null },
            { table: 'sysauto_script', fields: ['script'], label: 'Scheduled Job', identifierField: null },
            { table: 'sys_ws_operation', fields: ['operation_script'], label: 'Scripted REST Resource', identifierField: null },
            { table: 'sp_widget', fields: ['script', 'client_script'], label: 'Widget', identifierField: null }
        ];

        this.minIdentifierLength = 3;
        this.ignoredIdentifiers = {
            'var': true, 'the': true, 'for': true, 'new': true,
            'get': true, 'set': true, 'run': true, 'current': true, 'previous': true
        };
    },

    /**
     * Rebuilds the entire dependency graph for this application scope:
     * wipes x_demo_claude_app_dep_node / _dep_edge, re-scans every
     * configured table, and re-derives edges by cross-matching identifiers
     * against every other node's combined script text.
     * @returns {Object} { nodes: <count>, edges: <count> }
     */
    rebuildGraph: function () {
        var scopeSysId = this._getScopeSysId();
        var nodes = [];
        var s, gr;

        this._wipeTable(this.edgeTable);
        this._wipeTable(this.nodeTable);

        for (s = 0; s < this.sources.length; s++) {
            var source = this.sources[s];
            gr = new GlideRecord(source.table);
            if (scopeSysId) {
                gr.addQuery('sys_scope', scopeSysId);
            }
            gr.query();
            while (gr.next()) {
                var code = this._combineFields(gr, source.fields);
                if (!code) {
                    continue;
                }
                var identifier = source.identifierField ? gr.getValue(source.identifierField) : '';
                var nodeSysId = this._insertNode(gr, source, identifier);
                nodes.push({ sysId: nodeSysId, identifier: identifier, code: code });
            }
        }

        var edgeCount = this._buildEdges(nodes);

        gs.info('DependencyScanner: rebuilt graph - ' + nodes.length + ' nodes, ' + edgeCount + ' edges');
        return { nodes: nodes.length, edges: edgeCount };
    },

    /**
     * Looks up one previously-scanned record by (table, sys_id) and returns
     * what it depends on and what depends on it.
     * @param {string} table
     * @param {string} sysId
     * @returns {Object} { scanned, node, dependsOn: [], usedBy: [] }
     */
    getDependencies: function (table, sysId) {
        var nodeGr = new GlideRecord(this.nodeTable);
        nodeGr.addQuery('source_table', table);
        nodeGr.addQuery('source_sys_id', sysId);
        nodeGr.query();
        if (!nodeGr.next()) {
            return { scanned: false, node: null, dependsOn: [], usedBy: [] };
        }

        var node = this._describeNode(nodeGr);
        var nodeSysId = nodeGr.getUniqueValue();

        return {
            scanned: true,
            node: node,
            dependsOn: this._relatedNodes(this.edgeTable, 'from_node', nodeSysId, 'to_node'),
            usedBy: this._relatedNodes(this.edgeTable, 'to_node', nodeSysId, 'from_node')
        };
    },

    _getScopeSysId: function () {
        var gr = new GlideRecord('sys_scope');
        gr.addQuery('scope', gs.getCurrentScopeName());
        gr.query();
        if (gr.next()) {
            return gr.getUniqueValue();
        }
        return null;
    },

    _wipeTable: function (table) {
        var gr = new GlideRecord(table);
        gr.query();
        gr.deleteMultiple();
    },

    _combineFields: function (gr, fields) {
        var parts = [];
        var i, value;
        for (i = 0; i < fields.length; i++) {
            value = gr.getValue(fields[i]);
            if (value) {
                parts.push(value);
            }
        }
        return parts.join('\n');
    },

    _insertNode: function (sourceGr, source, identifier) {
        var nodeGr = new GlideRecord(this.nodeTable);
        nodeGr.initialize();
        nodeGr.setValue('name', sourceGr.getValue('name') || sourceGr.getDisplayValue());
        nodeGr.setValue('identifier', identifier || '');
        nodeGr.setValue('script_type', source.label);
        nodeGr.setValue('source_table', source.table);
        nodeGr.setValue('source_sys_id', sourceGr.getUniqueValue());
        return nodeGr.insert();
    },

    _buildEdges: function (nodes) {
        var edgeCount = 0;
        var t, f, target, from, pattern;

        for (t = 0; t < nodes.length; t++) {
            target = nodes[t];
            if (!target.identifier || target.identifier.length < this.minIdentifierLength) {
                continue;
            }
            if (this.ignoredIdentifiers[target.identifier.toLowerCase()]) {
                continue;
            }
            pattern = new RegExp('\\b' + this._escapeRegExp(target.identifier) + '\\b');

            for (f = 0; f < nodes.length; f++) {
                if (f === t) {
                    continue;
                }
                from = nodes[f];
                if (pattern.test(from.code)) {
                    var edgeGr = new GlideRecord(this.edgeTable);
                    edgeGr.initialize();
                    edgeGr.setValue('from_node', from.sysId);
                    edgeGr.setValue('to_node', target.sysId);
                    edgeGr.insert();
                    edgeCount++;
                }
            }
        }
        return edgeCount;
    },

    _escapeRegExp: function (text) {
        return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    },

    _describeNode: function (gr) {
        return {
            name: gr.getValue('name'),
            identifier: gr.getValue('identifier'),
            scriptType: gr.getValue('script_type'),
            sourceTable: gr.getValue('source_table'),
            sourceSysId: gr.getValue('source_sys_id')
        };
    },

    _relatedNodes: function (edgeTable, matchField, nodeSysId, otherField) {
        var results = [];
        var gr = new GlideRecord(edgeTable);
        gr.addQuery(matchField, nodeSysId);
        gr.query();
        while (gr.next()) {
            results.push({
                name: gr.getValue(otherField + '.name'),
                identifier: gr.getValue(otherField + '.identifier'),
                scriptType: gr.getValue(otherField + '.script_type'),
                sourceTable: gr.getValue(otherField + '.source_table'),
                sourceSysId: gr.getValue(otherField + '.source_sys_id')
            });
        }
        return results;
    },

    type: 'DependencyScanner'
};
