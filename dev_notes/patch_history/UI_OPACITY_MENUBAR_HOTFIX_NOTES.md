# UI opacity / menubar hotfix

- 상단 QML 메뉴바의 `투명도` 슬라이더를 브라우저 오버레이 배경이 아니라 프로그램 QML 창 전체 opacity로 분리했다.
- 새 설정값: `overlay_window_opacity`.
  - 1.0 = 불투명
  - 0.2 = 거의 투명
  - 0.0은 창을 다시 잡기 힘들어서 허용하지 않는다.
- 기존 `overlay_bg_opacity`는 오버레이 배경용 설정으로만 남겼다.
- 상단 메뉴바/최소화 버튼은 hover 여부와 관계없이 항상 보이게 했다.
- 최소화 버튼 클릭 시 `showControls=false`로 숨기던 동작을 제거했다.
