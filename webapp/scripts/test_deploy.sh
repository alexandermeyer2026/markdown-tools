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

# nginx.conf is a committed, static config (no generation step).
check "nginx.conf present"                            "[ -f nginx/nginx.conf ]"
check "nginx.conf terminates no TLS"                  "! grep -qi 'ssl_certificate' nginx/nginx.conf"

# ── First run (no .env): deploy creates .env from template and stops ──────────
echo "--- First run ---"
rm -f backend/.env
bash scripts/deploy.sh mydomain.com || true

check "first run: backend/.env generated"             "[ -f backend/.env ]"
check "first run: backend/.env has domain"            "grep -q 'https://mydomain.com' backend/.env"

# ── Second run (.env exists, stub for docker): deploy proceeds to `up` ────────
echo ""
echo "--- Second run ---"
mkdir -p bin
printf '#!/bin/sh\necho "[stub] docker $@"\n'        > bin/docker   && chmod +x bin/docker
PATH="$TMPDIR/repo/bin:$PATH"

bash scripts/deploy.sh mydomain.com

check "second run: backend/.env unchanged"              "grep -q 'https://mydomain.com' backend/.env"

echo ""
echo "$PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
