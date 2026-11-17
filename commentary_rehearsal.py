"""Read-only archive rehearsal: no Qt, OBS, network, speech, or wall-clock waits."""
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path
import wave

from commentary_director import CommentaryDirector
from commentary_entertainment import BGradeCommentary
from commentary_story import SpokenMemory
from commentary_calls import SpokenFocus
from commentary_content import topic_key
from event_engine import FightEventEngine


TARGET_NAMES = {"eyeleft": "왼쪽 눈", "eyeright": "오른쪽 눈", "chin": "턱", "nose": "코",
                "templeleft": "왼쪽 관자놀이", "templeright": "오른쪽 관자놀이", "liver": "간", "solarplexus": "명치"}


def _spoken_text(text):
    value = " ".join(str(text or "").split())
    # Rehearsal names are fixed identifiers, not user nicknames. Live packs
    # omit this explicit focus prefix; do not strip arbitrary rendered words.
    for name in ("블루 선수", "레드 선수"):
        if value.startswith(name + ", "):
            return value[len(name) + 2:]
    return value


def _official_effect(row):
    kind = str(row.get("damage_type") or "").replace(" ", "").replace("_", "").lower()
    return {"stun": "stun", "knockdown": "knockdown", "down": "knockdown",
            "knockout": "knockdown", "ko": "knockdown",
            "technicalknockout": "tko", "tko": "tko"}.get(kind, "")


class _AudioAudit:
    """Read prepared WAV headers only; never create speech or fake timing."""
    def __init__(self, cfg):
        self.cfg, self.cache = cfg, {}

    def seconds(self, role, text):
        from commentary_pack import enabled, ready, clip_path
        from local_tts import commentary_voice, LocalTTSError
        if not enabled(self.cfg):
            return None, "unmeasured"
        key = role, _spoken_text(text)
        if key in self.cache:
            return self.cache[key]
        try:
            path = clip_path(commentary_voice(self.cfg, role, ""), key[1])
            if not ready(path):
                result = None, "missing_pack"
            else:
                with wave.open(str(path), "rb") as wav:
                    result = wav.getnframes() / wav.getframerate(), "prepared_wav"
        except (OSError, ValueError, wave.Error, LocalTTSError):
            result = None, "missing_pack"
        self.cache[key] = result
        return result


def _fact_key(row, round_no):
    return (int(round_no), round(float(row.get("time") or 0), 3), round(float(row.get("damage") or 0), 2),
            row.get("attacker_side"), row.get("receiver_side"), row.get("hand"), row.get("punch"),
            str(row.get("weak_point") or "").lower())


def _saved_verdicts(directory, ruleset):
    database = Path(directory, "match_archive.db").resolve()
    if not database.is_file():
        return {}
    output = {}
    # Do not instantiate the live ledger: its constructor can migrate/write.
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        for round_no, raw, verdict in connection.execute(
                "SELECT round_no,raw_json,classified_json FROM events WHERE kind='damage' AND classified_json IS NOT NULL AND ruleset_version=?", (ruleset,)):
            try:
                output[_fact_key(json.loads(raw), round_no)] = json.loads(verdict)
            except (TypeError, ValueError):
                continue
    except sqlite3.DatabaseError:
        # Older archives can lack this table. Explicit fallback is reported.
        return {}
    finally:
        connection.close()
    return output


def rehearse_archive(path, cfg, *, drop_every=0):
    source = Path(path) / "damage_events.jsonl"
    bank, director, engine = BGradeCommentary(), CommentaryDirector(), FightEventEngine(cfg)
    bank.story.memory = SpokenMemory()
    bank.story.focus = SpokenFocus()
    bank.story.configure(cfg)
    # This is authored-coverage rehearsal, not a GPU job or a claim that new
    # scripts are already rendered in this user's chosen voice pack.
    bank.story.reply_filter = None
    audio = _AudioAudit(cfg)
    saved_verdicts = _saved_verdicts(path, engine.ruleset_version())
    transcript, malformed = [], 0
    simulated, previous_round, previous_time = 1000.0, None, None
    checked_events = 0
    saved_used = 0
    direction_steps = {}
    with source.open(encoding="utf-8-sig") as stream:
        for index, line in enumerate(stream):
            try:
                record = json.loads(line)
                row = dict(record["event"])
                round_no = max(1, int(record.get("round") or row.get("round") or 1))
                stamp = float(row.get("time") or 0)
                if not math.isfinite(stamp):
                    raise ValueError("non-finite clock")
            except (ValueError, KeyError, TypeError):
                malformed += 1
                continue
            checked_events += 1
            if round_no != previous_round:
                engine.reset()
                simulated += 60 if previous_round is not None else 0
            elif previous_time is not None:
                step = stamp - previous_time
                if abs(step) > .01:
                    direction_steps.setdefault(round_no, Counter())["elapsed" if step > 0 else "remaining"] += 1
                # New logs can count up and older ones count down. Preserve
                # archive delivery order, not an incorrectly sorted clock.
                simulated += abs(step)
            previous_round, previous_time = round_no, stamp
            regenerated = engine.classify(row)
            verdict = saved_verdicts.get(_fact_key(row, round_no))
            if verdict:
                saved_used += 1
            row["_central_event"] = dict(verdict or regenerated)
            if row["_central_event"].get("event_id"):
                row["event_id"] = row["_central_event"]["event_id"]
            row["effect_kind"] = (row["_central_event"].get("effect_kind")
                                  or row.get("effect_kind") or _official_effect(row))
            bank.story.observe(round_no, [row])
            side = str(row.get("attacker_side") or "")
            receiver = str(row.get("receiver_side") or "")
            if side not in ("blue", "red") or receiver not in ("blue", "red"):
                continue
            call = bank.event_call(row, name="블루 선수" if side == "blue" else "레드 선수",
                receiver="블루 선수" if receiver == "blue" else "레드 선수",
                target=TARGET_NAMES.get(str(row.get("weak_point") or "").lower(), "급소"),
                min_damage=float(getattr(cfg, "spectator_commentary_min_damage", 25)),
                key=f"archive:{index}", now=simulated)
            if getattr(cfg, "spectator_commentary_mode", "standard") == "quiet" and call and call.category not in ("stun", "knockdown", "tko"):
                call = None
            decision = director.choose_live([call] if call else [],
                cooldown_sec=float(getattr(cfg, "spectator_commentary_cooldown_sec", 6)), now=simulated)
            if not decision.candidate:
                continue
            bank.accept_call(call)
            story = call.presentation["story"]
            completed = not drop_every or (len(transcript) + 1) % drop_every != 0
            heard = bank.story.memory.recent(bank.story.scope, now=simulated)
            required_seed = ("eyes" if story["scene"] == "eye_return" else "permission"
                             if story["family"] == "callback" else "")
            required_side = receiver if story["scene"] == "permission_reverse" else side
            valid_callback = not required_seed or any(item.get("seed") == required_seed
                and item.get("side") == required_side for item in heard)
            recent_content = bank.story.memory.recent_content(bank.story.scope, now=simulated, max_age=75)
            prior_topics = {topic_key(meta, meta.get("side", ""), meta.get("round", 1)) for meta in recent_content
                            if meta["intent"] != "call"}
            repeated_topics = [meta["topic"] for meta in story.get("content", ()) if meta["intent"] != "call"
                               and topic_key(meta, side, round_no) in prior_topics]
            terminal = story["scene"] in ("stun", "knockdown", "tko")
            turns = []
            for turn in call.presentation["turns"]:
                duration, source_kind = audio.seconds(turn["role"], turn["text"])
                turns.append({**turn, "audio_seconds": duration, "audio_timing_source": source_kind})
            transcript.append({"round": round_no, "game_time": stamp, "side": side,
                "scene": story["scene"], "family": story["family"], "swear": story["swear"],
                "direction": story.get("direction"), "content": story.get("content", []),
                "simulated_at": simulated,
                "reply_budget_seconds": story.get("reply_budget_seconds"),
                "pacing_reason": story.get("pacing_reason", "legacy"),
                "delivery": story.get("delivery", "neutral"),
                "repeated_topics": repeated_topics, "terminal": terminal,
                "turns": turns, "named": call.presentation["focus"]["named"],
                "valid_subject": bank.story.focus.valid(call.presentation["focus"], now=simulated),
                "completed": completed, "valid_callback": valid_callback})
            if completed:
                bank.story.focus.started(call.presentation["focus"], now=simulated)
                bank.story.memory.complete(story, now=simulated)
    text = " ".join(turn["text"] for row in transcript for turn in row["turns"])
    completed_turns = [(row, turn) for row in transcript if row["completed"] for turn in row["turns"]]
    phrases = Counter(_spoken_text(turn["text"]) for row, turn in completed_turns)
    recent_phrases, exact_recent_repeats = {}, 0
    for row, turn in completed_turns:
        phrase = _spoken_text(turn["text"])
        prior = recent_phrases.get(phrase)
        if prior is not None and row["simulated_at"] - prior < 75 and not row["terminal"]:
            exact_recent_repeats += 1
        recent_phrases[phrase] = row["simulated_at"]
    replies = [(row, turn) for row in transcript for turn in row["turns"][1:]]
    measured_replies = [(row, turn) for row, turn in replies if turn["audio_seconds"] is not None]
    budgeted_replies = [(row, turn) for row, turn in measured_replies if row["reply_budget_seconds"] is not None]
    return {"archive": Path(path).name, "events": checked_events, "malformed": malformed,
        "mode": "authored_script_simulation", "completion_model": "assumed_completion_except_drop_every",
        "audio_latency_measured": False,
        "clock_directions": {str(r): next(iter(steps)) if len(steps) == 1 else "mixed"
                             for r, steps in direction_steps.items()},
        "simulated_span_seconds": round(simulated - 1000, 3),
        "archived_verdicts": saved_used, "raw_reclassifications": checked_events - saved_used,
        "engine_replay_events": checked_events,
        "calls": len(transcript), "scenes": dict(Counter(row["scene"] for row in transcript)),
        "named_calls": sum(row["named"] for row in transcript),
        "unnamed_calls": sum(not row["named"] for row in transcript),
        "single_turn_calls": sum(len(row["turns"]) == 1 for row in transcript),
        "intents": dict(Counter(meta["intent"] for row in transcript if row["completed"]
                                 for meta in row["content"] if meta["intent"] != "call")),
        "topics": dict(Counter(meta["topic"] for row in transcript if row["completed"]
                                for meta in row["content"] if meta["intent"] != "call")),
        "optional_replies": sum(len(row["turns"]) > 1 for row in transcript),
        "unique_completed_phrases": len(phrases),
        "exact_phrase_reuses": sum(max(0, amount - 1) for amount in phrases.values()),
        "exact_phrase_repeats_75s_nonterminal": exact_recent_repeats,
        "measured_reply_audio": len(measured_replies),
        "unmeasured_reply_audio": len(replies) - len(measured_replies),
        "missing_pack_turns": sum(turn["audio_timing_source"] == "missing_pack" for row in transcript for turn in row["turns"]),
        "reply_budget_checked": len(budgeted_replies),
        "reply_audio_over_budget": sum(turn["audio_seconds"] > float(row["reply_budget_seconds"]) for row, turn in budgeted_replies),
        "pacing_reasons": dict(Counter(row["pacing_reason"] for row in transcript)),
        "delivery_modes": dict(Counter(row["delivery"] for row in transcript)),
        "long_optional_replies": sum(len(turn["text"]) > 45 for row in transcript for turn in row["turns"][1:]),
        "repeated_optional_topics_75s": sum(len(row["repeated_topics"]) for row in transcript
                                            if row["completed"] and not row["terminal"]),
        "terminal_topic_repeats_75s": sum(len(row["repeated_topics"]) for row in transcript
                                           if row["completed"] and row["terminal"]),
        "families": dict(Counter(row["family"] for row in transcript)),
        "roles": dict(Counter(turn["role"] for row in transcript for turn in row["turns"])),
        "profanity": {word: len(re.findall(word, text)) for word in ("샤갈", "존나", "미쳤", "돌았", "개같", "좆", "염병")},
        "invalid_callbacks": sum(not row["valid_callback"] for row in transcript),
        "invalid_subjects": sum(not row["valid_subject"] for row in transcript), "transcript": transcript}
