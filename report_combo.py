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


def combo_clock(rows, round_events, duration):
    """Convert verified clock direction to elapsed time, without a live-clock guess.

    Modern docs specify elapsed; older recordings actually count down. Use
    append order inside this round, not the current round_time mode for a
    possibly different round. Mixed/unknown direction remains unreported.
    """
    empty = {"maxComboStartSeconds":None,"maxComboEndSeconds":None,
             "maxComboStartTimeText":"","maxComboTimeBasis":"unknown"}
    try:
        start,end = float(rows[0]["time"]),float(rows[-1]["time"])
        values = [float(row["time"]) for row in round_events if "time" in row]
        if not all(math.isfinite(value) and value >= 0 for value in [start,end]+values):
            return empty
        differences = [b-a for a,b in zip(values,values[1:]) if abs(b-a)>.005]
        increasing = any(delta>0 for delta in differences)
        decreasing = any(delta<0 for delta in differences)
        if increasing and not decreasing:
            basis = "elapsed"
        elif decreasing and not increasing:
            length = float(duration)
            if not math.isfinite(length) or length <= 0 or max(values)>length+.05:
                return empty
            start,end = max(0,length-start),max(0,length-end)
            basis = "converted_remaining"
        else:
            return empty
        seconds = int(start)
        return {"maxComboStartSeconds":round(start,2),"maxComboEndSeconds":round(end,2),
                "maxComboStartTimeText":f"{seconds//60}:{seconds%60:02d}","maxComboTimeBasis":basis}
    except (IndexError,KeyError,TypeError,ValueError,OverflowError):
        return empty


def combo_details(rows, hits, damage, *, round_events=(), duration=None):
    # Detail and displayed total must describe exactly the same selected chain.
    try:
        total = sum(float(row.get("damage", 0) or 0) for row in rows)
    except (TypeError, ValueError):
        rows, total = [], 0
    complete = hits >= 2 and len(rows) == hits and math.isfinite(total) and math.isclose(total,damage,abs_tol=.05)
    if not complete:
        return {"maxComboSequence": [], "maxComboDetail": "", "maxComboRound": 0,
                "maxComboCounterStart": False, "maxComboDownFinish": False,
                **combo_clock([],[],duration)}
    sequence = [punch_label(row) for row in rows]
    first, last = rows[0], rows[-1]
    central = first.get("_central_event") or {}
    counter = bool(central.get("counter",first.get("is_counter",False)))
    effect = str(last.get("effect_kind") or (last.get("_central_event") or {}).get("effect_kind") or "").lower()
    damage_type = str(last.get("damage_type") or "").lower()
    down = effect in ("knockdown","down","ko","tko") or damage_type in ("knockdown","ko","tko")
    return {"maxComboSequence": sequence, "maxComboDetail": " → ".join(sequence),
            "maxComboRound": int(last.get("_report_round",last.get("round",0)) or 0),
            "maxComboCounterStart": counter, "maxComboDownFinish": down,
            **combo_clock(rows,round_events or rows,duration)}
