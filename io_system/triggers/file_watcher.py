"""Filesystem trigger.

Watches a list of directories (via ``SUMMER_FILE_WATCH_PATHS``,
comma-separated) and emits a ``TriggerEvent`` whenever a new file is created
or moved into one of them. The content includes the first 1KB of the file
when it appears to be text.

Requires ``watchdog``. If watchdog is not importable, ``is_available()``
returns False and ``start()`` becomes a no-op.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .base import EventTrigger, TriggerCallback, TriggerEvent

logger = logging.getLogger(__name__)


def _watchdog_available() -> bool:
    try:
        import watchdog  # noqa: F401
        from watchdog.events import FileSystemEventHandler  # noqa: F401
        from watchdog.observers import Observer  # noqa: F401
        return True
    except ImportError:
        return False


_WATCHDOG_AVAILABLE = _watchdog_available()


_TEXT_PREVIEW_BYTES = 1024


class FileWatcherTrigger(EventTrigger):
    """Emits a TriggerEvent whenever a new file lands in a watched directory."""

    name = "file_watcher"

    def __init__(
        self,
        on_event: TriggerCallback,
        paths: Optional[List[str]] = None,
        recursive: bool = False,
    ):
        super().__init__(on_event)
        env_paths = os.environ.get("SUMMER_FILE_WATCH_PATHS", "")
        self.paths: List[Path] = [
            Path(p).expanduser()
            for p in (paths or [s.strip() for s in env_paths.split(",") if s.strip()])
        ]
        self.recursive = recursive
        self._observer = None
        self._stopped = threading.Event()

    @classmethod
    def is_available(cls) -> bool:
        return _WATCHDOG_AVAILABLE

    # ----- lifecycle -----

    def start(self) -> None:
        if not self.is_available():
            logger.info("FileWatcherTrigger.start(): watchdog unavailable; no-op")
            return
        if not self.paths:
            logger.info(
                "FileWatcherTrigger.start(): no paths configured; no-op"
            )
            return
        if self._observer is not None:
            return

        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        trigger = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                trigger._emit_for_path(event.src_path)

            def on_moved(self, event):
                if event.is_directory:
                    return
                dest = getattr(event, "dest_path", None) or event.src_path
                trigger._emit_for_path(dest)

        observer = Observer()
        handler = _Handler()
        scheduled_any = False
        for p in self.paths:
            if not p.exists() or not p.is_dir():
                logger.warning("FileWatcherTrigger: path missing or not a dir: %s", p)
                continue
            observer.schedule(handler, str(p), recursive=self.recursive)
            scheduled_any = True
        if not scheduled_any:
            logger.info("FileWatcherTrigger: no valid paths; no-op")
            return
        observer.daemon = True
        observer.start()
        self._observer = observer
        logger.info(
            "FileWatcherTrigger: watching %s",
            ", ".join(str(p) for p in self.paths),
        )

    def stop(self, timeout: float = 5.0) -> None:
        if self._observer is None:
            return
        try:
            self._observer.stop()
            self._observer.join(timeout=timeout)
        except Exception:
            logger.exception("FileWatcherTrigger: stop error")
        self._observer = None

    # ----- emission -----

    def _emit_for_path(self, path_str: str) -> None:
        try:
            path = Path(path_str)
            stat = path.stat()
        except OSError:
            return
        preview = _read_text_preview(path)
        size = stat.st_size
        content = f"New file: {path}\nSize: {size} bytes"
        if preview:
            content += f"\n{preview}"
        event = TriggerEvent(
            source=self.name,
            title=path.name,
            content=content,
            timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            metadata={
                "path": str(path),
                "size": size,
                "mtime": stat.st_mtime,
            },
            event_id=f"file:{path.resolve()}",
        )
        self._emit(event)


def _read_text_preview(path: Path) -> str:
    try:
        with path.open("rb") as f:
            chunk = f.read(_TEXT_PREVIEW_BYTES)
    except OSError:
        return ""
    if not chunk:
        return ""
    # Heuristic: treat as text if it decodes cleanly and has no NUL bytes.
    if b"\x00" in chunk:
        return ""
    try:
        return chunk.decode("utf-8")
    except UnicodeDecodeError:
        return ""
