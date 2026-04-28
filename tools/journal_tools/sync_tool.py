import datetime
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from os_utils import resolve_date

_CONFIG_PATH = Path.home() / '.journal_sync.json'


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        print("Not logged in. Run: journal sync login")
        sys.exit(1)
    return json.loads(_CONFIG_PATH.read_text())


def _save_config(config: dict) -> None:
    _CONFIG_PATH.write_text(json.dumps(config, indent=2))
    _CONFIG_PATH.chmod(0o600)


def _resolve_date(date_string: str) -> datetime.date:
    date = resolve_date(date_string)
    if date is None:
        print(f"Invalid date: {date_string}. Use today/yesterday/tomorrow or YYYY-MM-DD.")
        sys.exit(1)
    return date


def _request(method: str, url: str, token: str, body: bytes = None, content_type: str = None):
    headers = {'Authorization': f'Bearer {token}'}
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _cmd_login(args: list[str]) -> None:
    if len(args) < 1:
        print("Usage: journal sync login <server-url>")
        print("Example: journal sync login https://journal.yourdomain.com")
        sys.exit(1)

    url = args[0].rstrip('/')
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'
    import getpass
    password = getpass.getpass('Password: ')

    body = json.dumps({'password': password}).encode()
    status, data = _request('POST', f'{url}/api/auth/login', token='', body=body, content_type='application/json')

    if status != 200:
        print(f"Login failed: {data.decode()}")
        sys.exit(1)

    token = json.loads(data)['access_token']
    _save_config({'url': url, 'token': token})
    print(f"Logged in. Config saved to {_CONFIG_PATH}")


def _cmd_push(args: list[str], journal_dir: str) -> None:
    if len(args) < 1:
        print("Usage: journal sync push <date>")
        sys.exit(1)

    config = _load_config()
    date = _resolve_date(args[0])
    path = Path(journal_dir) / f'{date}.md'

    if not path.exists():
        print(f"No file found for {date}")
        sys.exit(1)

    content = path.read_bytes()
    boundary = 'boundary123456'
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{date}.md"\r\n'
        f'Content-Type: text/markdown\r\n\r\n'
    ).encode() + content + f'\r\n--{boundary}--\r\n'.encode()

    status, data = _request(
        'POST',
        f'{config["url"]}/api/files/upload',
        token=config['token'],
        body=body,
        content_type=f'multipart/form-data; boundary={boundary}',
    )

    if status == 200:
        print(f"Pushed {date}.md")
    elif status == 401:
        print("Token expired. Run: journal sync login <server-url>")
        sys.exit(1)
    else:
        print(f"Push failed ({status}): {data.decode()}")
        sys.exit(1)


def _cmd_pull(args: list[str], journal_dir: str) -> None:
    if len(args) < 1:
        print("Usage: journal sync pull <date>")
        sys.exit(1)

    config = _load_config()
    date = _resolve_date(args[0])

    status, data = _request(
        'GET',
        f'{config["url"]}/api/files/{date}/download',
        token=config['token'],
    )

    if status == 200:
        from os_utils.backup_manager import BackupManager
        dest = Path(journal_dir) / f'{date}.md'
        if dest.exists():
            BackupManager.backup(str(dest), journal_dir)
        dest.write_bytes(data)
        print(f"Pulled {date}.md")
    elif status == 401:
        print("Token expired. Run: journal sync login <server-url>")
        sys.exit(1)
    elif status == 404:
        print(f"No file for {date} on server")
        sys.exit(1)
    else:
        print(f"Pull failed ({status}): {data.decode()}")
        sys.exit(1)


class SyncTool:
    @staticmethod
    def run(args: list[str], journal_dir: str) -> None:
        if not args:
            print("Usage: journal sync <login|push|pull> [args...]")
            return

        sub = args[0].lower()
        rest = args[1:]

        match sub:
            case 'login':
                _cmd_login(rest)
            case 'push':
                _cmd_push(rest, journal_dir)
            case 'pull':
                _cmd_pull(rest, journal_dir)
            case _:
                print(f"Unknown sync subcommand: {sub}")
                print("Usage: journal sync <login|push|pull> [args...]")
