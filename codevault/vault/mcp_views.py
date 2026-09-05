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

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from mcp_server.views import MCPServerStreamableHttpView

logger = logging.getLogger("vault.mcp")


class CodeVaultMCPView(MCPServerStreamableHttpView):
    def get_permissions(self):
        if self.request.method in ("GET", "DELETE"):
            return []
        return super().get_permissions()

    def post(self, request, *args, **kwargs):
        """Split a JSON-RPC batch (an array body) into individual calls.

        JSON-RPC 2.0 allows bundling several requests/notifications into
        one POST as a JSON array, and MCP clients commonly pair
        `initialize` with `notifications/initialized` this way. The
        installed mcp SDK's streamable HTTP transport only accepts a
        single message object per POST - reproduced directly: posting a
        two-message array gets back HTTP 400 with "Validation error: ...
        Input should be a valid dictionary or instance of JSONRPCRequest
        ... input_type=list". That 400 was observed in production right
        after a real, successful OAuth token exchange, which is exactly
        the point in the flow where a client sends its first batched
        initialize.

        Each element is handed to the SDK as its own request in turn
        (overwriting the DRF request's cached parsed body - `.data`
        checks that cache before re-parsing, so this doesn't touch the
        raw bytes or re-trigger content-type negotiation). Responses to
        notifications (no "id") are dropped, matching JSON-RPC batch
        semantics; everything else is collected into a JSON-RPC batch
        response array.

        Also no-ops a genuinely empty POST body. Observed in production,
        authenticated (a valid Bearer token, twice within 30ms of each
        other - a keepalive or connection-warmup ping is the likeliest
        explanation, not a real JSON-RPC call): there is no way to parse
        "" as a JSON-RPC message, and forwarding it either to DRF's own
        parser or on to the SDK 400s either way ("Parse error" /
        "Validation error" depending on which side rejects it first).
        Nothing about an empty body is actionable, so it's acknowledged
        the same way an all-notification batch already is instead of
        failing the connection over what's likely inconsequential.
        """
        if not request.body:
            return HttpResponse(status=202)

        if not isinstance(request.data, list):
            return super().post(request, *args, **kwargs)

        results = []
        for message in request.data:
            request._full_data = message
            response = super().post(request, *args, **kwargs)
            if isinstance(message, dict) and "id" in message:
                results.append(json.loads(response.content) if response.content else None)

        if not results:
            return HttpResponse(status=202)
        return JsonResponse(results, safe=False)

    def finalize_response(self, request, response, *args, **kwargs):
        """Point the 401 challenge at this resource's metadata document.

        MCP's authorization spec has the client learn which authorization
        server protects an MCP endpoint from the WWW-Authenticate challenge
        on the unauthenticated 401: RFC 9728 carries that as a
        resource_metadata parameter naming the protected resource metadata
        URL. django-oauth-toolkit's OAuth2Authentication only ever emits a
        bare `Bearer realm="api"`, leaving the client to guess the
        well-known path - a client that doesn't guess has nowhere to go and
        reports the server as unreachable.
        """
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code == 401:
            metadata_url = request.build_absolute_uri(reverse("oauth2_provider:oauth-resource-metadata"))
            response["WWW-Authenticate"] = 'Bearer realm="api", resource_metadata="{}"'.format(metadata_url)
        elif response.status_code == 400:
            # Kept as a safety net: if some other shape of request still
            # 400s, this logs the exact body instead of leaving us to
            # guess again.
            body = getattr(request, "body", b"")
            logger.warning(
                "POST /mcp/ 400: content-type=%r body=%r",
                request.headers.get("Content-Type"),
                body[:2000],
            )
        return response
