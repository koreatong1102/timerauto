"""Single-pass video metadata scan, with one bounded background worker."""
from __future__ import annotations

import os
import stat
import threading
from dataclasses import dataclass

from video_formats import VIDEO_EXTENSIONS


@dataclass(frozen=True)
class VideoLibrarySnapshot:
    path: str
    files: tuple[str, ...]
    signature: tuple[tuple[str, int, int], ...]
    generation: int = 0
    error: str = ""


def scan_video_library(path: str) -> VideoLibrarySnapshot:
    """Read metadata once per video; no decoding, opening media, or file writes."""
    rows = []
    try:
        if not path:
            return VideoLibrarySnapshot(path, (), ())
        try:
            info = os.stat(path)
        except FileNotFoundError:
            return VideoLibrarySnapshot(path, (), ())
        if stat.S_ISREG(info.st_mode):
            if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS and info.st_size > 0:
                rows.append((os.path.abspath(path), info.st_mtime_ns, info.st_size))
        elif stat.S_ISDIR(info.st_mode):
            stack = [path]
            while stack:
                with os.scandir(stack.pop()) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            elif os.path.splitext(entry.name)[1].lower() in VIDEO_EXTENSIONS and entry.is_file():
                                value = entry.stat()
                                if value.st_size > 0:
                                    rows.append((os.path.abspath(entry.path), value.st_mtime_ns, value.st_size))
                        except FileNotFoundError:
                            continue  # A recording was moved/deleted during enumeration.
        rows.sort(key=lambda row: row[0])
        return VideoLibrarySnapshot(path, tuple(row[0] for row in rows),
            tuple((os.path.normcase(p), int(m), int(s)) for p, m, s in rows))
    except OSError as exc:
        # Never replace a good playlist with an incomplete permission/I/O scan.
        return VideoLibrarySnapshot(path, (), (), error=str(exc))


class IdleVideoScanner:
    """Coalesce overlapping requests; late results cannot overwrite a new path."""
    def __init__(self, notify):
        self._notify = notify
        self._lock = threading.Lock()
        self._path = ""
        self._generation = 0
        self._running = False
        self._closed = False

    def request(self, path: str) -> bool:
        with self._lock:
            if self._closed:
                return False
            if path != self._path:
                self._path = path
                self._generation += 1
            if self._running:
                return False
            # Also distinguish two scans of the same path: a queued older Qt
            # result must not overwrite a newer scan after a scheduling race.
            self._generation += 1
            self._running = True
        threading.Thread(target=self._run, name="IdleVideoLibrary", daemon=True).start()
        return True

    def is_current(self, result: VideoLibrarySnapshot) -> bool:
        with self._lock:
            return not self._closed and (result.path, result.generation) == (self._path, self._generation)

    def close(self):
        with self._lock:
            self._closed = True
            self._generation += 1

    def _run(self):
        while True:
            with self._lock:
                if self._closed:
                    self._running = False
                    return
                path, generation = self._path, self._generation
            result = scan_video_library(path)
            with self._lock:
                if self._closed:
                    self._running = False
                    return
                if (path, generation) != (self._path, self._generation):
                    continue
                self._running = False
            try:
                self._notify(VideoLibrarySnapshot(path, result.files, result.signature, generation, result.error))
            except RuntimeError:
                return  # Qt receiver was destroyed during shutdown.
            return
