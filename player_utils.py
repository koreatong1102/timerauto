from __future__ import annotations

import re
from typing import Any

try:
    from rapidfuzz import fuzz as rf_fuzz
    HAS_RAPIDFUZZ = True
except Exception:
    rf_fuzz = None
    HAS_RAPIDFUZZ = False


def player_gid_key_for_match(gid: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(gid or "").upper())


def player_similarity_for_match(a: str, b: str) -> int:
    sa = str(a or "").strip().lower()
    sb = str(b or "").strip().lower()
    if not sa or not sb:
        return 0
    if HAS_RAPIDFUZZ and rf_fuzz is not None:
        try:
            return int(rf_fuzz.ratio(sa, sb))
        except Exception:
            pass
    common = sum(1 for ch in sa if ch in sb)
    return int(100 * common / max(1, max(len(sa), len(sb))))


def canonical_player_gid_for_cfg(cfg: Any, gid: str, threshold: int = 70) -> str:
    raw = str(gid or "").strip().upper()
    if not raw:
        return ""
    players = getattr(cfg, "players", {}) or {}
    if raw in players:
        return raw
    key = player_gid_key_for_match(raw)
    if not key:
        return raw
    best_gid = ""
    best_sc = -1
    for existing_gid in players.keys():
        ex = str(existing_gid or "").strip().upper()
        if not ex:
            continue
        ex_key = player_gid_key_for_match(ex)
        if not ex_key:
            continue
        if ex_key == key:
            return ex
        sc = player_similarity_for_match(key, ex_key)
        if sc > best_sc:
            best_sc = sc
            best_gid = ex
    if best_sc >= int(threshold):
        return best_gid
    return raw
