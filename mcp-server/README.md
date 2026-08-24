# codevault-mcp

MCP server that lets Claude read and push code into a running CodeVault
instance, instead of you copy-pasting it between your work laptop and Claude.

Wraps CodeVault's `GET`/`POST` API (see the instance's `/api-access/` page)
as five MCP tools:

| Tool | What it does |
|---|---|
| `list_projects` | List your CodeVault projects |
| `create_project` | Create a project, or return the existing one with that name |
| `list_items` | List the scripts/files in a project |
| `get_item` | Fetch one item's full code + metadata (pull) |
| `push_item` | Create or update a script/file (push) — matches an existing item by `uid`, then `identifier`, then `(kind + title)`, so pushing the same script twice updates it instead of duplicating it |

## Setup

```bash
cd mcp-server
npm install
```

You need two things from your CodeVault instance's **API Access** page
(`/api-access/`, logged in as yourself):

1. Its base URL, e.g. `https://youruser.pythonanywhere.com`
2. Your API token

### Claude Code

```bash
claude mcp add codevault \
  --env CODEVAULT_BASE_URL=https://youruser.pythonanywhere.com \
  --env CODEVAULT_API_TOKEN=your-token-here \
  -- node /absolute/path/to/mcp-server/index.js
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "codevault": {
      "command": "node",
      "args": ["/absolute/path/to/mcp-server/index.js"],
      "env": {
        "CODEVAULT_BASE_URL": "https://youruser.pythonanywhere.com",
        "CODEVAULT_API_TOKEN": "your-token-here"
      }
    }
  }
}
```

Restart Claude after editing the config. Ask it to "list my CodeVault
projects" to confirm the connection.

## Notes

- Screenshots (`kind=image`) aren't supported through the API or this
  server — push code and XML only.
- The token grants full read/write access to that user's projects; treat it
  like a password and regenerate it from `/api-access/` if it leaks.
