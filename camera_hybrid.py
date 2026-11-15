"""Calibrated head-relative broadcast view, not eye tracking or HMD mirroring."""
import math


def view_mode(options):
    mode=options.get('view_mode')
    return mode if mode in ('opponent','raw','hybrid') else ('opponent' if options.get('look_opponent') else 'raw')


def needs_opponent(options):
    return view_mode(options) in ('opponent','hybrid')


def parse_pose(text):
    if not isinstance(text,str):raise ValueError('혼합 시점에 필요한 상대 머리 로그가 없습니다.')
    row=[float(v) for v in text.split()]
    if len(row)!=9 or not all(math.isfinite(v) for v in row):
        raise ValueError('머리 위치 파일이 완전하지 않습니다.')
    norm=math.sqrt(sum(v*v for v in row[5:]))
    if not .5<=norm<=1.5:raise ValueError('머리 회전값이 올바르지 않습니다.')
    return row[:5]+[v/norm for v in row[5:]]


def multiply(a,b):
    x,y,z,w=a;u,v,t,s=b
    return (w*u+x*s+y*t-z*v,w*v-x*t+y*s+z*u,w*t+x*v-y*u+z*s,w*s-x*u-y*v-z*t)


def upright(yaw,pitch):
    a,b=yaw/2,-pitch/2  # Positive elevation means look upward.
    return (math.cos(a)*math.sin(b),math.sin(a)*math.cos(b),
            -math.sin(a)*math.sin(b),math.cos(a)*math.cos(b))


def target_angles(source,target):
    dx,dy,dz=[target[i]-source[i] for i in (2,3,4)]
    if math.hypot(dx,dz)<.01:raise ValueError('상대와 카메라 위치가 겹칩니다.')
    return math.atan2(dx,dz),math.atan2(dy,math.hypot(dx,dz))


def wrap(angle):
    return (angle+math.pi)%(2*math.pi)-math.pi


def level_rotation(q):
    x,y,z,w=q
    fx,fy,fz=2*(x*z+w*y),2*(y*z-w*x),1-2*(x*x+y*y)
    return upright(math.atan2(fx,fz),math.atan2(fy,math.hypot(fx,fz)))


class HybridView:
    def __init__(self):self.correction=None

    def reset(self):self.correction=None

    def pose(self,source_text,target_text,player_pct=80,yaw=0,pitch=0):
        source,target=parse_pose(source_text),parse_pose(target_text)
        weight,yaw_offset,pitch_offset=map(float,(player_pct,yaw,pitch))
        if not all(math.isfinite(v) for v in (weight,yaw_offset,pitch_offset)) or not 0<=weight<=100 or abs(yaw_offset)>180 or abs(pitch_offset)>90:
            raise ValueError('혼합 시점 보정 범위를 벗어났습니다.')
        target_yaw,target_pitch=target_angles(source,target)
        raw=source[5:]
        if self.correction is None:
            # One reference pose: the operator must have the boxer facing the
            # opponent here. This cannot infer absolute headset gaze from a bone.
            inverse=(-raw[0],-raw[1],-raw[2],raw[3])
            self.correction=multiply(inverse,upright(target_yaw,target_pitch))
        x,y,z,w=multiply(raw,self.correction)
        fx,fy,fz=2*(x*z+w*y),2*(y*z-w*x),1-2*(x*x+y*y)
        head_yaw=math.atan2(fx,fz)
        head_pitch=math.atan2(fy,math.hypot(fx,fz))
        delta=wrap(target_yaw-head_yaw)
        # Fade assistance out during a deliberate turn, rather than snapping
        # a player's look-away back onto the opponent.
        assist=1-weight/100
        if weight>0:
            assist*=max(0,min(1,(math.radians(70)-abs(delta))/math.radians(40)))
        head_yaw+=assist*delta+math.radians(yaw_offset)
        head_pitch+=assist*(target_pitch-head_pitch)+math.radians(pitch_offset)
        head_pitch=max(math.radians(-60),min(math.radians(60),head_pitch))
        q=upright(head_yaw,head_pitch)  # Rebuild with world-up; no inherited roll.
        return ' '.join(str(v) for v in source[:5]+list(q))
