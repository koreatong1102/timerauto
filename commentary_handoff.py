"""Prepared-audio handoff policy; no Qt, network, verdicts or sleeps."""
import json
import math
from pathlib import Path


def importance(timing):
    category = timing.get("category", "")
    if timing.get("kind") == "terminal" and category != "stun":
        return 3
    if category in ("stun", "counter", "counter_context", "counter_combo", "combo", "combo_context", "answer_back") or timing.get("scene") in ("heavy", "long_combo"):
        return 2
    return 1


def sentence_ends(path):
    """Edge offsets are 100ns ticks. Old cache files may have no sidecar.

    Never fabricate word timing by dividing a clip's duration by text length.
    """
    try:
        metadata = Path(str(path) + ".timing.jsonl")
        if metadata.stat().st_size > 512_000:
            return ()
        ends = []
        with metadata.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row.get("type") != "SentenceBoundary":
                    continue
                end = (float(row["offset"]) + float(row["duration"])) / 10_000
                if math.isfinite(end) and 0 <= end <= 600_000:
                    ends.append(int(end))
        return tuple(sorted(set(ends)))
    except (OSError, ValueError, TypeError, KeyError):
        return ()


def handoff_delay(incoming, current, *, position_ms=0, duration_ms=0, boundaries=()):
    """None = do not interrupt. Zero = ready to fade; >0 = clause wait.

    Ordinary hits never interrupt. Reports and the final TKO call are protected.
    An important exchange may wait at most 550ms for a real sentence boundary;
    otherwise let the sentence finish or let the incoming call expire.
    """
    if current.get("kind") == "report" or current.get("category") == "tko":
        return None
    rank = importance(incoming)
    if rank == 1 or (importance(current) > rank and current.get("kind") != "reply"):
        return None
    if rank == 3:
        return 0
    if 0 < duration_ms - position_ms <= 650:
        return None  # Almost finished: let the natural EndOfMedia do the handoff.
    for boundary in boundaries:
        delta = boundary - position_ms
        if 0 <= delta <= 550:
            return delta
    return None
