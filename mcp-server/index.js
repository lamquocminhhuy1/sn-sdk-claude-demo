#!/usr/bin/env node
// MCP server exposing CodeVault's GET/POST API as tools for Claude, so
// Claude can list projects, pull existing code, and push new/updated code
// straight into a CodeVault instance instead of the user copy-pasting it.
//
// Config (env vars):
//   CODEVAULT_BASE_URL   e.g. https://youruser.pythonanywhere.com  (no trailing slash)
//   CODEVAULT_API_TOKEN  from that instance's /api-access/ page

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const BASE_URL = (process.env.CODEVAULT_BASE_URL || "").replace(/\/+$/, "");
const API_TOKEN = process.env.CODEVAULT_API_TOKEN || "";

if (!BASE_URL || !API_TOKEN) {
  console.error(
    "codevault-mcp: set CODEVAULT_BASE_URL and CODEVAULT_API_TOKEN " +
      "(find your token on the CodeVault instance's /api-access/ page)."
  );
  process.exit(1);
}

async function callApi(method, path, body) {
  const response = await fetch(BASE_URL + path, {
    method,
    headers: {
      Authorization: "Bearer " + API_TOKEN,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch (err) {
    throw new Error("CodeVault returned non-JSON response (HTTP " + response.status + "): " + text.slice(0, 300));
  }
  if (!response.ok) {
    throw new Error("CodeVault API error (HTTP " + response.status + "): " + (data.error || text));
  }
  return data;
}

function jsonResult(data) {
  return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
}

function errorResult(err) {
  return { content: [{ type: "text", text: "Error: " + err.message }], isError: true };
}

const server = new McpServer({ name: "codevault-mcp", version: "1.0.0" });

server.registerTool(
  "list_projects",
  {
    title: "List CodeVault projects",
    description: "List all projects (repos) stored in this user's CodeVault instance.",
    inputSchema: {},
  },
  async () => {
    try {
      return jsonResult(await callApi("GET", "/api/v1/projects/"));
    } catch (err) {
      return errorResult(err);
    }
  }
);

server.registerTool(
  "create_project",
  {
    title: "Create a CodeVault project",
    description:
      "Create a new project in CodeVault, or return the existing one if a project with " +
      "this name already exists (safe to call before pushing code without checking first).",
    inputSchema: {
      name: z.string().min(1).describe("Project name, e.g. 'Incident Auto-Assignment'"),
      description: z.string().optional(),
      scope_type: z
        .enum(["global", "scoped_app"])
        .optional()
        .describe("Where the ServiceNow code lives. Defaults to 'global'."),
      scope_name: z
        .string()
        .optional()
        .describe("Scoped app identifier, e.g. x_renin_ccr. Required when scope_type is 'scoped_app'."),
    },
  },
  async (args) => {
    try {
      return jsonResult(await callApi("POST", "/api/v1/projects/", args));
    } catch (err) {
      return errorResult(err);
    }
  }
);

server.registerTool(
  "list_items",
  {
    title: "List items in a CodeVault project",
    description: "List the scripts/files stored in one CodeVault project, optionally filtered by a search query.",
    inputSchema: {
      project_slug: z.string().min(1).describe("The project's slug, e.g. 'incident-auto-assignment'"),
      q: z.string().optional().describe("Filter by title or identifier substring"),
    },
  },
  async ({ project_slug, q }) => {
    try {
      const qs = q ? "?q=" + encodeURIComponent(q) : "";
      return jsonResult(await callApi("GET", "/api/v1/projects/" + encodeURIComponent(project_slug) + "/items/" + qs));
    } catch (err) {
      return errorResult(err);
    }
  }
);

server.registerTool(
  "get_item",
  {
    title: "Get a CodeVault item's full code",
    description: "Fetch one item's full source code and metadata by its uid (get code back out of CodeVault).",
    inputSchema: {
      uid: z.string().min(1).describe("The item's uid, from list_items"),
    },
  },
  async ({ uid }) => {
    try {
      return jsonResult(await callApi("GET", "/api/v1/items/" + encodeURIComponent(uid) + "/"));
    } catch (err) {
      return errorResult(err);
    }
  }
);

server.registerTool(
  "push_item",
  {
    title: "Push code into CodeVault",
    description:
      "Create or update a script/file in a CodeVault project (push code). Matches an existing item " +
      "to update by 'uid', then by 'identifier', then by (kind + title) - so pushing the same script " +
      "again updates it in place instead of creating a duplicate. Screenshots are not supported here.",
    inputSchema: {
      project_slug: z.string().min(1).describe("The project's slug to push into"),
      kind: z.enum(["code", "xml"]).default("code"),
      title: z.string().min(1).describe("Item title, e.g. the Script Include's class name"),
      uid: z.string().optional().describe("Update this exact item instead of matching by identifier/title"),
      identifier: z
        .string()
        .optional()
        .describe("API name other scripts call this by, e.g. a Script Include class name"),
      script_type: z
        .enum([
          "script_include",
          "business_rule",
          "client_script",
          "ui_page",
          "ui_action",
          "ui_macro",
          "scheduled_job",
          "fix_script",
          "rest_api",
          "widget",
          "other",
        ])
        .optional(),
      language: z.string().optional().describe("e.g. javascript, xml, html, css"),
      content: z.string().optional().describe("Main source code / XML content"),
      html_content: z.string().optional().describe("HTML part, for UI Pages / Widgets"),
      client_content: z.string().optional().describe("Client script part, for UI Pages / Widgets"),
      css_content: z.string().optional(),
      note: z.string().optional().describe("Context or instructions for whoever reads this later"),
      table_name: z.string().optional(),
      field_name: z.string().optional(),
      br_order: z.number().optional(),
      operations: z.string().optional(),
      condition: z.string().optional(),
      client_callable: z.boolean().optional(),
      api_endpoint: z.string().optional(),
      sub_type: z.string().optional(),
    },
  },
  async ({ project_slug, ...payload }) => {
    try {
      return jsonResult(
        await callApi("POST", "/api/v1/projects/" + encodeURIComponent(project_slug) + "/items/", payload)
      );
    } catch (err) {
      return errorResult(err);
    }
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
