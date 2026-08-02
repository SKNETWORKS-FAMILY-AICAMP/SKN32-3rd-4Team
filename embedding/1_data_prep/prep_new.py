"""신규 2파일(chunks_main/terms) 통합 전처리: dedup + cid제거 + 512분할
출력: data\main_indexready.jsonl / data\terms_indexready.jsonl"""
import json
import hashlib
import re
from transformers import AutoTokenizer
from rag_config import EMBED_MODEL, MAX_TOKENS

tok = AutoTokenizer.from_pretrained(EMBED_MODEL)
CID = re.compile(r"\(cid:\d+\)")
PAGE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
CONTENT = re.compile(r"[가-힣A-Za-z]")


def ntok(t):
    return len(tok.encode(t, add_special_tokens=True))


def process(in_path, out_path):
    # 1패스: chunk_id 등장 횟수
    counts = {}
    with open(in_path, encoding="utf-8") as f:
        for line in f:
            cid = json.loads(line)["chunk_id"]
            counts[cid] = counts.get(cid, 0) + 1

    seen = {}
    stats = dict(kept=0, dup=0, renamed=0, cidrm=0, junk=0, split=0)
    with open(in_path, encoding="utf-8") as f, \
         open(out_path, "w", encoding="utf-8") as out:

        def emit(c):
            t = c["text"]
            if ntok("passage: " + t) <= 512:
                out.write(json.dumps(c, ensure_ascii=False) + "\n")
                return 0
            body = tok.encode(t, add_special_tokens=False)
            for i, s in enumerate(range(0, len(body), 460), 1):
                nc = dict(c)
                nc["chunk_id"] = f"{c['chunk_id']}-t{i}"
                nc["text"] = tok.decode(body[s:s + 460])
                out.write(json.dumps(nc, ensure_ascii=False) + "\n")
            return 1

        for line in f:
            c = json.loads(line)
            t = c["text"].strip()
            # 쓰레기 필터
            if PAGE.match(t) or len(CONTENT.findall(t)) < 2:
                stats["junk"] += 1
                continue
            cid_len = sum(len(m) for m in CID.findall(t))
            if cid_len > len(t) * 0.2:
                stats["cidrm"] += 1
                continue
            # dedup
            k = c["chunk_id"]
            if counts[k] > 1:
                h = hashlib.md5(c["text"].encode()).hexdigest()[:8]
                if k in seen and h in seen[k]:
                    stats["dup"] += 1
                    continue
                if k in seen:
                    c["chunk_id"] = f"{k}::{h}"
                    stats["renamed"] += 1
                seen.setdefault(k, set()).add(h)
            stats["kept"] += 1
            stats["split"] += emit(c)

    print(f"[{in_path}]")
    print(f"  유지 {stats['kept']} (그중 512분할 {stats['split']}) / "
          f"중복제거 {stats['dup']} / ID변경 {stats['renamed']} / "
          f"cid깨짐 {stats['cidrm']} / 쓰레기 {stats['junk']}")
    print(f"  -> {out_path}")


process(r"data\chunks_main.jsonl", r"data\main_indexready.jsonl")
process(r"data\chunks_terms.jsonl", r"data\terms_indexready.jsonl")
print("\n완료. 이 2개 파일이 색인 입력입니다.")