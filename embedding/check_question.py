"""평가 문항 사전 검증: 질문을 던져 검색 결과를 눈으로 확인
사용: python check_question.py "보험료 카드 포인트 적립률은?"
     python check_question.py "면책기간이란?" --terms"""
import sys
from rag_config import search, search_terms

q = sys.argv[1]
use_terms = "--terms" in sys.argv
hits = search_terms(q, k=5) if use_terms else search(q, k=5)

print(f"질문: {q}  ({'terms' if use_terms else 'policy'})")
for h in hits:
    print(f"  [{h['insurer']}|{h['generation']}] {h['citation'][:40]}")
    print(f"    {h['text'][:100]!r}")