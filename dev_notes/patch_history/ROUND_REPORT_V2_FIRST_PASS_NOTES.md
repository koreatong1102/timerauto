# ROUND REPORT V2 FIRST PASS

## 변경 범위
- 라운드 리포트 payload에 `roundTag`, `bestShot`, `decisiveMoment` 추가.
- TKO > 다운 > 스턴 > 빅샷 순으로 결정 장면을 선택.
- 최고 데미지 한 방은 별도로 `bestShot`에 보관.
- 브라우저 오버레이 라운드 리포트 카드 상단에 라운드 태그와 결정장면/최고 한방 섹션 추가.

## 표시 예시
- `TKO ROUND`
- `DECISIVE TKO`
- `홍코너 뒷손 훅 → 관자놀이 / 청코너 피격`
- `85 DMG`

## 의도적으로 건드리지 않은 것
- 실시간 해설/캐스터 TTS 구조.
- 기존 다운/KO/TKO 오버레이.
- 포트레이트 포함 리포트.
- 몸 히트맵/좌표 기반 히트마커.
- 장갑 좌표 기반 펀치 시도 추정.
