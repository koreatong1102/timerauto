"""Bounded Source Record capture identity and live replay expiry checks."""
import math


def result_wait(context):
    return max(1.0, min(20.0, float(context.get('auto_replay_source_wait_sec') or 5.0)))


def file_matches_capture(meta, stat):
    """A new filename alone is not proof that it belongs to the oldest request.

    Replay files are created after the save RPC, unlike the continuously open
    recording in the same folder. Birth time remains valid while MP4 finalizes.
    Other platforms without birth time use mtime (primarily test environments).
    """
    try:
        requested = float(meta.get('requested_wall') or 0.0)
        if not requested or not math.isfinite(requested):
            return False
        created = float(getattr(stat, 'st_birthtime', stat.st_mtime))
        return requested - .1 <= created <= requested + result_wait(meta.get('context') or {})
    except (TypeError, ValueError, OverflowError):
        return False


def live_replay_expired(context, now, delay_sec=0.0):
    """Check again at start, not only when a saved file first reaches the app."""
    try:
        explicit = float(context.get('auto_replay_deadline_monotonic') or 0.0)
        if explicit:
            return not math.isfinite(explicit) or now > explicit
        triggered = float(context.get('trigger_monotonic') or 0.0)
        if not math.isfinite(triggered):
            return True
        if triggered <= 0:
            return False  # Legacy/manual preview without a live event timestamp.
        capture = max(0.0, float(context.get('replay_capture_delay_sec') or 0.0))
        wait = result_wait(context)
        budget = max(capture + wait, max(0.0, delay_sec) + 1.0)
        return not math.isfinite(budget) or now > triggered + budget
    except (TypeError, ValueError, OverflowError):
        return True
