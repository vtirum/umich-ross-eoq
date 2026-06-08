import csv
import threading
from pathlib import Path


def write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class IncrementalManifest:
    """Thread-safe CSV writer that flushes each row immediately.

    Safe to call .append() from multiple threads concurrently. If the script
    crashes mid-run, all rows written so far are preserved on disk.
    """

    def __init__(self, path, fieldnames):
        self.path = Path(path)
        self.fieldnames = fieldnames
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()

    def append(self, row):
        with self._lock:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=self.fieldnames).writerow(row)
