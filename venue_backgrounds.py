"""Official venue IDs and the bundled background of the browser VS intro."""
from __future__ import annotations

import json

VENUES = {
    0: ("HOME GYM", "assets/images/venues/home_gym.png"),
    1: ("NIGHT GYM", "assets/images/venues/night_gym.jpg"),
    2: ("HOTEL", "assets/images/venues/hotel.png"),
    3: ("MEMORIAL HALL", "assets/images/venues/memorial_hall.png"),
    4: ("PHILLY PARKWAY", "assets/images/venues/philly_parkway.jpg"),
}


def normalize_venue_id(value):
    # In particular, venue 0 is valid, not a missing/falsy value.
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if text not in {str(key) for key in VENUES}:
        return None
    return int(text)


def venue_from_update(data):
    """Return (explicitly supplied, normalized ID); absent updates keep state."""
    for key in ("spectator_venue_id", "venue_id", "venueId"):
        if key in data:
            return True, normalize_venue_id(data[key])
    for key in ("vs_intro_event", "spectator_lobby_status", "spectator_lobby_overlay"):
        payload = data.get(key)
        if isinstance(payload, dict) and "venueId" in payload:
            return True, normalize_venue_id(payload["venueId"])
    return False, None


def add_venue_background_layout(html):
    names = json.dumps({str(key): value[0] for key, value in VENUES.items()})
    script = r"""
const vsVenueNames=__VENUE_NAMES__;
function syncVsVenueBackground(s){
  s=s||{};
  const v=q('vs'),bg=q('vsBg');if(!v||!bg)return;
  const id=s.venueId===null||s.venueId===undefined?'':String(s.venueId);
  const known=Object.prototype.hasOwnProperty.call(vsVenueNames,id);
  const rev=known?Number(s['venue'+id+'Rev']||0):Number(s.vsbgRev||0);
  const src=rev>0?('/asset/'+(known?'venue'+id:'vsbg')+'?rev='+rev):'';
  if(src){
    if(bg.dataset.venueSrc!==src){
      bg.dataset.venueSrc=src;
      bg.dataset.venueFailed='';
      bg.onerror=()=>{if(bg.dataset.venueSrc===src){bg.dataset.venueFailed=src;bg.style.opacity='0';v.classList.remove('hasBg')}};
      bg.src=src;
    }
    const visible=bg.dataset.venueFailed!==src;
    bg.style.opacity=visible?String(Math.max(0,Math.min(1,s.vsBgOpacity??1))):'0';
    v.classList.toggle('hasBg',visible);
  }else{
    bg.dataset.venueSrc='';bg.removeAttribute('src');bg.style.opacity='0';v.classList.remove('hasBg');
  }
  bg.alt=known?vsVenueNames[id]:'';
  setText('vsStage',known?vsVenueNames[id]:(s.arenaName||'DEFAULT'));
}
""".replace("__VENUE_NAMES__", names)
    html = html.replace("function showVs(s){", script + "\nfunction showVs(s){", 1)
    # Reuse the existing first child/background and preserve all portrait timing.
    start = html.index("function showVs(s){")
    end = html.index("function syncVsImages(s){", start)
    show = html[start:end]
    bg_start = show.index("if((s.vsbgRev||0)>0)")
    bg_end = show.index("if(s.blueHasImage===true)", bg_start)
    show = show[:bg_start] + "syncVsVenueBackground(s);" + show[bg_end:]
    show = show.replace("setText('vsStage',s.arenaName||'DEFAULT');", "")
    html = html[:start] + show + html[end:]
    # Existing state renders also preload the selected map while still in lobby,
    # and update a late venue without restarting the VS animation or waiting.
    return html.replace("syncPlayerIdentities(s);syncVsImages(s);",
                        "syncVsVenueBackground(s);syncPlayerIdentities(s);syncVsImages(s);")
