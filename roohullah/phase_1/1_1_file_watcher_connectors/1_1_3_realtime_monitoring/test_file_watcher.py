"""
Tests for 1.1.3 Real-Time File Monitoring
-------------------------------------------
Run: python -m pytest test_file_watcher.py -v
"""

import os
import tempfile
import time

import pytest
from file_watcher import FolderWatcher, FinancialFileHandler, SUPPORTED_EXTENSIONS


# ── Test: handler filters correctly ───────────────────────────────────────────
def test_supported_extensions():
    assert ".csv" in SUPPORTED_EXTENSIONS
    assert ".xlsx" in SUPPORTED_EXTENSIONS
    assert ".xls" in SUPPORTED_EXTENSIONS
    assert ".txt" not in SUPPORTED_EXTENSIONS
    assert ".pdf" not in SUPPORTED_EXTENSIONS


def test_handler_ignores_hidden_files():
    events = []
    handler = FinancialFileHandler(callback=lambda fp, et: events.append(fp))
    # Simulate a hidden file event
    handler._handle(".hidden_file.csv", "created")
    assert events == []


def test_handler_ignores_temp_files():
    events = []
    handler = FinancialFileHandler(callback=lambda fp, et: events.append(fp))
    handler._handle("~$tempfile.xlsx", "created")
    assert events == []


def test_handler_fires_for_csv():
    events = []
    handler = FinancialFileHandler(callback=lambda fp, et: events.append(fp))
    handler._handle("transactions.csv", "created")
    assert len(events) == 1
    assert events[0] == "transactions.csv"


def test_handler_fires_for_xlsx():
    events = []
    handler = FinancialFileHandler(callback=lambda fp, et: events.append(fp))
    handler._handle("ledger.xlsx", "modified")
    assert len(events) == 1


def test_handler_debounce():
    """Rapid duplicate events should be debounced (ignored)."""
    events = []
    handler = FinancialFileHandler(callback=lambda fp, et: events.append(fp))
    handler._debounce_seconds = 5  # 5 second window

    handler._handle("data.csv", "created")
    handler._handle("data.csv", "modified")  # should be debounced
    assert len(events) == 1


# ── Test: watcher setup ──────────────────────────────────────────────────────
def test_watcher_rejects_invalid_dir():
    with pytest.raises(ValueError, match="not found"):
        FolderWatcher("/nonexistent/dir/", callback=lambda fp, et: None)


def test_watcher_accepts_valid_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        watcher = FolderWatcher(tmpdir, callback=lambda fp, et: None)
        assert watcher.is_running is False


def test_watcher_start_stop():
    """Watcher should start and stop cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        watcher = FolderWatcher(tmpdir, callback=lambda fp, et: None)
        watcher.start()
        assert watcher.is_running is True
        watcher.stop()
        assert watcher.is_running is False


def test_watcher_context_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        with FolderWatcher(tmpdir, callback=lambda fp, et: None) as w:
            assert w.is_running is True
        assert w.is_running is False


def test_watcher_detects_new_csv():
    """Drop a CSV into the watched folder — callback should fire."""
    events = []

    def on_file(filepath, event_type):
        events.append({"path": filepath, "type": event_type})

    with tempfile.TemporaryDirectory() as tmpdir:
        with FolderWatcher(tmpdir, callback=on_file):
            # Create a CSV file in the watched folder
            csv_path = os.path.join(tmpdir, "test_data.csv")
            with open(csv_path, "w") as f:
                f.write("Date,Amount\n2026-01-01,5000\n")

            # Give watchdog time to detect the file
            time.sleep(1)

        # At least one event should have fired
        assert len(events) >= 1
        assert any("test_data.csv" in e["path"] for e in events)
