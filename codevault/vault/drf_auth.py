"""DRF authentication class letting the /mcp/ endpoint accept a plain
ApiToken (Authorization: Bearer <key>, from /api-access/) as an
alternative to a full OAuth2 access token. This is what Claude Code /
Claude Desktop's local MCP client (mcp-server/) uses - a simple static
bearer token, no browser-based OAuth dance needed for a client that isn't
running in a browser to begin with. claude.ai's own connector still goes
through OAuth2Authentication (see settings.DJANGO_MCP_AUTHENTICATION_CLASSES,
which lists both, tried in order).
"""

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import ApiToken


class ApiTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        key = header[len("Bearer "):].strip()
        try:
            token = ApiToken.objects.select_related("owner").get(key=key)
        except ApiToken.DoesNotExist:
            return None  # let OAuth2Authentication have a turn instead of failing outright
        return token.owner, token

    def authenticate_header(self, request):
        return "Bearer"
