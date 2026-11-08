"""Bounded active-shot safety, separate from strict shot-entry composition.

Glove proximity and entry-speed estimates are not proof the rendered view is
unsafe. Judge published motion, persistent data loss and severe distance only.
All timing is monotonic and observation based, not a guarantee of comfort.
"""
import math


class ActiveViewSafety:
    def __init__(self):
        self.bad_since = {}
        self.previous = None
        self.metrics = {}

    def _held(self, key, bad, now, grace):
        if not bad:
            self.bad_since.pop(key, None)
            return False
        self.bad_since.setdefault(key, now)
        return now - self.bad_since[key] >= grace

    def evaluate(self, now, geometry_ok, reason, metrics, output):
        metrics = dict(metrics or {})
        self.metrics = metrics
        # Read/rewrite races are tolerated briefly; real data loss is not.
        partial = not geometry_ok and reason == 'partial_pose'
        stale = not geometry_ok and reason == 'head_log_stale'
        age = float(metrics.get('head_age', 0))
        if self._held('tracking_partial', partial, now, .65):
            return 'tracking_partial'
        if self._held('tracking_stale', stale and age >= 1.0, now, .15):
            return 'tracking_stale'

        distance = metrics.get('distance')
        if self._held('distance_close', distance is not None and distance < .35, now, .25):
            return 'distance_close'
        if self._held('distance_far', distance is not None and distance > 4.5, now, .7):
            return 'distance_far'

        speed = turn = 0.0
        try:
            pose = tuple(float(v) for v in output.replace('\\t', '\t').split()[:8])
            if len(pose) != 8 or not all(math.isfinite(v) for v in pose):
                raise ValueError('incomplete published pose')
            norm = math.sqrt(sum(v*v for v in pose[3:7]))
            if not .5 <= norm <= 1.5:
                raise ValueError('invalid published rotation')
            pose = pose[:3] + tuple(v/norm for v in pose[3:7])
            if self.previous:
                at, previous = self.previous
                if math.dist(pose[:3],previous[:3]) > 1.5:
                    self.metrics=dict(metrics,output_jump=round(math.dist(pose[:3],previous[:3]),3))
                    return 'tracking_jump'
                dt = now-at
                if 0 < dt <= .5:
                    speed = math.dist(pose[:3], previous[:3])/dt
                    dot = min(1.0, abs(sum(a*b for a,b in zip(pose[3:],previous[3:]))))
                    turn = math.degrees(2*math.acos(dot))/dt
            # Sampling a repeated pose must not shorten the next motion delta.
            if not self.previous or pose != self.previous[1]:
                self.previous = (now,pose)
            invalid = False
        except (AttributeError, TypeError, ValueError, OverflowError):
            invalid = True
        if self._held('tracking_output', invalid, now, .35):
            return 'tracking_output'
        # Hysteresis avoids resetting a sustained problem at a threshold edge.
        limit_speed, limit_turn = (3.5,180) if 'camera_motion' in self.bad_since else (5,260)
        self.metrics = dict(metrics, output_speed=round(speed,3), output_turn=round(turn,2))
        if self._held('camera_motion', speed > limit_speed or turn > limit_turn, now, .45):
            return 'camera_motion'
        known = {'view_ready','partial_pose','head_log_stale','too_close','too_far',
                 'rapid_motion','glove_obstruction'}
        unknown = not geometry_ok and (reason not in known or
                  (reason in ('too_close','too_far') and distance is None))
        if self._held('view_unknown', unknown, now, .65):
            return 'view_unknown'
        return ''
