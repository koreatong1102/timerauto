# Logic + Release Audit Hotfix

점검 기준: `timer_best_commentary_duo_test_flow_hotfix_source.zip` 기준으로 실제 자동 진행 로직과 배포 스크립트를 같이 확인했다.

## 확인한 자동해설 흐름

- 실제 fight 진행 중 safe caster line에는 `commentary_tts_followup_text`가 붙어서 캐스터 → 해설자 듀오 후속 멘트가 예약된다.
- 위험 문구, 다운, 스턴, TKO/KO, 회복/체력 위험 문맥은 듀오 유머 후보에서 제외된다.
- 다운은 1다운/2다운/3다운 상태 머신으로 분기되고, 재개/결과/브레이크 상태 진입 시 `commentary_tts_stop_roles`로 남은 예약 멘트를 취소한다.
- 브레이크 요약은 남은 쉬는 시간 예산 안에서 문장을 고르고, 라운드 시작 시 analyst 요약을 중단한다.

## 이번에 추가로 고친 부분

1. 요약 주어 보강
   - 라운드 요약에서 다운/스턴/우세/접전/코너 조언 문장에 선수 호출명을 더 넣었다.
   - 경기 종료 요약은 기존처럼 승자/점수/스코어카드에 주어를 유지한다.

2. 실시간 해설 주어 보강
   - 체력/데미지 위험, 약점 부위 쌓임 등 누가 위험한지 헷갈릴 수 있는 문장에 짧은 선수 호출명을 붙였다.

3. TTS 호출명 fallback 강화
   - 등록 닉네임이 있으면 등록 닉네임을 우선 사용한다.
   - 미등록 긴 영문 ID는 전체를 읽지 않고 짧은 호출명/별칭으로 줄인다.
   - 주요 RFC 선수 ID 별칭을 추가했다: Daniel, HISANAGA, NERY, DORAYM, MONSAN, KOT99K, GLASSBONES, FINDYOURWAYHOME 등.

4. 배포용 SpectatorLog 경로 자동탐색
   - 새 PC에서 config가 없어도 `%USERPROFILE%\\Documents\\ThrillOfTheFight2\\SpectatorLog`와 OneDrive Documents 경로를 먼저 찾는다.
   - 찾지 못하면 기존처럼 exe 옆 `ThrillOfTheFight2\\SpectatorLog`를 fallback으로 사용한다.

5. build_release 안전 점검
   - 빌드 후 필수 파일 누락 시 실패하도록 검사한다.
   - `-IncludeUserConfig` 사용 시 config 안에 SWa PC 같은 절대경로가 있으면 경고를 띄운다.

## 배포 판단

- 기본 `build_release.ps1`는 config/profile을 포함하지 않으므로 다른 사용자에게 SWa의 로컬 경로가 같이 나가지 않는다.
- 사용자는 첫 실행 후 설정을 저장하면 자기 PC 기준 config가 생성된다.
- SpectatorLog 경로는 새 자동탐색 로직으로 Documents 쪽 일반 경로를 우선 찾는다.
- Linux 환경에서는 Windows exe를 실제 실행할 수 없어, exe 런타임은 정적 점검/문법검증/로직 시뮬레이션까지 확인했다.
