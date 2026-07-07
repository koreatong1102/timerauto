# Overlay Map

## Browser overlay 핵심
`browser_overlay.py` 안에 HTML/CSS/JS가 문자열로 포함되어 있다. OBS/PRISM 브라우저 소스는 이 서버 페이지를 본다.

## 대표 DOM/이벤트
- `blueImg`, `redImg`: 선수 초상화 이미지
- `bluePortraitFx`, `redPortraitFx`: 과거 초상화 FX 레이어. stage40 이후 clone/이미지 기반 수정이 들어감.
- `screenImpact`: 화면 피격 이펙트 노드 풀
- impact 이벤트: 피격 위치/데미지/side/hand를 받아 화면 폭발 및 초상화 반응 실행

## 초상화 FX 주의
원형 div를 초상화 옆에 띄우는 방식은 실패했다. 실제 초상화 이미지와 픽셀 정렬되는 방식이어야 한다. 크기, z-index, transform, object-fit, left/right/top 값을 실제 이미지에서 복사하는지 확인해야 한다.
