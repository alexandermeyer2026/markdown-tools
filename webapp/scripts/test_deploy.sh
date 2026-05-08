#!/bin/sh
set -e

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

WEBAPP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cp -r "$WEBAPP_DIR" $TMPDIR/repo
cd $TMPDIR/repo

PASS=0
FAIL=0

check() {
    if eval "$2"; then
        echo "✓ $1"
        PASS=$((PASS + 1))
    else
        echo "✗ $1"
        FAIL=$((FAIL + 1))
    fi
}

# ── First run (no .env) ───────────────────────────────────────────────────────
echo "--- First run ---"
rm -f backend/.env
bash scripts/deploy.sh mydomain.com me@example.com || true

check "first run: nginx.conf generated"               "[ -f nginx/nginx.conf ]"
check "first run: nginx.conf has domain"              "grep -q 'mydomain.com' nginx/nginx.conf"
check "first run: nginx.conf no leftover placeholder" "! grep -q 'YOUR_DOMAIN' nginx/nginx.conf"
check "first run: backend/.env generated"             "[ -f backend/.env ]"
check "first run: backend/.env has domain"            "grep -q 'https://mydomain.com' backend/.env"
check "first run: nginx.conf.template untouched"      "grep -q 'YOUR_DOMAIN' nginx/nginx.conf.template"

# ── Second run (.env exists, stubs for certbot/docker/crontab) ───────────────
echo ""
echo "--- Second run ---"
mkdir -p bin
printf '#!/bin/sh\necho "[stub] certbot $@"\n'       > bin/certbot  && chmod +x bin/certbot
printf '#!/bin/sh\necho "[stub] docker $@"\n'        > bin/docker   && chmod +x bin/docker
printf '#!/bin/sh\necho "[stub] crontab $@"\n'       > bin/crontab  && chmod +x bin/crontab
PATH="$TMPDIR/repo/bin:$PATH"

# Overwrite nginx.conf to confirm it gets regenerated
echo "old" > nginx/nginx.conf

bash scripts/deploy.sh mydomain.com me@example.com

check "second run: nginx.conf regenerated"              "! grep -q 'old' nginx/nginx.conf"
check "second run: nginx.conf has domain"               "grep -q 'mydomain.com' nginx/nginx.conf"
check "second run: nginx.conf no leftover placeholder"  "! grep -q 'YOUR_DOMAIN' nginx/nginx.conf"
check "second run: backend/.env unchanged"              "grep -q 'https://mydomain.com' backend/.env"

echo ""
echo "$PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
