import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import bcrypt
from fastapi.testclient import TestClient

PASSWORD = "testpassword"
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
SECRET_KEY = "test-secret-key-that-is-long-enough-for-hmac-sha256"


def _make_client(journal_dir: str) -> TestClient:
    os.environ["PASSWORD_HASH"] = PASSWORD_HASH
    os.environ["SECRET_KEY"] = SECRET_KEY
    os.environ["JOURNAL_DIR"] = journal_dir
    os.environ["CORS_ORIGINS"] = "http://localhost"

    from webapp.backend.main import app
    return TestClient(app)


def _reset_rate_limit() -> None:
    from webapp.backend.routers.auth import _attempts
    _attempts.clear()


def _get_token(client: TestClient) -> str:
    resp = client.post("/auth/login", json={"password": PASSWORD})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(self.tmp)
        _reset_rate_limit()

    def test_login_valid(self):
        resp = self.client.post("/auth/login", json={"password": PASSWORD})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access_token", resp.json())

    def test_login_invalid(self):
        resp = self.client.post("/auth/login", json={"password": "wrong"})
        self.assertEqual(resp.status_code, 401)

    def test_login_rate_limit(self):
        for _ in range(5):
            self.client.post("/auth/login", json={"password": "wrong"})
        resp = self.client.post("/auth/login", json={"password": "wrong"})
        self.assertEqual(resp.status_code, 429)

    def test_protected_route_without_token(self):
        resp = self.client.get("/files")
        self.assertEqual(resp.status_code, 401)

    def test_protected_route_with_invalid_token(self):
        resp = self.client.get("/files", headers={"Authorization": "Bearer bad"})
        self.assertEqual(resp.status_code, 401)


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(self.tmp)
        _reset_rate_limit()
        self.token = _get_token(self.client)

    def _upload(self, date: str, content: str) -> None:
        self.client.post(
            "/files/upload",
            files={"file": (f"{date}.md", content.encode(), "text/markdown")},
            headers=_auth(self.token),
        )

    def test_list_empty(self):
        resp = self.client.get("/files", headers=_auth(self.token))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["dates"], [])

    def test_upload_and_list(self):
        self._upload("2025-01-15", "- [ ] Task A\n")
        resp = self.client.get("/files", headers=_auth(self.token))
        self.assertIn("2025-01-15", resp.json()["dates"])

    def test_upload_invalid_filename(self):
        resp = self.client.post(
            "/files/upload",
            files={"file": ("notes.md", b"content", "text/markdown")},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_upload_non_md(self):
        resp = self.client.post(
            "/files/upload",
            files={"file": ("2025-01-15.txt", b"content", "text/plain")},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_download_roundtrip(self):
        content = "- [ ] Task A\n"
        self._upload("2025-01-15", content)
        resp = self.client.get("/files/2025-01-15/download", headers=_auth(self.token))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, content.encode())

    def test_download_not_found(self):
        resp = self.client.get("/files/2025-01-15/download", headers=_auth(self.token))
        self.assertEqual(resp.status_code, 404)

    def test_delete(self):
        self._upload("2025-01-15", "- [ ] Task\n")
        self.client.delete("/files/2025-01-15", headers=_auth(self.token))
        resp = self.client.get("/files", headers=_auth(self.token))
        self.assertNotIn("2025-01-15", resp.json()["dates"])

    def test_upload_path_traversal(self):
        resp = self.client.post(
            "/files/upload",
            files={"file": ("../evil.md", b"content", "text/markdown")},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 400)


class TestTasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(self.tmp)
        _reset_rate_limit()
        self.token = _get_token(self.client)
        content = "- [ ] Task A\n- [x] Task B\n"
        Path(self.tmp, "2025-01-15.md").write_text(content)

    def test_get_tasks(self):
        resp = self.client.get("/tasks/2025-01-15", headers=_auth(self.token))
        self.assertEqual(resp.status_code, 200)
        tasks = resp.json()["tasks"]
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["title"], "Task A")
        self.assertEqual(tasks[0]["status"], "todo")
        self.assertEqual(tasks[1]["status"], "done")

    def test_get_tasks_not_found(self):
        resp = self.client.get("/tasks/2025-01-16", headers=_auth(self.token))
        self.assertEqual(resp.status_code, 404)

    def test_create_task(self):
        resp = self.client.post(
            "/tasks/2025-01-15",
            json={"title": "Task C"},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        content = Path(self.tmp, "2025-01-15.md").read_text()
        self.assertIn("Task C", content)

    def test_create_task_invalid_status(self):
        resp = self.client.post(
            "/tasks/2025-01-15",
            json={"title": "Task C", "status": "invalid"},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_task_newline_injection(self):
        resp = self.client.post(
            "/tasks/2025-01-15",
            json={"title": "Evil\nTask"},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_task_status(self):
        resp = self.client.patch(
            "/tasks/2025-01-15/1",
            json={"status": "done"},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        content = Path(self.tmp, "2025-01-15.md").read_text()
        self.assertIn("[x]", content)

    def test_update_task_invalid_line(self):
        resp = self.client.patch(
            "/tasks/2025-01-15/99",
            json={"status": "done"},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 404)

    def test_update_task_invalid_status(self):
        resp = self.client.patch(
            "/tasks/2025-01-15/1",
            json={"status": "invalid"},
            headers=_auth(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_creates_backup(self):
        self.client.patch(
            "/tasks/2025-01-15/1",
            json={"status": "done"},
            headers=_auth(self.token),
        )
        backups = list(Path(self.tmp, ".backups").glob("*.md"))
        self.assertGreater(len(backups), 0)


if __name__ == "__main__":
    unittest.main()
