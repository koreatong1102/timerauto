"""File-export workers receive detached plain values, never Qt objects."""
import threading


class BackgroundExportJob:
    def __init__(self, function, kwargs):
        self.done = threading.Event()
        self.path = ""
        self.error = ""
        def run():
            try:
                self.path = function(**kwargs)
            except Exception as exc:
                self.error = str(exc)
            finally:
                self.done.set()
        threading.Thread(target=run, name="ProjectSnapshotExport", daemon=True).start()
