"""django-mcp-server's stock MCPServerStreamableHttpView applies
IsAuthenticated uniformly to GET, POST, and DELETE. Observed in
production: claude.ai's connector opens the standalone SSE stream with
GET without attaching the Bearer token it just obtained via OAuth, even
though it does send it correctly on POST. Left alone, that GET 401s and
the connector reports a generic connection failure despite every actual
tool call being reachable and correct - this is the same bug CodeVault's
previous hand-rolled MCP endpoint had before being fixed the same way.

GET never returns any data here (DJANGO_MCP_GLOBAL_SERVER_CONFIG sets
stateless=True, so there's no server-initiated push to protect) and
DELETE is a stateless no-op, so neither has anything sensitive to guard -
only POST, where every tool call (read or write) actually happens, keeps
requiring a valid token.
"""

from mcp_server.views import MCPServerStreamableHttpView


class CodeVaultMCPView(MCPServerStreamableHttpView):
    def get_permissions(self):
        if self.request.method in ("GET", "DELETE"):
            return []
        return super().get_permissions()
