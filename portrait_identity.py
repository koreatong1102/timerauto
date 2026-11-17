"""Bind decoded official portraits to a fighter and a match, not name.txt's age.

The spectator tool can rewrite name.txt between rounds without recapturing the
portrait. A receipt is written only after a complete PNG was decoded. It can
survive a restart of this same match, but cannot authorize another fighter,
another file, or another match. No images are decoded on the UI lookup path.
"""
import json
import logging
import os
from pathlib import Path
import tempfile
import threading


def _snapshot(path):
    path = os.path.normcase(os.path.abspath(path))
    stat = os.stat(path)
    if not stat.st_size:
        raise ValueError('empty portrait')
    name_path = os.path.join(os.path.dirname(path), 'name.txt')
    raw = Path(name_path).read_bytes()
    try:
        name = raw.decode('utf-8-sig').strip().casefold()
    except UnicodeDecodeError:
        name = raw.decode('cp949').strip().casefold()
    if not name:
        raise ValueError('missing fighter identity')
    record = dict(path=path, name=name,
                  signature=[stat.st_mtime_ns, stat.st_size, stat.st_dev, stat.st_ino])
    return record, os.stat(name_path).st_mtime_ns


class PortraitOwnership:
    def __init__(self):
        self._lock = threading.RLock()
        self._scope = None
        self._path = None
        self._owners = {}

    def bind(self, directory='', session_id=''):
        """Load at most once per match. A different match never inherits receipts."""
        scope = (os.path.abspath(directory) if directory else '', str(session_id or ''))
        with self._lock:
            if scope == self._scope:
                return
            self._scope, self._owners = scope, {}
            self._path = Path(scope[0], 'portrait_owners.json') if all(scope) else None
            if self._path is None:
                return
            try:
                if self._path.stat().st_size > 32768:
                    return
                data = json.loads(self._path.read_text(encoding='utf-8'))
                if data.get('version') == 1 and data.get('session_id') == scope[1]:
                    self._owners = dict(data.get('portraits') or {})
            except (OSError, ValueError, TypeError, AttributeError):
                self._owners = {}

    def candidate(self, side, path):
        with self._lock:
            try:
                record, name_mtime = _snapshot(path)
                fresh = record['signature'][0] + 100_000_000 >= name_mtime
                if fresh or record == self._owners.get(side):
                    return dict(record, _scope=self._scope)
            except (OSError, ValueError, UnicodeError):
                pass
            return None

    def confirm(self, side, record):
        """Called after PNG decode; reject identity/file changes during that read."""
        with self._lock:
            if record.get('_scope') != self._scope:
                return False
            if self.candidate(side, record['path']) != record:
                return False
            receipt = {key: value for key, value in record.items() if key != '_scope'}
            if self._owners.get(side) != receipt:
                self._owners[side] = receipt
                self._save()
            return True

    def _save(self):
        if self._path is None:
            return
        staged = ''
        try:
            fd, staged = tempfile.mkstemp(prefix='portrait_owners_', suffix='.tmp', dir=self._path.parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(dict(version=1, session_id=self._scope[1], portraits=self._owners),
                          stream, ensure_ascii=False)
            os.replace(staged, self._path)
            staged = ''
        except OSError:
            # Receipt persistence failure must not hide a successfully decoded face.
            logging.warning('PORTRAIT_OWNERSHIP_SAVE_FAILED path=%s', self._path)
        finally:
            if staged:
                try:
                    os.unlink(staged)
                except OSError:
                    pass
