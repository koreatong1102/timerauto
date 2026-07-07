# Stage45 Portrait Stun Flash Fix

## 문제
- Stage44에서 작은 clone 초상화는 제거됐지만, `impact` 이벤트의 `effectKind: "stun"` 값을 JS가 읽지 않았다.
- 그래서 설정 테스트/실전 impact 이벤트가 stun이어도 브라우저에서는 `kind === "impact"`만 보고 일반 heavy hit처럼 처리했다.
- clone 제거 후에는 원본 초상화 자체의 flash가 너무 약해서 스턴 플래시가 거의 안 보였다.

## 수정
- 브라우저 이벤트 분류에서 `effectKind`, `effect_kind`, `fxKind`, `fx_kind`를 함께 읽도록 수정.
- `effectKind: "stun"`이면 `portrait(side, 'stun', ...)`이 확실히 실행되게 수정.
- 원본 초상화 img 자체에 적용되는 Stage45 전용 hit/heavy/stun/ko keyframes 추가.
- clone 이미지와 portraitFxLayer는 계속 비활성화해서 작은 초상화/옆 이펙트가 다시 나오지 않게 유지.

## 검증
- `python -m py_compile timerauto.py browser_overlay.py config_model.py spectator_log_watcher.py`
- extracted overlay JS `node --check` 통과.
