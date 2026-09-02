"""RFC 8414 / RFC 9728 metadata endpoints, overriding django-oauth-toolkit's
defaults for exactly one thing: the protected-resource "resource" value.

The stock OAuthProtectedResourceMetadataView derives the RFC 9728 `resource`
identifier from the request's own /.well-known/oauth-protected-resource URL,
which resolves to this site's origin - but our actual protected resource is
specifically /mcp/, not the origin root. Point it there explicitly so a
client that fetches /.well-known/oauth-protected-resource (root or the
/mcp-suffixed form claude.ai's client also probes) is told the right
resource URL.

These URLs are meant to be included under the same "oauth2_provider"
namespace as the rest of django-oauth-toolkit's urls (see config/urls.py) -
several of that app's other views reverse() these names internally (e.g.
the registration_endpoint field in the authorization-server metadata
document), so the namespace must match exactly.
"""

from django.urls import path, reverse
from oauth2_provider.views.metadata import OAuthProtectedResourceMetadataView, OAuthServerMetadataView


class CodeVaultResourceMetadataView(OAuthProtectedResourceMetadataView):
    def get_resource(self, request):
        return request.build_absolute_uri(reverse("mcp_server_streamable_http_endpoint"))


urlpatterns = [
    path(".well-known/oauth-authorization-server", OAuthServerMetadataView.as_view(), name="oauth-server-metadata"),
    path(
        ".well-known/oauth-authorization-server/<path:issuer_path>",
        OAuthServerMetadataView.as_view(),
        name="oauth-server-metadata-issuer",
    ),
    path(
        ".well-known/oauth-protected-resource",
        CodeVaultResourceMetadataView.as_view(),
        name="oauth-resource-metadata",
    ),
    path(
        ".well-known/oauth-protected-resource/<path:resource_path>",
        CodeVaultResourceMetadataView.as_view(),
        name="oauth-resource-metadata-path",
    ),
]
