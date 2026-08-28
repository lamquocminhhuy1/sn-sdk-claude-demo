"""Minimal CORS handling for the endpoints claude.ai's connector-setup UI
can call directly from the browser: OAuth discovery/registration/token
exchange and the MCP endpoint itself. None of these use cookies for auth
(bearer tokens, or a PKCE-protected authorization code that only the
party who completed /oauth/authorize/ would have) - so allowing any
origin to read the response doesn't expose anything an attacker couldn't
already get by calling the endpoint directly with the same credentials.

Without this, a browser-side fetch() from claude.ai's own origin can
still reach the server and get a normal response (it'll show up in this
server's logs as a completed request) while the browser silently
discards it before claude.ai's JS ever sees it - which looks, from here,
exactly like "everything succeeded and then nothing else happened".
"""

from django.http import HttpResponse

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
}


def cors(view_func):
    """Answers CORS preflight (OPTIONS) requests directly, and stamps the
    CORS headers onto every other response this view produces."""

    def wrapped(request, *args, **kwargs):
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = view_func(request, *args, **kwargs)
        for key, value in CORS_HEADERS.items():
            response[key] = value
        return response

    return wrapped
