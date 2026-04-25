#!/bin/sh
# First-time deploy script.
# Run this once on the VPS after cloning the repo.
#
# Usage: ./scripts/deploy.sh <domain> <email>
# Example: ./scripts/deploy.sh journal.example.com me@example.com

set -e

DOMAIN=${1:?Usage: ./scripts/deploy.sh <domain> <email>}
EMAIL=${2:?Usage: ./scripts/deploy.sh <domain> <email>}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# ── 1. Substitute domain in nginx config ──────────────────────────────────────
sed -i "s/YOUR_DOMAIN/$DOMAIN/g" nginx/nginx.conf

# ── 2. Substitute domain in backend .env (CORS_ORIGINS) ──────────────────────
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo ""
  echo "backend/.env created from .env.example."
  echo "Edit it now to set SECRET_KEY and PASSWORD_HASH, then re-run this script."
  echo ""
  echo "Generate a password hash with:"
  echo "  python3 -c \"import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())\""
  exit 1
fi

sed -i "s|https://yourdomain.com|https://$DOMAIN|g" backend/.env

# ── 3. Install certbot and obtain SSL certificate ─────────────────────────────
if ! command -v certbot > /dev/null 2>&1; then
  echo "Installing certbot..."
  apt-get update -qq && apt-get install -y certbot
fi

echo "Obtaining SSL certificate for $DOMAIN..."
certbot certonly --standalone \
  --email "$EMAIL" \
  --agree-tos --no-eff-email \
  -d "$DOMAIN"

# ── 4. Start the stack ────────────────────────────────────────────────────────
echo "Starting services..."
docker compose up -d --build

# ── 5. Set up automatic cert renewal ─────────────────────────────────────────
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && docker compose -f $SCRIPT_DIR/../docker-compose.yml restart nginx") | crontab -

echo ""
echo "Done. App is live at https://$DOMAIN"
