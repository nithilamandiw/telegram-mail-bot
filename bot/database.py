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
                verification_token TEXT,
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

            CREATE TABLE IF NOT EXISTS sent_emails (
                id         TEXT PRIMARY KEY,
                chat_id    TEXT NOT NULL,
                from_addr  TEXT NOT NULL,
                to_addr    TEXT NOT NULL,
                subject    TEXT NOT NULL,
                body       TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'sent',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sent_emails_chat_id
                ON sent_emails(chat_id);

            CREATE TABLE IF NOT EXISTS blocked_senders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    TEXT NOT NULL,
                sender     TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(chat_id, sender)
            );

            CREATE INDEX IF NOT EXISTS idx_blocked_senders_chat_id
                ON blocked_senders(chat_id);
        """)
        conn.commit()
        # Migration: add verification_token column if missing (existing DBs)
        self._migrate_add_verification_token()

    def _migrate_add_verification_token(self) -> None:
        """Add verification_token column to domains table if it doesn't exist."""
        conn = self._conn
        cursor = conn.execute("PRAGMA table_info(domains)")
        columns = [row[1] for row in cursor.fetchall()]
        if "verification_token" not in columns:
            conn.execute("ALTER TABLE domains ADD COLUMN verification_token TEXT")
            conn.commit()

    # ── Domains ──────────────────────────────────────────────

    def add_domain(self, chat_id: str, domain: str, verification_token: str = "") -> bool:
        """
        Register a domain for a chat with a unique verification token.
        Returns False if it already exists for this chat.
        """
        try:
            self._conn.execute(
                "INSERT INTO domains (chat_id, domain, verified, verification_token, created_at) "
                "VALUES (?, ?, 0, ?, ?)",
                (chat_id, domain, verification_token, datetime.now(timezone.utc).isoformat()),
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

    def is_domain_verified_by_others(self, domain: str, chat_id: str) -> bool:
        """
        Check if a domain is already verified by a different user.
        Used to prevent hijacking of domains that are already owned.
        """
        row = self._conn.execute(
            "SELECT 1 FROM domains WHERE domain = ? AND chat_id != ? AND verified = 1 LIMIT 1",
            (domain, chat_id),
        ).fetchone()
        return row is not None

    def get_verification_token(self, chat_id: str, domain: str) -> str | None:
        """Get the verification token for a domain."""
        row = self._conn.execute(
            "SELECT verification_token FROM domains WHERE chat_id = ? AND domain = ?",
            (chat_id, domain),
        ).fetchone()
        return row["verification_token"] if row else None

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

    # ── Sent Emails (Outbox) ─────────────────────────────────

    def save_sent_email(
        self, email_id: str, chat_id: str, from_addr: str,
        to_addr: str, subject: str, body: str, status: str = "sent",
    ) -> None:
        """Save an outgoing email to the sent history."""
        self._conn.execute(
            "INSERT INTO sent_emails (id, chat_id, from_addr, to_addr, subject, body, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email_id, chat_id, from_addr, to_addr, subject, body, status,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def get_sent_emails_for_chat(self, chat_id: str, limit: int = 20) -> list[dict]:
        """Get recent sent emails for a chat."""
        rows = self._conn.execute(
            "SELECT * FROM sent_emails WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Blocked Senders ──────────────────────────────────────

    def add_blocked_sender(self, chat_id: str, sender: str) -> bool:
        """Block a sender (email or @domain). Returns False if already blocked."""
        try:
            self._conn.execute(
                "INSERT INTO blocked_senders (chat_id, sender, created_at) VALUES (?, ?, ?)",
                (chat_id, sender.lower().strip(), datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_blocked_sender(self, chat_id: str, sender: str) -> bool:
        """Unblock a sender. Returns True if a row was deleted."""
        cursor = self._conn.execute(
            "DELETE FROM blocked_senders WHERE chat_id = ? AND sender = ?",
            (chat_id, sender.lower().strip()),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_blocked_senders(self, chat_id: str) -> list[dict]:
        """Get all blocked senders for a chat."""
        rows = self._conn.execute(
            "SELECT * FROM blocked_senders WHERE chat_id = ? ORDER BY created_at DESC",
            (chat_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def is_sender_blocked(self, chat_id: str, sender_email: str) -> bool:
        """
        Check if a sender is blocked. Supports:
        - Exact email match (e.g. spam@example.com)
        - Domain-level match (e.g. @example.com blocks all from that domain)
        """
        sender_email = sender_email.lower().strip()
        # Extract just the email if it contains a display name like "Name <email>"
        if "<" in sender_email and ">" in sender_email:
            sender_email = sender_email.split("<")[-1].rstrip(">")
        domain = "@" + sender_email.split("@")[-1] if "@" in sender_email else ""

        row = self._conn.execute(
            "SELECT 1 FROM blocked_senders WHERE chat_id = ? AND (sender = ? OR sender = ?) LIMIT 1",
            (chat_id, sender_email, domain),
        ).fetchone()
        return row is not None


