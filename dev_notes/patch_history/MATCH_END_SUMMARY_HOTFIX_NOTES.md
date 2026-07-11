# MATCH END SUMMARY HOTFIX

범위: 경기 종료/결과 상태에서 최종 요약 TTS만 추가.

수정 파일:
- spectator_log_watcher.py

변경 내용:
- round_state가 results 또는 end로 전환될 때 최종 경기 요약을 1회 생성합니다.
- 기존 경기 종료 캐스터 멘트가 있으면 약 3.2초 뒤 해설자 후속 멘트로 재생합니다.
- damage_events에서 TKO/KO가 명확하면 승자와 승리 방식을 말합니다.
- TKO/KO가 없으면 공식 승자를 단정하지 않고, 다운/유효타/큰 타격/약점 누적 기준으로 경기 흐름을 요약합니다.
- 중복 방지를 위해 상태+매치업+damage_events 파일 시그니처 기준으로 1회만 말합니다.

로그 확인:
- SPECTATORLOG_MATCH_SUMMARY state=results text=...
- COMMENTARY_TTS_FOLLOWUP text=...
