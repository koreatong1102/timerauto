"""Fight-time camera coverage budget. No I/O, game input or combat verdicts."""
from collections import deque


class ShotBudget:
    def __init__(self, target_pct=18, idle_sec=12):
        self.target=max(5,min(35,float(target_pct)))/100
        self.idle_sec=max(6,min(60,float(idle_sec)))
        self.fight=0.0
        self.last_at=None
        self.live=False
        self.quiet_since=0.0
        self.opened=None
        self.intervals=deque(maxlen=64)
        self.serial=0

    def observe(self, now, live):
        if self.last_at is not None and live and self.live:
            # Do not count long worker suspensions or a pause as viewed fight.
            self.fight+=max(0,min(1,now-self.last_at))
        if live and not self.live:self.quiet_since=self.fight
        self.last_at,self.live=now,live
        while self.intervals and self.intervals[0][1]<self.fight-60:
            self.intervals.popleft()

    @property
    def quiet(self):
        return max(0,self.fight-self.quiet_since)

    def used_seconds(self):
        start=max(0,self.fight-60)
        total=sum(max(0,b-max(a,start)) for a,b in self.intervals)
        if self.opened is not None:total+=max(0,self.fight-max(start,self.opened))
        return total

    def allows(self, duration):
        # A small startup denominator prevents a first short shot from looking
        # like 100% coverage, without permitting an initial barrage of cuts.
        denominator=max(30,min(60,self.fight))
        return self.opened is None and (self.used_seconds()+duration)/denominator<=self.target+.03

    def support_ready(self):
        return self.quiet>=self.idle_sec/2

    def scenic_ready(self):
        return self.quiet>=self.idle_sec

    def relaxation(self):
        return min(8,max(0,self.quiet-self.idle_sec)*2)

    def started(self):
        self.opened=self.fight

    def ended(self):
        if self.opened is not None:
            self.intervals.append((self.opened,self.fight))
        self.opened=None
        self.quiet_since=self.fight
        self.serial+=1

    def snapshot(self):
        return {'fight_sec':round(self.fight,2),'quiet_sec':round(self.quiet,2),
                'coverage_pct':round(100*self.used_seconds()/max(30,min(60,self.fight)),1),
                'target_pct':round(100*self.target,1)}
