"""
Manifest writers. Every downloader records what it fetched, from where, and its hash.

Three shapes, because the scripts differ in how they run:

  write_csv            one-shot write at the end of a run
  merge_csv            merge new rows into an existing manifest on a key, so a run
                       scoped to part of the data does not erase the rest
  IncrementalManifest  thread-safe, flushes each row as it lands, for the long
                       concurrent API pulls where a crash must not lose the record
"""

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


def merge_csv(path, rows, fieldnames, key):
    """Write rows, keeping any earlier rows this run did not touch.

    Scripts that are scoped by an environment variable (KS_ASSESS_LEVELS,
    MN_LEVELS, KS_YEARS...) only produce manifest rows for the slice they just
    ran. With write_csv that silently discards everything from previous runs -
    Kansas ended up with a 4-row manifest describing 22 files on disk. This
    merges on `key` (usually local_path) so the manifest describes the whole
    output directory rather than the last invocation.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get(key):
                    existing[row[key]] = row
    for row in rows:
        if row.get(key):
            existing[row[key]] = row
    merged = sorted(existing.values(), key=lambda r: str(r.get(key, "")))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged)
    return merged


class IncrementalManifest:
    """Thread-safe CSV writer that flushes each row immediately.

    Safe to call .append() from multiple threads concurrently. If the script
    crashes mid-run, all rows written so far are preserved on disk.

    Prior rows are carried forward. A run scoped to part of the data (one fiscal year,
    one report) would otherwise truncate the manifest to just that slice and lose the
    record of everything collected before it - AZ's report-card manifest went from
    eight fiscal years to one that way. Pass `key` to have finalize() drop the stale
    copy of any row this run rewrote; without it, prior rows are kept as-is.
    """

    def __init__(self, path, fieldnames, key=None):
        self.path = Path(path)
        self.fieldnames = fieldnames
        self.key = tuple(key) if key else None
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prior = self._read_prior()
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(prior)      # written up front so a crash cannot lose them

    def _read_prior(self):
        if not self.path.exists():
            return []
        try:
            with open(self.path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            return []
        # a changed schema means the old file describes something else; start clean
        if rows and set(rows[0]) - set(self.fieldnames):
            return []
        return rows

    def append(self, row):
        with self._lock:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=self.fieldnames,
                               extrasaction="ignore").writerow(row)

    def finalize(self):
        """Collapse duplicates on `key`, keeping the newest write. No-op without a key."""
        if not self.key:
            return
        with self._lock:
            with open(self.path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            merged = {}
            for r in rows:
                merged[tuple(r.get(k, "") for k in self.key)] = r
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=self.fieldnames, extrasaction="ignore")
                w.writeheader()
                w.writerows(merged.values())
        return len(rows) - len(merged)
