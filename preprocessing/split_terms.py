# -*- coding: utf-8 -*-
"""chunks_final.jsonl → 본문/표(chunks_main.jsonl)와 용어(chunks_terms.jsonl)로 분리."""
import json

n_main = n_term = 0
with open('out/chunks_final.jsonl', encoding='utf-8') as fin, \
     open('out/chunks_main.jsonl', 'w', encoding='utf-8') as fmain, \
     open('out/chunks_terms.jsonl', 'w', encoding='utf-8') as fterm:
    for line in fin:
        c = json.loads(line)
        if c['content_type'] == 'term':
            fterm.write(line); n_term += 1
        else:
            fmain.write(line); n_main += 1

print(f'chunks_main.jsonl  = {n_main}청크 (본문+표)')
print(f'chunks_terms.jsonl = {n_term}청크 (용어)')