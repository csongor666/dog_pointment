import base64
import json
import time
from datetime import datetime, timezone
from typing import Any

import requests


class StorageError(RuntimeError):
    pass


class GitHubJSONStorage:
    """JSON-fájl olvasása és módosítása a GitHub Contents API-n keresztül."""

    def __init__(self, token: str, owner: str, repo: str, branch: str, path: str):
        self.token = token
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.path = path
        self.url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def read(self) -> tuple[list[dict[str, Any]], str | None]:
        response = requests.get(
            self.url,
            headers=self.headers,
            params={"ref": self.branch},
            timeout=20,
        )
        if response.status_code == 404:
            return [], None
        if not response.ok:
            raise StorageError(f"GitHub olvasási hiba ({response.status_code}): {response.text[:300]}")

        payload = response.json()
        try:
            raw = base64.b64decode(payload["content"]).decode("utf-8")
            data = json.loads(raw)
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise StorageError("A foglalási JSON-fájl nem olvasható.") from exc
        if not isinstance(data, list):
            raise StorageError("A foglalási fájl gyökérelemének listának kell lennie.")
        return data, payload.get("sha")

    def write(self, records: list[dict[str, Any]], sha: str | None, message: str) -> None:
        content = json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha
        response = requests.put(self.url, headers=self.headers, json=body, timeout=25)
        if not response.ok:
            raise StorageError(f"GitHub mentési hiba ({response.status_code}): {response.text[:300]}")

    def add_booking(self, booking: dict[str, Any], retries: int = 3) -> None:
        """Ütközésellenőrzéssel ment. SHA-ütközés esetén újrapróbálkozik."""
        for attempt in range(retries):
            records, sha = self.read()
            collision = any(
                item.get("date") == booking["date"]
                and item.get("time") == booking["time"]
                and item.get("status", "active") == "active"
                for item in records
            )
            if collision:
                raise StorageError("Ezt az időpontot időközben lefoglalták.")
            records.append(booking)
            try:
                self.write(records, sha, f"Új foglalás: {booking['date']} {booking['time']}")
                return
            except StorageError as exc:
                if "409" not in str(exc) and "422" not in str(exc):
                    raise
                if attempt == retries - 1:
                    raise StorageError("Párhuzamos foglalás történt. Kérjük, próbálja újra.") from exc
                time.sleep(0.5 * (attempt + 1))

    def cancel_booking(self, booking_id: str) -> None:
        records, sha = self.read()
        found = False
        for item in records:
            if item.get("id") == booking_id:
                item["status"] = "cancelled"
                item["cancelled_at"] = datetime.now(timezone.utc).isoformat()
                found = True
                break
        if not found:
            raise StorageError("A foglalás nem található.")
        self.write(records, sha, f"Foglalás lemondása: {booking_id}")
