#!/bin/sh
# First-time deploy for the standalone webapp stack.
# Run this once on the host after cloning the repo.
#
# The webapp serves plain HTTP on a port (default 127.0.0.1:8080, override with
# WEBAPP_PORT). It does NOT terminate TLS — put a reverse proxy of your choice
# in front for HTTPS, or access it directly.
#
# Usage: ./scripts/deploy.sh <domain>
# Example: ./scripts/deploy.sh journal.example.com

set -e

DOMAIN=${1:?Usage: ./scripts/deploy.sh <domain>}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# ── 1. Generate backend .env from template ────────────────────────────────────
if [ ! -f backend/.env ]; then
  sed "s|https://yourdomain.com|https://$DOMAIN|g" backend/.env.example > backend/.env
  echo ""
  echo "backend/.env created from .env.example."
  echo "Edit it now to set SECRET_KEY and PASSWORD_HASH, then re-run this script."
  echo ""
  echo "Generate a password hash with:"
  echo "  python3 -c \"import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())\""
  exit 1
fi

# ── 2. Start the stack ────────────────────────────────────────────────────────
echo "Starting services..."
docker compose up -d --build

echo ""
echo "Done. Webapp is serving HTTP on ${WEBAPP_PORT:-127.0.0.1:8080}."
echo "Put a reverse proxy in front for TLS (e.g. https://$DOMAIN)."
