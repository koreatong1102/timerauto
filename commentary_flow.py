"""Bounded relationships between confirmed events; never classifies a punch."""
from collections import OrderedDict, deque
import math


def target_group(value):
    key = str(value or "").lower().replace("_", "")
    if key in ("liver", "solarplexus"):
        return "body"
    if key in ("eyeleft", "eyeright", "chin", "nose", "templeleft", "templeright", "forehead"):
        return "head"
    return ""


class ExchangeContext:
    def __init__(self):
        self.rounds = OrderedDict()

    def observe(self, round_no, row, *, counter=False, combo_hits=0):
        try:
            stamp, damage = float(row["time"]), float(row.get("damage") or 0)
        except (KeyError, ValueError, TypeError):
            return {}
        if not math.isfinite(stamp) or not math.isfinite(damage) or stamp < 0:
            return {}
        state = self.rounds.setdefault(round_no, {"stamp": None, "clock": 0., "hits": deque(maxlen=32), "chains": {}})
        self.rounds.move_to_end(round_no)
        while len(self.rounds) > 4:
            self.rounds.popitem(last=False)
        if state["stamp"] is not None:
            # Events arrive in acquisition order. Either official clock direction
            # is supported without sorting/deleting a counter or combo verdict.
            state["clock"] += abs(stamp - state["stamp"])
        state["stamp"] = stamp
        clock = state["clock"]
        side, receiver = row.get("attacker_side"), row.get("receiver_side")
        if side not in ("blue", "red") or receiver not in ("blue", "red") or side == receiver:
            return {}
        recent = [item for item in state["hits"] if 0 <= clock - item["at"] <= 8]
        trailing = []
        for item in reversed(recent):
            if item["side"] == side or clock - item["at"] > 3:
                break
            trailing.append(item)
        group = target_group(row.get("weak_point"))
        own = [item for item in recent if item["side"] == side]
        switch = bool(group and len(own) >= 3 and own[-1]["group"]
                      and all(item["group"] == own[-1]["group"] for item in own[-3:])
                      and own[-1]["group"] != group)
        chain = state["chains"].get(side) or {}
        continuation = bool(combo_hits > 1 and 0 < chain.get("hits", 0) < combo_hits
                            and 0 <= clock - chain.get("at", -99) <= 7)
        release = bool(continuation and chain.get("counter") and combo_hits >= 3)
        if combo_hits:
            state["chains"][side] = {"hits": combo_hits, "at": clock,
                                      "counter": bool(counter or (continuation and chain.get("counter")))}
        out = {"flow_clock": clock, "exchange_return": damage >= 10 and len(trailing) >= 2,
               "counter_release": release, "target_switch": switch and damage >= 10,
               "target_group": group, "opponent_streak": len(trailing),
               "pacing_hot": combo_hits >= 3 or sum(clock - item["at"] <= 2 for item in recent) >= 3}
        if damage >= 10 and str(row.get("punch") or "").lower() not in ("pull", "other"):
            state["hits"].append({"side": side, "at": clock, "group": group})
        return out
