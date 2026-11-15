"""Explicit game stoppages, kept separate from the number of knockdowns."""
import re


def official_stoppage_kind(damage_type):
    token=re.sub(r'[^a-z0-9]','',str(damage_type or '').lower())
    if token=='tko' or 'technicalknockout' in token:return 'tko'
    if token=='ko' or 'knockout' in token:return 'ko'
    return ''


def stoppage_loser_sides(data):
    result=set()
    direct=dict(data.get('spectator_stoppage') or {})
    if str(direct.get('method') or '').upper() in ('KO','TKO','KO/TKO'):
        side=direct.get('loser')
        if side in ('blue','red'):result.add(side)
    for event in data.get('spectator_effect_events') or []:
        if event.get('kind') in ('ko','tko') and event.get('side') in ('blue','red'):
            result.add(event['side'])
    reports=list(data.get('spectator_round_reports') or [])
    if isinstance(data.get('spectator_round_report'),dict):reports.append(data['spectator_round_report'])
    for report in reports:
        if not isinstance(report,dict):continue
        method=str(report.get('resultMethod') or (report.get('matchResult') or {}).get('method') or '').upper()
        winner=report.get('winner') or (report.get('matchResult') or {}).get('winner')
        if method in ('KO','TKO','KO/TKO') and winner in ('blue','red'):
            result.add('red' if winner=='blue' else 'blue')
    return result


def update_life_flags(data,eliminated=(),round_key=None):
    """Presentation only; never changes raw knockdown counts or report data."""
    eliminated=set(eliminated)
    if any(data.get(key) for key in ('spectator_match_clear','spectator_match_stats_reset','vs_intro_event')):
        eliminated.clear();round_key=None
    if 'round_current' in data:
        try:current=int(data['round_current'])
        except (ValueError,TypeError):current=None
        if current is not None:
            if round_key is not None and current!=round_key:eliminated.clear()
            round_key=current
    eliminated.update(stoppage_loser_sides(data))
    return eliminated,round_key
