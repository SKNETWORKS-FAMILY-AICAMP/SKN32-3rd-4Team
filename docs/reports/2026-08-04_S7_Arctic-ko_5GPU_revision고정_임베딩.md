# S7 Arctic-ko 5GPU 리비전 고정 임베딩 결과

- 날짜: 2026-08-04
- 상태: **생성·병합·검증 완료 / shadow / serving 미연결**
- 대상: `s7_hybrid-table-v1`의 인용 가능 조항 내용
- 후보 fact 포함: **아니오**

## 결론

S7의 인용 가능 원문 집합을 기존 S6 Arctic-ko 청크와 정확 대조한 뒤, 모델 커밋을 고정해
5개 RunPod GPU에서 전량 재임베딩했다. 최종 산출물은 145,220행 × 1,024차원이며
누락·중복·비정상값 없이 병합됐다.

기존 산출물은 모델 리비전이 비어 있었지만, 이번 결과는 아래 커밋으로 고정했다.

```text
dragonkue/snowflake-arctic-embed-l-v2.0-ko
revision=55ec6e9358a56d56af759bc8372e970caf8c305f
```

## 입력 동등성

| 항목 | 값 |
|---|---:|
| S7 eligible 고유 내용 | 59,951 |
| 입력 청크 | 145,220 |
| S7 대비 누락 내용 | 0 |
| S7 대비 초과 내용 | 0 |
| 청크 키 중복 | 0 |
| candidate fact 포함 | false |

청크 파일 SHA-256:
`76b4fca3ec7a30e796620f86b9ef73c30cf0454a156a628f9dffb2c153b00db7`

## 5GPU 실측

| 샤드 | GPU | 행 | 배치 | 순수 추론 초 | 피크 VRAM |
|---|---|---:|---:|---:|---:|
| 00 | RTX 2000 Ada | 29,044 | 64 | 312.845 | 1,795.1 MB |
| 01 | RTX 2000 Ada | 29,044 | 64 | 303.748 | 1,795.1 MB |
| 02 | RTX 4000 Ada | 29,044 | 96 | 184.032 | 2,149.1 MB |
| 03 | RTX 4000 Ada | 29,044 | 96 | 184.611 | 2,149.1 MB |
| 04 | RTX 2000 Ada | 29,044 | 64 | 311.532 | 1,795.1 MB |

모델 다운로드·로딩을 포함한 벽시계 시간은 약 6분이었다. 5개 샤드는 모두 같은 모델,
리비전, 차원, 정규화, 패키지 계열을 기록했다.

## 최종 검증

| 검사 | 결과 |
|---|---:|
| 최종 shape | 145,220 × 1,024 |
| dtype | float16 |
| 정규화 | true |
| float32 norm 범위 | 0.9995117 ~ 1.0 |
| 누락/중복/global index 충돌 | 0 |
| vectors SHA-256 | `b73527a0e70646e4bb2127dd8870126e99377fc99f1e2af8e2c4e11c3fd7c134` |
| 관련 회귀 테스트 | 14/14 통과 |

기존 리비전 미기록 벡터와 행별 비교:

| 지표 | 값 |
|---|---:|
| cosine mean | 0.9999973 |
| cosine p01 | 0.9999756 |
| cosine min | 0.9980168 |
| float16 완전 동일 행 | 717 |

부동소수점·GPU 실행 차이는 있으나 검색 표현은 사실상 같은 결과다. 이번 재생성의 핵심 이득은
성능 변화가 아니라 **모델 리비전과 분산 실행 provenance를 고정한 재현성**이다.

## 산출물

- `data/external/s7_arctic_ko_revisioned/chunks.jsonl`
- `data/external/s7_arctic_ko_revisioned/vectors.npz`
- `data/external/s7_arctic_ko_revisioned/meta.json`
- `data/work/s7_arctic_embed5/manifest.json`
- `data/work/s7_arctic_embed5/shard-00..04.meta.json`

## 릴리스 판단

현재 상태는 의도적으로 `shadow`, `serving_eligible=false`다. S7 candidate fact는 포함하지 않았고,
`config/accepted_extraction.json`도 변경하지 않았다. 전처리 정합성 위반과 S7 승인 게이트를 먼저
해결한 뒤에만 serving 승격을 검토한다.
