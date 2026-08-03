# Claude CLI — MinerU 48문서 구현 코드 검토

- 시각: 2026-08-03 21:20 KST
- 방식: Claude Code 2.1.196, 읽기 전용 정적 분석
- 판정: **패킷 생성·원격 실행 조건부 GO / 자동 게이트 확대 근거 NO-GO**

## 지적 요약

| 심각도 | 지적 | 반영 |
|---|---|---|
| P1 | 대표 페이지 랭크가 현재 `len(coords)`와 이전 `len(methods)`를 비교 | `coord_count`를 Anchor에 보존해 같은 튜플로 비교 |
| P1 | manifest 생략 시 이미지 SHA 검증이 꺼짐 | config에도 SHA 포함, SHA 없는 config는 manifest 없이는 하드 실패 |
| P1 | 구조 표 0개면 bbox rate `None`이 게이트 통과 | 표 1개 이상이고 bbox 100%일 때만 통과 |
| P1 | bbox 정규화 좌표계 무검증 | `[0,1]`, 길이 4, 양의 면적 검증 후 경계·보존 계산 |
| P2 | rowspan 금액 셀이 여러 행에서 후보 중복 | 의미상 다중 적용 가능성이 있어 삭제하지 않고 amount origin group과 재사용 수를 지표화 |
| P2 | 열 헤더 path가 없음 | 첫 값 행 이전의 같은 열 헤더 셀을 context에 포함 |
| P2 | `선택형IV` 정규식 대안 순서 오류 | `IV`를 `I{1,3}`보다 먼저 매칭 |
| P2 | 세대 경계 코드 이원화 | `config/generation_profiles.json`에서 로드 |
| P2 | runner 기본 limit 1이 전량 성공으로 오인 가능 | 기본 0(전량), expected/selected 기록, 부분 성공 상태 분리 |
| P2 | shadow 격리 테스트 범위가 좁음 | 경로 존재 assert, py/json/sql/yaml 설정·인덱스/DB 적재 루트 검사 |
| P2 | bbox float가 candidate ID를 흔듦 | 해시 입력 bbox만 소수 4자리 정규화, 실제 근거 bbox는 원본 보존 |

## 해석

P1 수정과 테스트 전에는 score의 자동 게이트를 확대 근거로 사용하지 않는다. 사람 결합 gold가 없는 상태의
`expansion_allowed=false`는 유지한다.

