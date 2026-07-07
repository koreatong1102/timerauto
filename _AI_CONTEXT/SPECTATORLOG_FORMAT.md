# SpectatorLog Format Notes

## damage_events v2
현재 SpectatorLogs2 기준 tab-separated 컬럼:
```text
round_time final_damage corner hand screen_x screen_y world_x world_y world_z punch_type damage_type weak_point
```
`hand`가 추가되어 12컬럼이다. 구버전 11컬럼도 방어해야 한다.

## 추가/중요 파일
- `match/punches_thrown.txt`: `round_time corner hand punch_type`
- `match/scores.csv`: 공식 라운드 점수
- `match/winner.txt`: 최종 승자
- `match/round_total.txt`: 총 라운드
- `match/camera_input.txt`: 관전 카메라 입력/머리 숨김 플래그
- `blue|red/accessibility.txt`, `cosmetics.txt`: 선수 설정/외형 정보

## 현재 감지 결과
```json
{
  "root_exists": false,
  "note": "static source package context"
}
```
