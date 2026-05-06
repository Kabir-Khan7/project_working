"""
1.1.3 — Real-Time File Monitoring (Standalone Module)
------------------------------------------------------
Watches a folder for new or modified financial files (CSV, XLSX).
When a file is detected, it triggers a callback function.

How it works:
    1. You point it at a folder: watch("/path/to/data/")
    2. It sits quietly, monitoring for changes
    3. When a new .csv or .xlsx file appears → triggers your callback
    4. When an existing file is modified → triggers your callback
    5. Incremental: it only processes NEW changes, not full reload

Dependencies:
    pip install watchdog

Usage:
    from file_watcher import FolderWatcher

    def on_new_file(filepath: str, event_type: str):
        print(f"New file detected: {filepath} ({event_type})")

    watcher = FolderWatcher(
        watch_dir="/path/to/financial/data/",
        callback=on_new_file,
    )
    watcher.start()    # starts watching in background
    watcher.stop()     # stop watching
"""

from __future__ import annotations

import sys
import time
import logging
from pathlib import Path
from typing import Callable, Optional, Set

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

logger = logging.getLogger(__name__)

# File extensions we care about
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsm"}


# ── Event Handler ─────────────────────────────────────────────────────────────
class FinancialFileHandler(FileSystemEventHandler):
    """
    Watches for file system events (created, modified) and fires a callback
    only for supported financial file types (.csv, .xlsx, .xls).

    Ignores:
        - Temporary files (~$xxx.xlsx, .tmp, .swp)
        - Hidden files (starting with .)
        - Non-financial formats (.txt, .pdf, .doc, etc.)
    """

    def __init__(
        self,
        callback: Callable[[str, str], None],
        extensions: Optional[Set[str]] = None,
    ):
        super().__init__()
        self.callback = callback
        self.extensions = extensions or SUPPORTED_EXTENSIONS
        self._recently_processed: dict[str, float] = {}
        self._debounce_seconds = 2.0  # ignore duplicate events within 2 sec

    def on_created(self, event: FileSystemEvent):
        """Triggered when a new file appears in the watched folder."""
        if not event.is_directory:
            self._handle(event.src_path, "created")

    def on_modified(self, event: FileSystemEvent):
        """Triggered when an existing file is modified."""
        if not event.is_directory:
            self._handle(event.src_path, "modified")

    def _handle(self, filepath: str, event_type: str):
        """Check if the file is a supported type and not a temp/hidden file."""
        path = Path(filepath)

        # Skip hidden files and temp files
        if path.name.startswith(".") or path.name.startswith("~$"):
            return

        # Skip unsupported extensions
        if path.suffix.lower() not in self.extensions:
            return

        # Debounce: some editors save files multiple times rapidly
        now = time.time()
        last = self._recently_processed.get(filepath, 0)
        if now - last < self._debounce_seconds:
            return
        self._recently_processed[filepath] = now

        logger.info(f"File {event_type}: {filepath}")
        self.callback(filepath, event_type)


# ── Watcher Class ─────────────────────────────────────────────────────────────
class FolderWatcher:
    """
    Watches a folder for new/modified financial files.

    Usage:
        watcher = FolderWatcher("/data/", callback=my_function)
        watcher.start()      # runs in background thread
        # ... do other stuff ...
        watcher.stop()       # stop watching

    Or use as context manager:
        with FolderWatcher("/data/", callback=fn) as w:
            time.sleep(60)   # watch for 60 seconds
    """

    def __init__(
        self,
        watch_dir: str,
        callback: Callable[[str, str], None],
        recursive: bool = True,
    ):
        """
        Args:
            watch_dir:  path to the folder to watch
            callback:   function(filepath, event_type) called on each event
            recursive:  also watch sub-folders? (default: True)
        """
        self.watch_dir = Path(watch_dir)
        if not self.watch_dir.is_dir():
            raise ValueError(f"Watch directory not found: {watch_dir}")

        self.callback = callback
        self.recursive = recursive
        self._observer = Observer()
        self._handler = FinancialFileHandler(callback=callback)
        self._running = False

    def start(self):
        """Start watching (non-blocking — runs in a background thread)."""
        self._observer.schedule(
            self._handler,
            str(self.watch_dir),
            recursive=self.recursive,
        )
        self._observer.start()
        self._running = True
        logger.info(f"Watching folder: {self.watch_dir}")

    def stop(self):
        """Stop watching."""
        if self._running:
            self._observer.stop()
            self._observer.join()
            self._running = False
            logger.info("File watcher stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

    watch_path = sys.argv[1] if len(sys.argv) > 1 else "."

    def handle_file(filepath: str, event_type: str):
        print(f"  >> [{event_type.upper()}] {filepath}")

    print(f"Watching: {Path(watch_path).resolve()}")
    print(f"Drop a .csv or .xlsx file to test. Press Ctrl+C to stop.\n")

    with FolderWatcher(watch_path, callback=handle_file):
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
