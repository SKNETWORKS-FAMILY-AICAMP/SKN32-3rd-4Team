# s6 manifest sidecar 무결성 검증 누락

- 발견 시각: 2026-08-03 15:56 KST
- 심각도: P0 — 승인 기준선의 지문이 실제 파일과 다름
- 상태: **수정 완료** — 회귀 테스트 6개와 s6 1,367건 재검증 통과

## 1. 위치

- 생성: `scripts/extract/build_manifest.py`의 manifest/`.sha256` 쓰기 부분
- 검증: 같은 파일의 `--verify` 분기
- 산출물:
  - `data/manifests/preprocess/manifest_s6.json`
  - `data/manifests/preprocess/manifest_s6.sha256`

## 2. 재현

```powershell
$actual = (Get-FileHash -Algorithm SHA256 `
  data\manifests\preprocess\manifest_s6.json).Hash.ToLowerInvariant()
$recorded = (Get-Content -Raw -Encoding UTF8 `
  data\manifests\preprocess\manifest_s6.sha256).Trim().ToLowerInvariant()
"actual=$actual"
"recorded=$recorded"
"match=$($actual -eq $recorded)"

python -m scripts.extract.build_manifest --schema s6 --verify
```

## 3. 실측

```text
actual   = c39ffb1bec3ca16300fd0588106fd91b29ee398fc30585e79fd7b122eb6ebfcf
recorded = 060d0f21b7cd7a59cec4b96b8b517fd8be13c6e56f053a9b17d189c27bae5331
match    = False
CRLF 쌍  = 38,760
```

그런데 기존 `--verify`는 문서 1,367건·산출물 해시 어긋남 0으로 exit 0을 반환했다.
sidecar 자체를 읽거나 실제 manifest 파일의 바이트 해시와 대조하지 않기 때문이다.

## 4. 원인

코드는 `_canon()`이 만든 LF 문자열 `body.encode("utf-8")`를 먼저 해시한다. 그 뒤
`Path.write_text()`가 Windows 기본 newline 변환으로 실제 파일을 CRLF로 기록한다.
따라서 sidecar는 **쓰기 전 논리 문자열**의 해시이고, 실제 manifest 파일의 SHA-256이 아니다.

## 5. 위험

- sidecar만으로는 manifest 파일의 변조·전송 손상을 확인할 수 없다.
- `--verify`가 exit 0이므로 검증이 완전하다는 잘못된 신뢰를 준다.
- s6를 s7과 비교하거나 승인 릴리스를 동결할 때 기준선 파일 자체의 무결성이 증명되지 않는다.

## 6. 정정 계획

1. manifest를 명시적 LF로 쓴 뒤 **실제 파일을 다시 읽어** `sha256_file(out)`으로 sidecar를 만든다.
2. `--verify`가 sidecar 부재·형식 오류·실제 해시 불일치를 실패로 처리한다.
3. Windows 줄바꿈 환경에서도 실제 파일 해시와 sidecar가 같은 회귀 테스트를 추가한다.
4. 기존 s6 manifest는 내용은 바꾸지 않고 sidecar만 실제 파일 해시로 정정한다.

## 7. 수정·검증 결과

- manifest를 명시적 LF로 쓴 뒤 `sha256_file(out)`으로 실제 파일을 해시한다.
- `--verify`가 sidecar 부재·형식 오류·해시 불일치를 `bad`에 포함한다.
- 기존 sidecar를 실제 파일 해시 `c39ffb1b…`로 정정했다.
- `tests/test_preprocess_manifest.py`: sidecar 관련 회귀를 포함해 **6 passed**.
- 실제 명령: `python -m scripts.extract.build_manifest --schema s6 --verify`
  → 문서 1,367건, 어긋남 0, exit 0.

## 참조

- `RULE.md` §1.2, §4.0
- `CLAUDE.md` §0, §4
- `docs/plans/2026-08-03_1540_s6_우선검증과_레거시_격리_계획.md`
