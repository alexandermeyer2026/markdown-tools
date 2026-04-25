# Journal Web App

A self-hosted mobile portal for the markdown journal CLI tool. Upload selected `.md` files to a server, view and edit tasks from any browser, and download them back. The CLI and web app are independent — sync is manual and explicit.

## How it works

- The **CLI tool** is your primary interface, running locally with your full journal
- The **web app** runs on a server and holds only what you upload to it
- You push files up and pull them down manually — nothing syncs automatically

---

## Local setup (Docker)

**Requirements:** Docker Desktop, Python 3.10+ (for generating the password hash)

**1. Generate a password hash**
```sh
python3 -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
```

**2. Create `webapp/backend/.env`**
```sh
cp webapp/backend/.env.example webapp/backend/.env
```

Edit it with your values:
```
JOURNAL_DIR=/data/journal
SECRET_KEY=any-random-string
PASSWORD_HASH="<hash from step 1>"
CORS_ORIGINS=http://localhost:8080
```

> The `PASSWORD_HASH` value must be wrapped in double quotes to prevent `$` signs from being interpreted.

**3. Install frontend dependencies** (required once to generate `package-lock.json`)
```sh
cd webapp/frontend && npm install && cd ../..
```

**4. Start the stack**
```sh
cd webapp
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
```

Open [http://localhost:8080](http://localhost:8080) and log in with your password.

---

## Server deployment

**Requirements:** A VPS with Docker and Docker Compose installed, a domain pointed at the server, ports 80 and 443 open.

**1. Clone the repo on the server**
```sh
git clone <repo-url>
cd <repo>
```

**2. Create `webapp/backend/.env`**
```sh
cp webapp/backend/.env.example webapp/backend/.env
```

Edit it:
```
JOURNAL_DIR=/data/journal
SECRET_KEY=<long random string>
PASSWORD_HASH="<bcrypt hash>"
CORS_ORIGINS=https://yourdomain.com
```

Generate a secure `SECRET_KEY`:
```sh
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**3. Run the deploy script**
```sh
chmod +x webapp/scripts/deploy.sh
./webapp/scripts/deploy.sh yourdomain.com you@email.com
```

The script will:
- Substitute your domain into the nginx config
- Obtain an SSL certificate via certbot (needs port 80 free)
- Build and start all containers
- Set up automatic certificate renewal via cron

Your app will be live at `https://yourdomain.com`.

---

## Usage

| Action | How |
|--------|-----|
| Upload a file | Dashboard → Upload → select `YYYY-MM-DD.md` |
| View tasks | Tap a date card |
| Change task status | Tap the status icon (cycles: ○ → ◐ → ✓ → ○) |
| Add a task | Tap the **+** button on a day view |
| Download a file | Date card → ↓ button |
| Delete a file | Date card → ✕ button |

---

## Architecture

```
webapp/
├── backend/        FastAPI — wraps the existing CLI parser and models
├── frontend/       React 18 + TypeScript — mobile-first UI
├── nginx/          nginx config + frontend Dockerfile
├── scripts/        deploy.sh for first-time server setup
├── docker-compose.yml        production
└── docker-compose.local.yml  local overrides (HTTP, port 8080)
```

The backend imports the CLI's `TaskParser`, `Task`, and `BackupManager` directly — no separate data model. Files are stored as plain `.md` in `JOURNAL_DIR`, and every write is backed up automatically to `JOURNAL_DIR/.backups/`.
