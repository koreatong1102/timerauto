"""Presentation of one already-selected report combo, not new combat rules."""
import math


def punch_label(event):
    punch = str(event.get("punch") or "").replace("_", "").replace(" ", "").lower()
    hand = str(event.get("hand") or "").strip().lower()
    prefix = {"left": "L.", "right": "R."}.get(hand, "")
    # Lead/rear describes stance, not an absolute left/right hand. Never infer
    # handedness from that prefix (southpaw fighters would be mislabeled).
    for stance in ("lead", "rear"):
        if punch.startswith(stance):
            punch = punch[len(stance):]
            break
    if punch == "jab":
        return "JAB"
    if punch == "cross":
        return "CROSS"
    kind = {"hook": "HOOK", "uppercut": "UPPERCUT", "overhand": "OVERHAND",
            "straight": "STRAIGHT"}.get(punch)
    return prefix + kind if kind else "PUNCH"


def classified_combo_rows(events, best_event, side):
    """Recover the chosen chain from canonical hit counts, without rejudging.

    Missing prefix/rows are an incomplete detail, not permission to invent
    punches. Round-local central counts decide resets and interruptions.
    """
    chain = []
    active_round = None
    for event in events:
        round_no = event.get("_report_round")
        if active_round != round_no:
            chain = []
            active_round = round_no
        if str(event.get("attacker_side") or "").lower() != side:
            continue
        hits = int(event.get("combo_hits", 0) or 0)
        if hits == 1:
            chain = [event]
        elif hits > 1:
            same_receiver = chain and chain[-1].get("receiver_side") == event.get("receiver_side")
            chain = chain + [event] if same_receiver and hits == len(chain)+1 else []
        if event is best_event:
            return chain if len(chain) == hits else []
    return []


def combo_details(rows, hits, damage):
    # Detail and displayed total must describe exactly the same selected chain.
    try:
        total = sum(float(row.get("damage", 0) or 0) for row in rows)
    except (TypeError, ValueError):
        rows, total = [], 0
    complete = hits >= 2 and len(rows) == hits and math.isfinite(total) and math.isclose(total,damage,abs_tol=.05)
    if not complete:
        return {"maxComboSequence": [], "maxComboDetail": "", "maxComboRound": 0,
                "maxComboCounterStart": False, "maxComboDownFinish": False}
    sequence = [punch_label(row) for row in rows]
    first, last = rows[0], rows[-1]
    central = first.get("_central_event") or {}
    counter = bool(central.get("counter",first.get("is_counter",False)))
    effect = str(last.get("effect_kind") or (last.get("_central_event") or {}).get("effect_kind") or "").lower()
    damage_type = str(last.get("damage_type") or "").lower()
    down = effect in ("knockdown","down","ko","tko") or damage_type in ("knockdown","ko","tko")
    return {"maxComboSequence": sequence, "maxComboDetail": " → ".join(sequence),
            "maxComboRound": int(last.get("_report_round",last.get("round",0)) or 0),
            "maxComboCounterStart": counter, "maxComboDownFinish": down}
