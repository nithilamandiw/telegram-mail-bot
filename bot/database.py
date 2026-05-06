"""
SQLite database layer for domain and email address management.

Replaces DynamoDB with a local SQLite database — zero cloud dependencies.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "email_bot.db"


class Database:
    """Thread-safe SQLite database for the email bot."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_tables()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_tables(self) -> None:
        """Create tables if they don't exist."""
        conn = self._conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS domains (
                chat_id   TEXT    NOT NULL,
                domain    TEXT    NOT NULL,
                verified  INTEGER NOT NULL DEFAULT 0,
                created_at TEXT   NOT NULL,
                PRIMARY KEY (chat_id, domain)
            );

            CREATE TABLE IF NOT EXISTS addresses (
                email      TEXT PRIMARY KEY,
                chat_id    TEXT NOT NULL,
                domain     TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_addresses_chat_id
                ON addresses(chat_id);

            CREATE INDEX IF NOT EXISTS idx_addresses_domain
                ON addresses(domain);

            CREATE TABLE IF NOT EXISTS emails (
                id         TEXT PRIMARY KEY,
                chat_id    TEXT NOT NULL,
                to_email   TEXT NOT NULL,
                from_addr  TEXT NOT NULL,
                subject    TEXT NOT NULL,
                date       TEXT NOT NULL,
                body_html  TEXT,
                body_text  TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_emails_chat_id
                ON emails(chat_id);
        """)
        conn.commit()

    # ── Domains ──────────────────────────────────────────────

    def add_domain(self, chat_id: str, domain: str) -> bool:
        """
        Register a domain for a chat. Returns False if it already exists.
        """
        try:
            self._conn.execute(
                "INSERT INTO domains (chat_id, domain, verified, created_at) VALUES (?, ?, 0, ?)",
                (chat_id, domain, datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_domain(self, chat_id: str, domain: str) -> dict | None:
        """Get a domain record for a specific chat."""
        row = self._conn.execute(
            "SELECT * FROM domains WHERE chat_id = ? AND domain = ?",
            (chat_id, domain),
        ).fetchone()
        return dict(row) if row else None

    def verify_domain(self, chat_id: str, domain: str) -> None:
        """Mark a domain as verified."""
        self._conn.execute(
            "UPDATE domains SET verified = 1 WHERE chat_id = ? AND domain = ?",
            (chat_id, domain),
        )
        self._conn.commit()

    def get_domains_for_chat(self, chat_id: str) -> list[dict]:
        """Get all domains for a chat."""
        rows = self._conn.execute(
            "SELECT * FROM domains WHERE chat_id = ?", (chat_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_verified_domains(self) -> list[str]:
        """Get all verified domain names (for SMTP filtering)."""
        rows = self._conn.execute(
            "SELECT DISTINCT domain FROM domains WHERE verified = 1"
        ).fetchall()
        return [r["domain"] for r in rows]

    def delete_domain(self, chat_id: str, domain: str) -> bool:
        """Delete a domain and all its associated email addresses."""
        self._conn.execute(
            "DELETE FROM addresses WHERE chat_id = ? AND domain = ?",
            (chat_id, domain),
        )
        cursor = self._conn.execute(
            "DELETE FROM domains WHERE chat_id = ? AND domain = ?",
            (chat_id, domain),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ── Email Addresses ──────────────────────────────────────

    def add_email(self, email: str, chat_id: str, domain: str) -> bool:
        """Register an email address. Returns False if it already exists."""
        try:
            self._conn.execute(
                "INSERT INTO addresses (email, chat_id, domain, created_at) VALUES (?, ?, ?, ?)",
                (email, chat_id, domain, datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_email(self, email: str) -> dict | None:
        """Look up an email address."""
        row = self._conn.execute(
            "SELECT * FROM addresses WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None

    def get_emails_for_chat(self, chat_id: str) -> list[dict]:
        """Get all email addresses for a chat."""
        rows = self._conn.execute(
            "SELECT * FROM addresses WHERE chat_id = ?", (chat_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_emails_for_domain(self, chat_id: str, domain: str) -> list[dict]:
        """Get all email addresses for a specific domain."""
        rows = self._conn.execute(
            "SELECT * FROM addresses WHERE chat_id = ? AND domain = ?",
            (chat_id, domain),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_email(self, email: str) -> bool:
        """Delete an email address. Returns True if a row was deleted."""
        cursor = self._conn.execute(
            "DELETE FROM addresses WHERE email = ?", (email,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ── Stored Emails (Webmail Viewer) ────────────────────────

    def save_email(
        self, email_id: str, chat_id: str, to_email: str,
        from_addr: str, subject: str, date: str,
        body_html: str | None, body_text: str | None,
    ) -> None:
        """Save a received email for web viewing."""
        self._conn.execute(
            "INSERT INTO emails (id, chat_id, to_email, from_addr, subject, date, body_html, body_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email_id, chat_id, to_email, from_addr, subject, date,
                body_html, body_text,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def get_email_by_id(self, email_id: str) -> dict | None:
        """Look up a stored email by its UUID."""
        row = self._conn.execute(
            "SELECT * FROM emails WHERE id = ?", (email_id,)
        ).fetchone()
        return dict(row) if row else None

