from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.utils.module_loading import import_string
from oauth2_provider import urls as oauth2_urls
from rest_framework.permissions import IsAuthenticated

from vault import api, views
from vault.mcp_views import CodeVaultMCPView
from vault.oauth_metadata import urlpatterns as oauth_metadata_urlpatterns

# Mounting oauth2_provider's URLs at two different prefixes under `include()`
# calls that both claim the "oauth2_provider" namespace looks reasonable but
# is broken: Django only lets one of the two resolvers answer reverse()
# lookups for a shared namespace (system check urls.W005 warns about this
# exact case), so a view in the OTHER mount - e.g. OAuthServerMetadataView
# building "authorization_endpoint" via reverse("oauth2_provider:authorize")
# - silently gets NoReverseMatch and the field just vanishes from the
# discovery document. All of it goes in ONE include() at the site root
# instead: RFC 8414/9728 require the .well-known/ paths there anyway (see
# vault/oauth_metadata.py), and none of authorize/, token/, register/,
# applications/, authorized_tokens/ collide with this app's own routes -
# oidc_urlpatterns is the one part of oauth2_provider.urls deliberately
# left out, since its logout/ name would shadow our own and we don't use
# OIDC (no id_token issuance) anyway.
oauth2_all_urlpatterns = (
    oauth_metadata_urlpatterns
    + oauth2_urls.base_urlpatterns
    + oauth2_urls.dcr_urlpatterns
    + oauth2_urls.management_urlpatterns
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api-access/", views.api_access, name="api_access"),
    path("api-access/regenerate/", views.api_token_regenerate, name="api_token_regenerate"),
    path("api/v1/projects/", api.projects_collection, name="api_projects"),
    path("api/v1/projects/<slug:slug>/items/", api.items_collection, name="api_items"),
    path("api/v1/items/<uuid:uid>/", api.item_detail, name="api_item_detail"),
    # Same construction as mcp_server.urls itself, but using our
    # CodeVaultMCPView (exempts GET/DELETE from auth - see vault/mcp_views.py)
    # instead of the stock MCPServerStreamableHttpView.
    path(
        getattr(settings, "DJANGO_MCP_ENDPOINT", "mcp"),
        CodeVaultMCPView.as_view(
            permission_classes=[IsAuthenticated] if getattr(settings, "DJANGO_MCP_AUTHENTICATION_CLASSES", None) else [],
            authentication_classes=[
                import_string(cls) for cls in getattr(settings, "DJANGO_MCP_AUTHENTICATION_CLASSES", [])
            ],
        ),
        name="mcp_server_streamable_http_endpoint",
    ),
    path("", include((oauth2_all_urlpatterns, "oauth2_provider"), namespace="oauth2_provider")),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.project_list, name="project_list"),
    path("projects/new/", views.project_create, name="project_create"),
    path("p/<slug:slug>/", views.project_detail, name="project_detail"),
    path("p/<slug:slug>/edit/", views.project_edit, name="project_edit"),
    path("p/<slug:slug>/delete/", views.project_delete, name="project_delete"),
    path("p/<slug:slug>/deps/", views.project_dependencies, name="project_dependencies"),
    path("p/<slug:slug>/new/", views.item_create, name="item_create"),
    path("item/<uuid:uid>/", views.item_detail, name="item_detail"),
    path("item/<uuid:uid>/edit/", views.item_edit, name="item_edit"),
    path("item/<uuid:uid>/delete/", views.item_delete, name="item_delete"),
    path("item/<uuid:uid>/raw/", views.item_raw, name="item_raw"),
    path("media/<path:path>", views.serve_media, name="serve_media"),
]
