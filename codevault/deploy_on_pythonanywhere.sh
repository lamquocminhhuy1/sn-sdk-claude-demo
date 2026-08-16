#!/bin/bash
# One-shot CodeVault deploy. Run INSIDE a PythonAnywhere Bash console:
#
#   export PA_TOKEN=<your API token>
#   git clone https://github.com/lamquocminhhuy1/sn-sdk-claude-demo.git
#   bash sn-sdk-claude-demo/codevault/deploy_on_pythonanywhere.sh
#
# Re-running is safe: it upgrades code, keeps the database and admin password.
set -e

PA_USER="$USER"
DOMAIN="${PA_USER}.pythonanywhere.com"
API="https://www.pythonanywhere.com/api/v0/user/${PA_USER}"
SRC="$HOME/sn-sdk-claude-demo/codevault"
VENV="$HOME/.virtualenvs/codevault"
WSGI_FILE="/var/www/${PA_USER}_pythonanywhere_com_wsgi.py"

fail() { echo "ERROR: $1" >&2; exit 1; }
api() {  # api METHOD path [curl -d args...]
    local method="$1" path="$2"; shift 2
    curl -sS -X "$method" "${API}${path}" -H "Authorization: Token ${PA_TOKEN}" "$@"
    echo
}

[ -n "$PA_TOKEN" ] || fail "run: export PA_TOKEN=<your API token> first"
[ -d "$SRC" ] || fail "$SRC not found - git clone the repo into your home directory first"

PYBIN=python3.11
command -v $PYBIN >/dev/null 2>&1 || PYBIN=python3.10
command -v $PYBIN >/dev/null 2>&1 || fail "no python3.10/3.11 found"
PYVER=$($PYBIN -c 'import sys; print("python%d%d" % sys.version_info[:2])')

echo "== 1/6 Virtualenv ($PYBIN) =="
[ -d "$VENV" ] || $PYBIN -m venv "$VENV"
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$SRC/requirements.txt"

echo "== 2/6 Secrets =="
# Secret key persists in the WSGI file; reuse it on re-runs so sessions survive.
if [ -f "$WSGI_FILE" ] && grep -q "DJANGO_SECRET_KEY" "$WSGI_FILE"; then
    SECRET_KEY=$(python - "$WSGI_FILE" <<'PYEOF'
import re, sys
text = open(sys.argv[1]).read()
match = re.search(r"DJANGO_SECRET_KEY'\] = '([^']*)'", text)
print(match.group(1) if match else "")
PYEOF
)
fi
if [ -z "$SECRET_KEY" ]; then
    SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as g; print(g().replace(chr(39), chr(45)))")
fi
ADMIN_PASS=$(python -c "import secrets; print(secrets.token_urlsafe(12))")

echo "== 3/6 Database, admin user, static files =="
cd "$SRC"
export DJANGO_SECRET_KEY="$SECRET_KEY" DJANGO_DEBUG=0
python manage.py migrate --no-input
if DJANGO_SUPERUSER_PASSWORD="$ADMIN_PASS" python manage.py createsuperuser \
        --no-input --username admin --email "admin@${DOMAIN}" 2>/dev/null; then
    NEW_ADMIN=1
else
    NEW_ADMIN=0
fi
python manage.py collectstatic --no-input --clear >/dev/null

echo "== 4/6 Web app via API =="
# Create (fails harmlessly if the app already exists), then point it at our code.
api POST "/webapps/" -d "domain_name=${DOMAIN}" -d "python_version=${PYVER}" || true
api PATCH "/webapps/${DOMAIN}/" \
    -d "source_directory=${SRC}" -d "virtualenv_path=${VENV}"
# Static mapping for /static/ only. /media/ stays behind Django login on purpose.
api POST "/webapps/${DOMAIN}/static_files/" \
    -d "url=/static/" -d "path=${SRC}/staticfiles" || true

echo "== 5/6 WSGI file =="
python - "$WSGI_FILE" "$SRC" <<'PYEOF'
import os, sys
wsgi_path, src = sys.argv[1], sys.argv[2]
secret = os.environ["DJANGO_SECRET_KEY"]
content = (
    "import os\n"
    "import sys\n\n"
    "path = " + repr(src) + "\n"
    "if path not in sys.path:\n"
    "    sys.path.insert(0, path)\n\n"
    "os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'\n"
    "os.environ['DJANGO_DEBUG'] = '0'\n"
    "os.environ['DJANGO_SECRET_KEY'] = " + repr(secret) + "\n\n"
    "from django.core.wsgi import get_wsgi_application\n"
    "application = get_wsgi_application()\n"
)
with open(wsgi_path, "w") as f:
    f.write(content)
print("wrote", wsgi_path)
PYEOF

echo "== 6/6 Reload =="
api POST "/webapps/${DOMAIN}/reload/"

echo
echo "======================================================="
echo " DONE - your site: https://${DOMAIN}"
if [ "$NEW_ADMIN" = "1" ]; then
    echo " Login:    admin"
    echo " Password: ${ADMIN_PASS}"
    echo " (change it right away: https://${DOMAIN}/admin/password_change/)"
else
    echo " Admin user already existed - password unchanged."
fi
echo " Now REVOKE the API token: Account -> API Token"
echo "======================================================="
