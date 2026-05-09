import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

from app.models import ChatMessage, ChatResponse


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return value or "user"


class Storage:
    def __init__(self, database_path: Path, evidence_dir: Path):
        self.database_path = database_path
        self.evidence_dir = evidence_dir
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    username TEXT,
                    messages_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    evidence_path TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )

    def create_user(self, username: str, password: str) -> dict[str, str]:
        username = username.strip().lower()
        if len(username) < 3 or len(password) < 4:
            raise ValueError("Username must be at least 3 characters and password at least 4 characters.")
        user_id = secrets.token_urlsafe(16)
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, username, hashed, _now()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Username already exists.") from exc
        return {"user_id": user_id, "username": username}

    def authenticate(self, username: str, password: str) -> dict[str, str] | None:
        username = username.strip().lower()
        with self._connect() as conn:
            row = conn.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return None
        if not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"]):
            return None
        return {"user_id": row["id"], "username": row["username"]}

    def get_user(self, user_id: str | None) -> dict[str, str] | None:
        if not user_id:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return {"user_id": row["id"], "username": row["username"]}

    def save_conversation(
        self,
        user_id: str | None,
        messages: list[ChatMessage],
        response: ChatResponse,
    ) -> str | None:
        user = self.get_user(user_id)
        if not user:
            return None

        conversation_id = secrets.token_urlsafe(16)
        payload = {
            "conversation_id": conversation_id,
            "user_id": user["user_id"],
            "username": user["username"],
            "created_at": _now(),
            "messages": [message.model_dump() for message in messages],
            "response": response.model_dump(),
        }

        user_dir = self.evidence_dir / _safe_name(user["username"])
        user_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = user_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{conversation_id}.json"
        evidence_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations
                (id, user_id, username, messages_json, response_json, evidence_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    user["user_id"],
                    user["username"],
                    json.dumps(payload["messages"], ensure_ascii=False),
                    json.dumps(payload["response"], ensure_ascii=False),
                    str(evidence_path),
                    payload["created_at"],
                ),
            )
        self.append_user_memory(user["user_id"], payload)
        return str(evidence_path)

    def memory_path_for_user(self, user: dict[str, str]) -> Path:
        user_dir = self.evidence_dir / _safe_name(user["username"])
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "memory.json"

    def load_user_memory(self, user_id: str | None) -> dict:
        user = self.get_user(user_id)
        if not user:
            return {}
        memory_path = self.memory_path_for_user(user)
        if not memory_path.exists():
            return {
                "user_id": user["user_id"],
                "username": user["username"],
                "created_at": _now(),
                "updated_at": _now(),
                "summary": "",
                "conversations": [],
            }
        try:
            return json.loads(memory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "user_id": user["user_id"],
                "username": user["username"],
                "created_at": _now(),
                "updated_at": _now(),
                "summary": "",
                "conversations": [],
            }

    def append_user_memory(self, user_id: str, payload: dict) -> None:
        memory = self.load_user_memory(user_id)
        if not memory:
            return
        conversations = memory.setdefault("conversations", [])
        conversations.append(payload)
        memory["updated_at"] = _now()
        user = {"user_id": memory["user_id"], "username": memory["username"]}
        self.memory_path_for_user(user).write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")

    def update_user_memory_summary(self, user_id: str | None, summary: str) -> None:
        if not user_id:
            return
        memory = self.load_user_memory(user_id)
        if not memory:
            return
        memory["summary"] = summary
        memory["updated_at"] = _now()
        user = {"user_id": memory["user_id"], "username": memory["username"]}
        self.memory_path_for_user(user).write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_conversations(self, user_id: str) -> list[dict[str, str]]:
        user = self.get_user(user_id)
        if not user:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, username, evidence_path, created_at
                FROM conversations
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]
