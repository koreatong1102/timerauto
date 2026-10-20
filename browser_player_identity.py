"""Shared two-line fighter identity for the browser HUD and match-intro VS."""

PLAYER_ID_CSS = r"""
.nicknameText{display:block;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  box-sizing:border-box;line-height:1.3;padding:1px 2px}
.playerGameId{display:none;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:#cbd5e1;-webkit-text-fill-color:#cbd5e1;font:600 12.5px/1.15 Consolas,'Malgun Gothic',monospace;
  letter-spacing:.25px;text-shadow:0 1px 2px #000;pointer-events:none}
.name{height:auto!important;min-height:28px!important;padding-top:2px!important;padding-bottom:2px!important;box-sizing:border-box!important}
.name.hasPlayerId{min-height:48px!important;padding-top:3px!important;padding-bottom:3px!important}
.name .nicknameText{line-height:1.3}
.name .playerGameId{margin-top:4px}
.vsName.hasPlayerId{top:650px!important;height:auto!important;line-height:1!important}
.vsName .nicknameText{line-height:1.25;padding:.04em .12em}
.vsName .playerGameId{margin-top:12px;font-size:26px;line-height:1.15;font-style:normal;letter-spacing:1px}
"""

PLAYER_ID_JS = r"""
function syncPlayerIdentities(s){
  s=s||{};
  for(const side of ['blue','red']){
    const cap=side==='blue'?'Blue':'Red',id=String(s[side+'PlayerId']||'').trim();
    for(const prefix of [side,'vs'+cap]){
      const host=q(prefix==='blue'||prefix==='red'?prefix+'Name':prefix);
      const label=q(prefix+'GameId');
      if(!host||!label)continue;
      const shown=s.showPlayerIds!==false&&id.length>0;
      if(label.textContent!==id)label.textContent=id;
      label.title=id;
      label.style.display=shown?'block':'none';
      host.classList.toggle('hasPlayerId',shown);
    }
  }
}
"""


def add_player_identity_layout(html: str) -> str:
    """Keep existing name containers/styles and add text-only ID children.

    Existing render calls update nickname children, never the whole container,
    so normal state updates do not destroy/recreate the ID nodes every frame.
    """
    for side, fallback in (("blue", "BLUE"), ("red", "RED")):
        cap = side.title()
        for host, css, nickname, identity in (
            (side + "Name", "name", side + "Nickname", side + "GameId"),
            ("vs" + cap, "vsName vs" + cap, "vs" + cap + "Nickname", "vs" + cap + "GameId"),
        ):
            html = html.replace(
                f'<div id="{host}" class="{css}">{fallback}</div>',
                f'<div id="{host}" class="{css}"><span id="{nickname}" class="nicknameText">{fallback}</span>'
                f'<span id="{identity}" class="playerGameId"></span></div>',
                1,
            )
            html = html.replace(
                f"setText('{host}',s.{side}Name||'{fallback}')",
                f"setText('{nickname}',s.{side}Name||'{fallback}')",
            )
    html = html.replace("</style>", PLAYER_ID_CSS + "\n</style>", 1)
    html = html.replace("function showVs(s){", PLAYER_ID_JS + "\nfunction showVs(s){", 1)
    return html.replace("syncVsImages(s);", "syncPlayerIdentities(s);syncVsImages(s);")
