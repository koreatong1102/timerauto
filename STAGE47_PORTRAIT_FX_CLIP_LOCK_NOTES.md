# Stage47 Portrait FX Clip Lock

## 문제
- Stage46에서 브라우저 초상화 FX 레이어를 다시 켰지만 FX 박스 자체가 확대/스케일 애니메이션을 타면서 실제 초상화 영역 밖으로 커질 수 있었다.
- CSS에 `!important`가 붙어 있어 JS 정렬 함수가 계산한 실제 초상화 크기/위치가 브라우저에서 덮어써지지 않을 수 있었다.
- FX 레이어 자체가 `scale(1.08~1.20)`으로 애니메이션되어, 내부 요소를 클리핑해도 레이어 박스 전체가 초상화 밖으로 커질 수 있었다.
- 실제 초상화 이미지에도 피격 상태에서 큰 `drop-shadow`와 이동/확대가 들어가 있어 빛 번짐이 초상화 밖으로 보일 수 있었다.

## 수정
- `portraitFxLayer`를 현재 HUD의 실제 초상화 박스와 같은 `122x122`, `top:-24px`, `left/right:-10px` 기본값으로 맞추고, JS가 실행될 때는 실제 이미지 계산값으로 다시 고정하게 했다.
- FX 레이어 자체의 확대 애니메이션을 제거하고 opacity만 변화하게 바꿨다.
- flash/ring/core/slash/sparks는 레이어 내부에서만 움직이고, 부모 레이어의 `overflow:hidden + clip-path + contain:paint`로 강제 클리핑한다.
- `alignPortraitFxLayer()`가 CSS `!important`와 싸워도 이길 수 있게 `style.setProperty(..., 'important')` 방식으로 바꿨다.
- 피격 중 실제 초상화 이미지의 큰 `drop-shadow`/이동/확대 애니메이션을 잠그고, 내부 FX 레이어가 타격감을 담당하게 했다.

## 검증
- `python -m py_compile browser_overlay.py`
- 브라우저 오버레이 `<script>` 추출 후 `node --check` 통과.
