"""Bounded shutdown work without blocking the Qt message pump."""
import logging
import threading
import time


def finish_shutdown(tasks, timeout=8.0):
    """Run independent cleanup groups in parallel, retaining the UI event loop.

    Each group must contain no Qt widget access. Dependencies belong in the same
    group (e.g. disable Source Record before disconnecting OBS). Never terminate
    a thread: unfinished groups are diagnosed and daemonized at the deadline.
    """
    from PyQt6.QtCore import QEventLoop, QTimer
    pending = {}
    for name, callback in tasks:
        done = threading.Event()
        pending[name] = done

        def run(label=name, work=callback, completed=done):
            start = time.monotonic()
            logging.info('APP_SHUTDOWN_STEP_BEGIN step=%s', label)
            try:
                work()
            except Exception:
                logging.exception('APP_SHUTDOWN_STEP_FAIL step=%s', label)
            finally:
                logging.info('APP_SHUTDOWN_STEP_END step=%s seconds=%.3f', label, time.monotonic()-start)
                completed.set()

        threading.Thread(target=run, name='shutdown-'+name, daemon=True).start()
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    deadline = time.monotonic()+max(0.01, timeout)

    def poll():
        if all(event.is_set() for event in pending.values()) or time.monotonic() >= deadline:
            loop.quit()

    timer.timeout.connect(poll)
    timer.start()
    if any(not event.is_set() for event in pending.values()):
        loop.exec()
    timer.stop()
    remaining = [name for name, event in pending.items() if not event.is_set()]
    if remaining:
        logging.error('APP_SHUTDOWN_DEADLINE pending=%s', ','.join(remaining))
    return remaining
