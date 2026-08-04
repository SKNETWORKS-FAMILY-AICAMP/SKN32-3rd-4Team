# shadow48 scorer 구형 manifest `documents` 누락

- 시각: 2026-08-03 21:05 KST
- 위치: `scripts/eval/score_ocr_shadow48.py:build_review_html`

## 재현

```powershell
python -m scripts.eval.score_ocr_shadow48 `
  --manifest data/eval/ocr_sota5/manifest.json `
  --results-root data/eval/ocr_sota5/remote_output/mineru_2_5_pro_2605 `
  --candidate-dir data/eval/ocr_sota5/selfpay_candidates ...
```

집중 테스트 6건은 통과했지만 검수 HTML 생성에서 `manifest["documents"]`를 직접 읽어
`KeyError: 'documents'`가 발생했다. SOTA5 구형 manifest는 `samples`만 보유한다.

## 영향

- 신규 shadow48 manifest에는 `documents`가 있어 본 평가 실행에는 영향이 없다.
- 그러나 계획에 포함한 기존 7쪽 회귀 검수 HTML 생성을 완료하지 못했다.
- 점수 JSON은 예외 직전에 쓰였지만 작업 완료 결과로 간주하지 않는다.

## 수정

`documents`가 없으면 `insurer+sha12`로 samples를 결정적으로 그룹화하는 호환 경로를 추가하고
같은 명령을 재실행한다.

