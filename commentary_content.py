"""Bounded local content direction; never classifies punches or generates facts."""


def subject(script, scene):
    """Authored metadata takes precedence; legacy lines share conservative topics.

    Broad fallback topics deliberately group paraphrases instead of treating a
    different string as a new joke. No keyword guessing on rendered nicknames.
    """
    intent = script.intent or (
        "change" if scene in ("reversal", "permission_reverse") and script.family in ("analysis", "contrast", "callback") else
        "pattern" if scene in ("repeat_counter", "target_repeat", "eye_seed", "eye_return", "permission_return") and (script.family in ("analysis", "callback") or script.seed) else
        "analysis" if script.family == "analysis" else
        "reaction" if script.family == "reaction" else "humor")
    group = ("counter" if scene in ("counter", "whiff", "graze", "repeat_counter") else
             "combo" if scene in ("combo", "counter_combo", "long_combo") else
             "target" if scene in ("weak", "target_repeat", "eye_seed", "eye_return") else scene)
    topic = script.topic or (
        "self_incompetence" if script.family == "self" else
        "commentators_bickering" if script.family == "banter" else
        "audience_attention" if script.family == "audience" else
        f"{group}:{script.family}")
    # These are the same observation, even though one says "another hit" and
    # another says "hits accumulating". Metadata is not a license to count
    # paraphrases as fresh perspectives.
    topic = {"target_new_hit": "target_accumulation", "target:analysis": "target_accumulation"}.get(topic, topic)
    # Evidence-based observations are specific to a fighter/round. Generic
    # jokes remain global: switching fighters must not repeat the same gag.
    return {"intent": intent, "topic": topic,
            "evidence": intent in ("change", "pattern", "analysis")}


def topic_key(meta, side, round_no):
    return (meta["topic"], side if meta.get("evidence") else "",
            round_no if meta.get("evidence") else 0)


def plan(scripts, *, scene, side, round_no, heard, pending, now, density, terminal=False):
    """Choose an intent BEFORE choosing wording. Empty pool means call only.

    Actual audio gets a 75-second topic rest. In-flight selection only reserves
    eight seconds; failed synthesis never spends the heard-topic allowance.
    """
    reservations = [item for item in pending if 0 <= now - item["at"] < 8]
    spoken = [item for item in heard if item.get("intent") != "call"]
    recent_reply = spoken + [{**meta, "at": item["at"]} for item in reservations for meta in item.get("content", ())
                             if meta.get("intent") != "call"]
    latest = max([item.get("completed_at", item.get("at", -1e9)) for item in recent_reply] or [-1e9])
    # Pattern changes may deserve an explanation, but not another two-voice
    # exchange six seconds after the last one. Keep the factual call intact.
    gap = 18 if density == "full" else 24
    if not terminal and now - latest < gap:
        return [], "recent_reply"
    used = {topic_key(item, item.get("side", ""), item.get("round", 1))
            for item in spoken if 0 <= now - item["completed_at"] < 75}
    used.update(topic_key(meta, item.get("side", ""), item.get("round", 1))
                for item in reservations for meta in item.get("content", ())
                if meta.get("intent") != "call")
    fresh = [script for script in scripts if topic_key(subject(script, scene), side, round_no) not in used]
    if not fresh:
        return (list(scripts), "terminal") if terminal else ([], "topics_rested")
    # Different material, not a fixed every-third-call counter. Evidence-based
    # changes get first refusal, then alternate interpretation and entertainment.
    last = spoken[-1] if spoken else {}
    if scene in ("reversal", "permission_reverse"):
        order = ("change", "humor", "reaction", "analysis", "pattern")
    elif scene in ("repeat_counter", "target_repeat", "eye_seed", "eye_return", "permission_return") and last.get("intent") != "pattern":
        order = ("pattern", "humor", "reaction", "analysis", "change")
    elif last.get("intent") in ("humor", "reaction"):
        order = ("analysis", "pattern", "change", "humor", "reaction")
    else:
        order = ("humor", "reaction", "analysis", "pattern", "change")
    for intent in order:
        pool = [script for script in fresh if subject(script, scene)["intent"] == intent]
        if pool:
            return pool, intent
    return fresh, "reaction"
