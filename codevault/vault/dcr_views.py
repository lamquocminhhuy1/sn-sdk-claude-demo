"""RFC 7591 doesn't require token_endpoint_auth_method in the registration
request. When it's omitted, django-oauth-toolkit's DynamicClientRegistrationView
defaults to "client_secret_basic" (a confidential client, secret required at
the token endpoint). Observed in production: claude.ai's connector registers
without this field and then never sends a client_secret back when exchanging
the authorization code - it only ever presents PKCE, exactly what a public
client does. Registered confidential, every one of its token exchanges fails
with invalid_client and the connector reports a generic "couldn't reach"
error despite discovery, registration, login and consent all having
succeeded.

Default an omitted token_endpoint_auth_method to "none" (public, PKCE-only)
instead, matching what these clients actually implement. A client that
explicitly asks for a confidential method (e.g. by sending
"client_secret_basic" itself) is still honored as confidential.
"""

import json

from oauth2_provider.views.dynamic_client_registration import DynamicClientRegistrationView


class CodeVaultDCRView(DynamicClientRegistrationView):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict) and "token_endpoint_auth_method" not in data:
            data["token_endpoint_auth_method"] = "none"
            request._body = json.dumps(data).encode("utf-8")
        return super().post(request, *args, **kwargs)
