"""OAuth 2.0 authorization server (RFC 6749 + PKCE + RFC 7591 dynamic
client registration + RFC 8414/9728 metadata discovery) - just enough of
it for claude.ai's "Add custom connector" flow to work against the remote
MCP endpoint at /mcp/.

claude.ai's connector UI always attempts OAuth for a custom remote MCP
server (a bare token in the URL, as mcp_server.mcp_endpoint uses, isn't
enough for that specific flow). The dance it drives:

1. It calls /mcp/ with no auth, gets a 401 + WWW-Authenticate pointing here.
2. GET /.well-known/oauth-protected-resource -> which authorization server.
3. GET /.well-known/oauth-authorization-server -> that server's endpoints.
4. POST /oauth/register/ -> registers itself as a client (no manual setup).
5. Opens /oauth/authorize/ in the user's browser -> our existing Django
   login (if needed) -> a consent screen -> redirects back with a code.
6. POST /oauth/token/ -> exchanges the code (+ PKCE verifier) for an
   access token, which it then sends as `Authorization: Bearer <token>`
   on every /mcp/ call.

This is a public-client flow (no client secret): the authorization code
is single-use and short-lived, and PKCE (S256) proves the token request
comes from whoever started the authorize step, so no secret is needed.
"""

import base64
import hashlib
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .cors import cors
from .mcp_server import fingerprint
from .models import OAuthAuthorizationCode, OAuthClient, OAuthToken

SCOPE = "codevault"


def _base_url(request):
    return request.build_absolute_uri("/")[:-1]


@cors
@require_GET
def protected_resource_metadata(request):
    base = _base_url(request)
    return JsonResponse(
        {
            "resource": base + reverse("mcp_endpoint_oauth"),
            "authorization_servers": [base],
        }
    )


@cors
@require_GET
def authorization_server_metadata(request):
    base = _base_url(request)
    return JsonResponse(
        {
            "issuer": base,
            "authorization_endpoint": base + reverse("oauth_authorize"),
            "token_endpoint": base + reverse("oauth_token"),
            "registration_endpoint": base + reverse("oauth_register"),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [SCOPE],
        }
    )


@csrf_exempt
@cors
@require_http_methods(["POST"])
def register(request):
    """Dynamic Client Registration (RFC 7591). Open registration - anyone
    can self-register a client, same trust model most public MCP servers
    use; the authorize screen is still gated behind the user's own login."""
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_client_metadata"}, status=400)

    redirect_uris = payload.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return JsonResponse(
            {"error": "invalid_redirect_uri", "error_description": "'redirect_uris' is required."},
            status=400,
        )

    client = OAuthClient.objects.create(
        client_name=(payload.get("client_name") or "")[:200],
        redirect_uris=redirect_uris,
    )
    print("[oauth-register] client_id={0} name={1!r} redirect_uris={2}".format(client.client_id, client.client_name, redirect_uris))
    return JsonResponse(
        {
            "client_id": client.client_id,
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status=201,
    )


def _redirect_with_params(uri, **params):
    from urllib.parse import urlencode

    joiner = "&" if "?" in uri else "?"
    return HttpResponseRedirect(uri + joiner + urlencode(params))


@login_required
def authorize(request):
    client_id = request.GET.get("client_id") or request.POST.get("client_id")
    redirect_uri = request.GET.get("redirect_uri") or request.POST.get("redirect_uri")
    state = request.GET.get("state") or request.POST.get("state") or ""
    code_challenge = request.GET.get("code_challenge") or request.POST.get("code_challenge")
    code_challenge_method = request.GET.get("code_challenge_method") or request.POST.get(
        "code_challenge_method", "S256"
    )
    scope = request.GET.get("scope") or request.POST.get("scope", SCOPE)

    try:
        client = OAuthClient.objects.get(client_id=client_id)
    except OAuthClient.DoesNotExist:
        return render(request, "vault/oauth_error.html", {"message": "Unknown client_id."}, status=400)

    if redirect_uri not in client.redirect_uris:
        return render(
            request, "vault/oauth_error.html", {"message": "redirect_uri doesn't match this client's registration."}, status=400
        )
    if not code_challenge or code_challenge_method != "S256":
        return _redirect_with_params(redirect_uri, error="invalid_request", state=state)

    if request.method == "POST":
        if request.POST.get("decision") == "approve":
            auth_code = OAuthAuthorizationCode.objects.create(
                client=client,
                user=request.user,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                scope=scope,
            )
            print(
                "[oauth-authorize] approved: client_id={0} user={1} code_fingerprint={2}".format(
                    client_id, request.user.username, fingerprint(auth_code.code)
                )
            )
            return _redirect_with_params(redirect_uri, code=auth_code.code, state=state)
        print("[oauth-authorize] denied: client_id={0} user={1}".format(client_id, request.user.username))
        return _redirect_with_params(redirect_uri, error="access_denied", state=state)

    return render(
        request,
        "vault/oauth_authorize.html",
        {
            "client": client,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "scope": scope,
        },
    )


def _pkce_matches(code_verifier, code_challenge):
    if not code_verifier:
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return computed == code_challenge


def _issue_token(client, user, scope):
    return OAuthToken.objects.create(client=client, user=user, scope=scope)


def _token_json(data, status=200):
    """RFC 6749 5.1: token endpoint responses (success or error) MUST carry
    Cache-Control: no-store and Pragma: no-cache - they contain, or relate
    to, credentials. A client enforcing this strictly could otherwise
    refuse to use a token response missing these."""
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _token_response(token):
    return _token_json(
        {
            "access_token": token.access_token,
            "token_type": "Bearer",
            "expires_in": int((token.expires_at - timezone.now()).total_seconds()),
            "refresh_token": token.refresh_token,
            "scope": token.scope,
        }
    )


@csrf_exempt
@cors
@require_http_methods(["POST"])
def token(request):
    if (request.content_type or "").startswith("application/json"):
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else {}
        except (ValueError, UnicodeDecodeError):
            return _token_json({"error": "invalid_request"}, status=400)
    else:
        data = request.POST

    grant_type = data.get("grant_type")
    print("[oauth-token] grant_type={0} client_id={1}".format(grant_type, data.get("client_id")))

    if grant_type == "authorization_code":
        code_value = data.get("code")
        redirect_uri = data.get("redirect_uri")
        client_id = data.get("client_id")
        code_verifier = data.get("code_verifier")

        try:
            auth_code = OAuthAuthorizationCode.objects.select_related("client", "user").get(code=code_value)
        except OAuthAuthorizationCode.DoesNotExist:
            print("[oauth-token] authorization_code: no such code (fingerprint={0})".format(fingerprint(code_value)))
            return _token_json({"error": "invalid_grant"}, status=400)

        reasons = []
        if auth_code.used:
            reasons.append("already used")
        if auth_code.is_expired:
            reasons.append("expired at {0}".format(auth_code.expires_at))
        if auth_code.client.client_id != client_id:
            reasons.append("client_id mismatch (code was for {0})".format(auth_code.client.client_id))
        if auth_code.redirect_uri != redirect_uri:
            reasons.append("redirect_uri mismatch (code was for {0!r})".format(auth_code.redirect_uri))
        if not _pkce_matches(code_verifier, auth_code.code_challenge):
            reasons.append("PKCE code_verifier doesn't match code_challenge")
        if reasons:
            print("[oauth-token] authorization_code rejected: " + "; ".join(reasons))
            return _token_json({"error": "invalid_grant"}, status=400)

        auth_code.used = True
        auth_code.save(update_fields=["used"])
        issued = _issue_token(auth_code.client, auth_code.user, auth_code.scope)
        print(
            "[oauth-token] issued: client_id={0} user={1} token_fingerprint={2} expires_at={3}".format(
                client_id, auth_code.user.username, fingerprint(issued.access_token), issued.expires_at
            )
        )
        return _token_response(issued)

    if grant_type == "refresh_token":
        refresh_value = data.get("refresh_token")
        client_id = data.get("client_id")
        try:
            old_token = OAuthToken.objects.select_related("client", "user").get(refresh_token=refresh_value)
        except OAuthToken.DoesNotExist:
            print("[oauth-token] refresh_token: no such refresh token (fingerprint={0})".format(fingerprint(refresh_value)))
            return _token_json({"error": "invalid_grant"}, status=400)
        if old_token.client.client_id != client_id:
            print("[oauth-token] refresh_token: client_id mismatch (token was for {0})".format(old_token.client.client_id))
            return _token_json({"error": "invalid_grant"}, status=400)

        issued = _issue_token(old_token.client, old_token.user, old_token.scope)
        old_token.delete()  # rotate: the used refresh token is no longer valid
        print(
            "[oauth-token] refreshed: client_id={0} user={1} new_token_fingerprint={2}".format(
                client_id, old_token.user.username, fingerprint(issued.access_token)
            )
        )
        return _token_response(issued)

    return _token_json({"error": "unsupported_grant_type"}, status=400)
