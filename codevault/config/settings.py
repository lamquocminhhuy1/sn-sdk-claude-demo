"""
Django settings for the CodeVault project.

Designed to run locally (DEBUG on) and on PythonAnywhere (free or paid tier)
with configuration coming from environment variables where it matters.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY: on PythonAnywhere, set a real secret key in the WSGI file or a
# .env-style mechanism. The fallback below is only meant for local development.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-only-insecure-key-change-me-on-pythonanywhere",
)

# DEBUG defaults to True locally; set DJANGO_DEBUG=0 in production.
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    ".pythonanywhere.com",
]
_extra_host = os.environ.get("DJANGO_ALLOWED_HOST")
if _extra_host:
    ALLOWED_HOSTS.append(_extra_host)

CSRF_TRUSTED_ORIGINS = [
    "https://*.pythonanywhere.com",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "oauth2_provider",
    "mcp_server",
    "vault",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Media files (screenshots, xml uploads). These are served through a
# login-protected Django view (vault.views.serve_media), NOT as public static
# files — do not add a /media/ static mapping on PythonAnywhere.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Keep uploads reasonable for the free-tier 512 MB disk quota.
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 20 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "project_list"
LOGOUT_REDIRECT_URL = "login"

# --- Remote MCP server (django-mcp-server) + OAuth 2.0 (django-oauth-toolkit) ---
# Together these serve claude.ai's "Add custom connector" flow at /mcp/:
# discovery -> dynamic client registration -> authorize+consent -> token
# exchange (PKCE) -> Bearer-authenticated MCP tool calls. See vault/mcp.py
# for the tool definitions and vault/drf_auth.py for the extra bearer-token
# auth path that lets Claude Code/Desktop's local MCP client authenticate
# with a plain ApiToken instead of going through the full OAuth dance.
DJANGO_MCP_ENDPOINT = "mcp/"
DJANGO_MCP_AUTHENTICATION_CLASSES = [
    "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
    "vault.drf_auth.ApiTokenAuthentication",
]
# Stateless: no Mcp-Session-Id required/issued. Every tool call here is a
# quick synchronous DB read/write with no server-initiated messages, so
# there is no session state worth tracking, and requiring a session ID
# is one more thing an MCP client can get subtly wrong.
DJANGO_MCP_GLOBAL_SERVER_CONFIG = {"stateless": True}

OAUTH2_PROVIDER = {
    "SCOPES": {"codevault": "Read and write your CodeVault projects"},
    "DEFAULT_SCOPES": ["codevault"],
    "PKCE_REQUIRED": True,
    # Open registration: claude.ai self-registers a client before the user
    # has logged in anywhere, same trust model most public MCP servers use.
    # The actual access grant is still gated behind the user's own login at
    # the /authorize/ consent screen.
    "DCR_ENABLED": True,
    "DCR_REGISTRATION_PERMISSION_CLASSES": ("oauth2_provider.dcr.AllowAllDCRPermission",),
    # claude.ai registers a public, PKCE-only client (no client_secret ever
    # stored or sent) - advertise that explicitly, and narrow the advertised
    # grant types to only the two this app actually wants supported. Neither
    # setting changes what the server *accepts* (DCR and the token endpoint
    # don't consult these), just what discovery *advertises*, so this is
    # purely about giving a spec-compliant client an accurate picture.
    "OAUTH2_TOKEN_ENDPOINT_AUTH_METHODS_SUPPORTED": ["none", "client_secret_basic", "client_secret_post"],
    "OAUTH2_GRANT_TYPES_SUPPORTED": ["authorization_code", "refresh_token"],
}

# Django sets Cross-Origin-Opener-Policy: same-origin on every response by
# default. That's fine for the app itself, but /oauth/authorize/ is meant
# to be opened as a POPUP by a cross-origin caller (claude.ai's connector
# flow) which typically signals completion back to its opener via
# window.opener.postMessage(...). COOP: same-origin severs window.opener
# the moment the popup navigates to our (cross-origin, from claude.ai's
# point of view) origin, silently breaking that handshake even though the
# OAuth exchange itself completes successfully server-side - which matches
# exactly what was observed: every step logs as succeeding, then nothing.
# Disabling COOP site-wide costs us a defense against a niche
# cross-origin side-channel class of attack that isn't a real concern for
# this app; unblocking the OAuth popup flow is worth that trade here.
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
