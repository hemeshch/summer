"""Email trigger.

Two operating modes:

1. Fixture mode (default). Reads JSONL records from the path in
   ``SUMMER_EMAIL_FIXTURE`` and polls for newly-appended lines. Useful for
   demos and tests without real Gmail or IMAP credentials.

2. IMAP mode. Activated when ``SUMMER_IMAP_HOST`` is set. Connects via
   ``imaplib.IMAP4_SSL``, polls the configured folder, tracks the last seen
   UID, and emits a ``TriggerEvent`` for each new message.

Both modes run on a daemon thread driven by a ``threading.Event``. The
trigger is always available (fixture mode works anywhere), and degrades to
a no-op if neither a fixture nor IMAP host is configured.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import List, Optional, Tuple

from .base import EventTrigger, TriggerCallback, TriggerEvent

logger = logging.getLogger(__name__)


_MAX_BODY_BYTES = 2048


class EmailTrigger(EventTrigger):
    """Polls a fixture file or an IMAP inbox for new mail."""

    name = "email"

    def __init__(
        self,
        on_event: TriggerCallback,
        fixture_path: Optional[str] = None,
        imap_host: Optional[str] = None,
        imap_user: Optional[str] = None,
        imap_password: Optional[str] = None,
        imap_folder: Optional[str] = None,
        poll_seconds: Optional[float] = None,
    ):
        super().__init__(on_event)
        env_fixture = os.environ.get("SUMMER_EMAIL_FIXTURE")
        self.fixture_path: Optional[Path] = (
            Path(fixture_path or env_fixture)
            if (fixture_path or env_fixture)
            else None
        )
        self.imap_host = imap_host or os.environ.get("SUMMER_IMAP_HOST")
        self.imap_user = imap_user or os.environ.get("SUMMER_IMAP_USER")
        self.imap_password = imap_password or os.environ.get("SUMMER_IMAP_PASSWORD")
        self.imap_folder = (
            imap_folder or os.environ.get("SUMMER_IMAP_FOLDER", "INBOX")
        )
        try:
            self.poll_seconds = float(
                poll_seconds
                if poll_seconds is not None
                else os.environ.get("SUMMER_IMAP_POLL_SECONDS", "60")
            )
        except ValueError:
            self.poll_seconds = 60.0

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fixture_offset: int = 0
        self._last_uid: int = 0

    @classmethod
    def is_available(cls) -> bool:
        return True

    # ----- lifecycle -----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if not self.fixture_path and not self.imap_host:
            logger.info(
                "EmailTrigger: no fixture path and no IMAP host configured; idle"
            )
            return
        self._stop_event.clear()
        if self.fixture_path and self.fixture_path.exists():
            # Seed offset so existing lines don't replay on startup.
            try:
                self._fixture_offset = self.fixture_path.stat().st_size
            except OSError:
                self._fixture_offset = 0
        self._thread = threading.Thread(
            target=self._run, name="EmailTrigger", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ----- run loop -----

    def _run(self) -> None:
        use_imap = bool(self.imap_host)
        sleep_for = self.poll_seconds if use_imap else max(self.poll_seconds / 6.0, 1.0)
        logger.info(
            "EmailTrigger: started (mode=%s, poll=%ss)",
            "imap" if use_imap else "fixture",
            sleep_for,
        )
        while not self._stop_event.is_set():
            try:
                if use_imap:
                    self._poll_imap()
                else:
                    self._poll_fixture()
            except Exception:
                logger.exception("EmailTrigger: poll cycle errored")
            self._stop_event.wait(sleep_for)
        logger.info("EmailTrigger: stopped")

    # ----- fixture mode -----

    def _poll_fixture(self) -> None:
        if not self.fixture_path or not self.fixture_path.exists():
            return
        try:
            with self.fixture_path.open("r", encoding="utf-8") as f:
                f.seek(self._fixture_offset)
                new_text = f.read()
                self._fixture_offset = f.tell()
        except OSError:
            logger.exception("EmailTrigger: cannot read fixture %s", self.fixture_path)
            return
        for line in new_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._emit_fixture_entry(entry)

    def _emit_fixture_entry(self, entry: dict) -> None:
        sender = entry.get("from", "")
        subject = entry.get("subject", "")
        body = (entry.get("body") or "")[:_MAX_BODY_BYTES]
        ts = _parse_ts(entry.get("timestamp")) or datetime.now(timezone.utc)
        message_id = entry.get("id") or entry.get("message_id")
        event_id = f"email:{message_id}" if message_id else None
        event = TriggerEvent(
            source=self.name,
            title=subject,
            content=f"From: {sender}\nSubject: {subject}\n\n{body}",
            timestamp=ts,
            metadata={"from": sender, "subject": subject, "uid": message_id},
            event_id=event_id,
        )
        self._emit(event)

    # ----- imap mode -----

    def _poll_imap(self) -> None:
        if not (self.imap_host and self.imap_user and self.imap_password):
            logger.warning(
                "EmailTrigger: IMAP host set but credentials missing; idle"
            )
            return
        try:
            client = imaplib.IMAP4_SSL(self.imap_host)
            client.login(self.imap_user, self.imap_password)
        except Exception:
            logger.exception("EmailTrigger: IMAP connection failed")
            return
        try:
            client.select(self.imap_folder, readonly=True)

            # First poll: seed _last_uid to the current max so we don't replay
            # every existing message on startup. We only react to messages
            # delivered AFTER the trigger came up.
            if self._last_uid == 0:
                typ, data = client.uid("search", None, "ALL")
                if typ == "OK" and data and data[0]:
                    existing = [int(u) for u in data[0].split()]
                    if existing:
                        self._last_uid = max(existing)
                        logger.info(
                            "EmailTrigger: seeded last_uid=%s; will only fire for messages with higher UID",
                            self._last_uid,
                        )
                return

            criterion = f"UID {self._last_uid + 1}:*"
            typ, data = client.uid("search", None, criterion)
            if typ != "OK" or not data or not data[0]:
                return
            uids = [int(u) for u in data[0].split() if int(u) > self._last_uid]
            for uid in sorted(uids):
                try:
                    self._fetch_and_emit_uid(client, uid)
                except Exception:
                    logger.exception("EmailTrigger: failed to fetch uid %s", uid)
                self._last_uid = max(self._last_uid, uid)
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

    def _fetch_and_emit_uid(self, client: imaplib.IMAP4_SSL, uid: int) -> None:
        typ, data = client.uid("fetch", str(uid).encode(), b"(RFC822)")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return
        raw = data[0][1]
        msg = email.message_from_bytes(raw)
        subject, sender, body, ts, message_id = _parse_message(msg)
        event_id = f"email:{message_id}" if message_id else f"email:uid:{uid}"
        event = TriggerEvent(
            source=self.name,
            title=subject,
            content=f"From: {sender}\nSubject: {subject}\n\n{body[:_MAX_BODY_BYTES]}",
            timestamp=ts or datetime.now(timezone.utc),
            metadata={"from": sender, "subject": subject, "uid": uid},
            event_id=event_id,
        )
        self._emit(event)


# ----- helpers -----

def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        parts = email.header.decode_header(value)
    except Exception:
        return value
    out: List[str] = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                out.append(chunk.decode("utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _extract_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp.lower():
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except LookupError:
                    return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return msg.get_payload() or ""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _parse_message(msg: Message) -> Tuple[str, str, str, Optional[datetime], Optional[str]]:
    subject = _decode_header(msg.get("Subject", ""))
    sender = _decode_header(msg.get("From", ""))
    body = _extract_body(msg)
    raw_date = msg.get("Date")
    ts: Optional[datetime] = None
    if raw_date:
        try:
            ts = email.utils.parsedate_to_datetime(raw_date)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            ts = None
    message_id = (msg.get("Message-ID") or "").strip().strip("<>") or None
    return subject, sender, body, ts, message_id
