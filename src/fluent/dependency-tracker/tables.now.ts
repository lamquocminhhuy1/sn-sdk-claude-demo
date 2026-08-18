import { Table, StringColumn, ReferenceColumn } from '@servicenow/sdk/core'

// One row per scanned ServiceNow component (Script Include, Business Rule,
// Client Script, UI Page, ...). `identifier` is only populated for
// components other code can call by name (currently: Script Include class
// name) - it is what DependencyScanner cross-matches against every other
// node's combined script text to build edges.
export const x_demo_claude_app_dep_node = Table({
    name: 'x_demo_claude_app_dep_node',
    label: 'Dependency Node',
    display: 'name',
    schema: {
        name: StringColumn({ label: 'Name', maxLength: 200, mandatory: true }),
        identifier: StringColumn({ label: 'Identifier', maxLength: 100 }),
        script_type: StringColumn({ label: 'Script Type', maxLength: 60 }),
        source_table: StringColumn({ label: 'Source Table', maxLength: 80, mandatory: true }),
        source_sys_id: StringColumn({ label: 'Source Sys ID', maxLength: 32, mandatory: true }),
    },
    index: [{ name: 'dep_node_source', unique: true, element: ['source_table', 'source_sys_id'] }],
    allowWebServiceAccess: true,
    createAccessControls: true,
    actions: { read: true, create: true, update: true, delete: true },
})

// A directed edge: from_node's code references to_node's identifier.
export const x_demo_claude_app_dep_edge = Table({
    name: 'x_demo_claude_app_dep_edge',
    label: 'Dependency Edge',
    schema: {
        from_node: ReferenceColumn({ label: 'From', referenceTable: 'x_demo_claude_app_dep_node' }),
        to_node: ReferenceColumn({ label: 'To', referenceTable: 'x_demo_claude_app_dep_node' }),
    },
    index: [{ name: 'dep_edge_pair', unique: true, element: ['from_node', 'to_node'] }],
    allowWebServiceAccess: true,
    createAccessControls: true,
    actions: { read: true, create: true, update: true, delete: true },
})
