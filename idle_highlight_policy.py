"""Idle-video eligibility only; never stops KD, POTM, reports or the match."""
import time


class IdleHighlightPolicy:
    def __init__(self):
        self.last_end = None
        self.terminal = False
        self.occupied = False

    def update(self, cfg, update, *, now=None):
        now = time.monotonic() if now is None else now
        state = str(update.get("spectator_round_state") or "").lower()
        if state in ("intro", "fight", "break", "knockdown", "foul") or update.get("vs_intro_event"):
            self.terminal = False
        if state in ("results", "end", "knockout", "disqualified", "cancel") or update.get("spectator_match_terminal"):
            if not self.terminal:
                self.last_end = now
            self.terminal = True
        lobby = update.get("spectator_lobby_status")
        if isinstance(lobby, dict):
            self.occupied = any(bool(s.get("occupied")) and not any(t in str(s.get("type") or "").lower()
                for t in ("spectator", "observer", "camera", "host")) for s in lobby.get("slots", []) if isinstance(s, dict))
        wait = max(0, min(3600, int(getattr(cfg, "idle_highlight_after_match_sec", 300))))
        remaining = max(0., wait - (now - self.last_end)) if self.last_end is not None else 0.
        # Publish only eligibility changes, not a ticking countdown: the latter
        # would resend the entire overlay state even when playback is unchanged.
        return {"idleHighlightPolicyBlocked": bool(
                    (getattr(cfg, "idle_highlight_stop_on_player", False) and self.occupied) or
                    (getattr(cfg, "idle_highlight_delay_enabled", False) and remaining > 0))}
