"""Drive the whole claude.ai connector flow against this deployment's own
code and database, and report which step breaks.

Every step below is what claude.ai's connector actually does when you add a
custom connector: discovery, dynamic client registration, the browser
authorize + consent screen, the PKCE token exchange, and finally an
authenticated MCP call. It runs through Django's test client rather than
over the network, so it works on a PythonAnywhere console with no outbound
access - but it hits the real URLconf, the real views and the real
database, with the same X-Forwarded-Proto a request through the TLS proxy
carries.

    python manage.py check_mcp_oauth --host tester68.pythonanywhere.com

Registrations it creates are deleted again before it exits; nothing else is
written, and the only tools it calls are read-only.
"""

import base64
import hashlib
import json
import re
import secrets
from urllib.parse import parse_qs, urlencode, urlparse

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.urls import reverse

REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
MCP_ACCEPT = "application/json, text/event-stream"


class Failure(Exception):
    pass


class Command(BaseCommand):
    help = "Run claude.ai's connector flow end to end against this deployment and report where it breaks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            required=True,
            help="Public hostname of this deployment, e.g. tester68.pythonanywhere.com",
        )
        parser.add_argument(
            "--user",
            default=None,
            help="Username to authorize as. Defaults to the first superuser.",
        )

    # ------------------------------------------------------------------ util

    def ok(self, label, detail=""):
        self.stdout.write(self.style.SUCCESS("[OK]   " + label) + (("  " + detail) if detail else ""))

    def fail(self, label, detail):
        self.stdout.write(self.style.ERROR("[FAIL] " + label))
        self.stdout.write("       " + str(detail)[:1500])
        raise Failure(label)

    def request(self, method, path, **kwargs):
        # A request arriving through PythonAnywhere's TLS proxy carries the
        # original scheme here; without it every absolute URL the server
        # builds comes back as http:// and clients reject the flow.
        kwargs.setdefault("HTTP_HOST", self.host)
        kwargs.setdefault("HTTP_X_FORWARDED_PROTO", "https")
        return getattr(self.client, method)(path, **kwargs)

    # ------------------------------------------------------------------ main

    def handle(self, *args, **options):
        self.host = options["host"]
        self.client = Client()

        User = get_user_model()
        if options["user"]:
            user = User.objects.filter(username=options["user"]).first()
            if user is None:
                raise CommandError("No such user: " + options["user"])
        else:
            user = User.objects.filter(is_superuser=True).order_by("id").first()
            if user is None:
                raise CommandError("No superuser found; pass --user <username>.")
        self.stdout.write("Authorizing as: " + user.get_username() + "\n")

        application = None
        try:
            client_data = self.step_discovery()
            application, client_data = self.step_register()
            code, verifier = self.step_authorize(user, client_data)
            access_token = self.step_token(client_data, code, verifier)
            self.step_mcp(access_token)
        except Failure:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Flow stopped at the step above."))
            return
        finally:
            if application is not None:
                application.delete()
                self.stdout.write("\n(cleaned up the test client registration)")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("ALL STEPS PASSED - the server side of the connector flow is working."))

    # ----------------------------------------------------------- 1. discovery

    def step_discovery(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Discovery"))

        response = self.request(
            "post",
            reverse("mcp_server_streamable_http_endpoint"),
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
            content_type="application/json",
            HTTP_ACCEPT=MCP_ACCEPT,
        )
        if response.status_code != 401:
            self.fail(
                "unauthenticated POST /mcp/ should be 401 so the client knows to start OAuth",
                "got " + str(response.status_code),
            )
        challenge = response.get("WWW-Authenticate", "")
        if "resource_metadata=" not in challenge:
            self.fail(
                "the 401 challenge doesn't name the resource metadata document",
                "WWW-Authenticate: " + (challenge or "(header missing)")
                + " - MCP clients read resource_metadata from here to find the authorization server",
            )
        self.ok("unauthenticated POST /mcp/ -> 401", challenge)

        for path in [
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
        ]:
            response = self.request("get", path)
            if response.status_code != 200:
                self.fail(path, "status " + str(response.status_code))
            body = response.json()
            if not body.get("resource", "").startswith("https://"):
                self.fail(path + " advertises a non-https resource", body)
            self.ok(path, body["resource"])

        for path in [
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-authorization-server/mcp",
        ]:
            response = self.request("get", path)
            if response.status_code != 200:
                self.fail(path, "status " + str(response.status_code))
            body = response.json()
            missing = [
                key
                for key in ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint")
                if key not in body
            ]
            if missing:
                self.fail(path + " is missing endpoints", "missing: " + ", ".join(missing))
            insecure = [k for k, v in body.items() if isinstance(v, str) and v.startswith("http://")]
            if insecure:
                self.fail(path + " advertises http:// endpoints", "insecure: " + ", ".join(insecure))
            self.ok(path, "all endpoints present and https")

        return None

    # -------------------------------------------------------- 2. registration

    def step_register(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Dynamic client registration"))

        # claude.ai omits token_endpoint_auth_method; the server has to read
        # that as a public, PKCE-only client (see vault/dcr_views.py).
        response = self.request(
            "post",
            reverse("oauth2_provider:dcr-register"),
            data=json.dumps({"client_name": "connector self-check", "redirect_uris": [REDIRECT_URI]}),
            content_type="application/json",
        )
        if response.status_code != 201:
            self.fail("POST /register/", "status " + str(response.status_code) + " " + response.content.decode())
        data = response.json()

        if data.get("token_endpoint_auth_method") != "none":
            self.fail(
                "registration produced a confidential client",
                "token_endpoint_auth_method=" + repr(data.get("token_endpoint_auth_method"))
                + " - claude.ai never sends a client_secret, so its token exchange will 401",
            )
        self.ok("POST /register/ -> public client", data["client_id"])

        from oauth2_provider.models import get_application_model

        application = get_application_model().objects.get(client_id=data["client_id"])
        return application, data

    # ----------------------------------------------------------- 3. authorize

    def step_authorize(self, user, client_data):
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. Authorize + consent"))

        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(8)

        self.client.force_login(user)
        response = self.request(
            "get",
            reverse("oauth2_provider:authorize"),
            data={
                "response_type": "code",
                "client_id": client_data["client_id"],
                "redirect_uri": REDIRECT_URI,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "codevault",
            },
        )
        if response.status_code != 200:
            self.fail(
                "GET /authorize/ (consent screen)",
                "status " + str(response.status_code) + " " + response.content.decode()[:600],
            )
        self.ok("GET /authorize/ renders the consent screen")

        # Submit exactly the hidden fields the rendered form carries, the way
        # the user's browser would when they click Authorize.
        hidden = dict(re.findall(r'name="(\w+)"\s+value="([^"]*)"', response.content.decode()))
        response = self.request(
            "post",
            reverse("oauth2_provider:authorize"),
            data=dict(hidden, allow="Authorize"),
        )
        if response.status_code != 302:
            self.fail(
                "POST /authorize/ (clicking Authorize)",
                "status " + str(response.status_code) + " " + response.content.decode()[:600],
            )
        location = response["Location"]
        if not location.startswith(REDIRECT_URI):
            self.fail("consent redirected somewhere unexpected", location)
        qs = parse_qs(urlparse(location).query)
        if "code" not in qs:
            self.fail("no authorization code in the redirect", location)
        self.ok("POST /authorize/ -> redirect with code", "state matches" if qs.get("state", [None])[0] == state else "STATE MISMATCH")

        return qs["code"][0], verifier

    # --------------------------------------------------------------- 4. token

    def step_token(self, client_data, code, verifier):
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. Token exchange (PKCE, no client_secret)"))

        response = self.request(
            "post",
            reverse("oauth2_provider:token"),
            data=urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": client_data["client_id"],
                    "code_verifier": verifier,
                }
            ),
            content_type="application/x-www-form-urlencoded",
        )
        if response.status_code != 200:
            self.fail(
                "POST /token/",
                "status " + str(response.status_code) + " " + response.content.decode(),
            )
        body = response.json()
        if "access_token" not in body:
            self.fail("POST /token/ returned no access_token", body)
        self.ok("POST /token/ -> access token", "scope=" + str(body.get("scope")))
        return body["access_token"]

    # ----------------------------------------------------------------- 5. mcp

    def step_mcp(self, access_token):
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Authenticated MCP calls"))

        def rpc(method, params=None, msg_id=1):
            payload = {"jsonrpc": "2.0", "method": method}
            if msg_id is not None:
                payload["id"] = msg_id
            if params is not None:
                payload["params"] = params
            return self.request(
                "post",
                reverse("mcp_server_streamable_http_endpoint"),
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_ACCEPT=MCP_ACCEPT,
                HTTP_AUTHORIZATION="Bearer " + access_token,
            )

        response = rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "check_mcp_oauth", "version": "1.0.0"},
            },
        )
        if response.status_code != 200 or "error" in response.json():
            self.fail("initialize", "status " + str(response.status_code) + " " + response.content.decode()[:800])
        self.ok("initialize")

        response = rpc("tools/list", msg_id=2)
        if response.status_code != 200:
            self.fail("tools/list", "status " + str(response.status_code) + " " + response.content.decode()[:800])
        body = response.json()
        if "error" in body:
            self.fail("tools/list", body["error"])
        names = sorted(tool["name"] for tool in body["result"]["tools"])
        self.ok("tools/list", ", ".join(names))

        response = rpc("tools/call", {"name": "list_projects", "arguments": {}}, msg_id=3)
        body = response.json()
        if response.status_code != 200 or "error" in body:
            self.fail("tools/call list_projects", response.content.decode()[:800])
        self.ok("tools/call list_projects", body["result"]["content"][0]["text"][:200])
