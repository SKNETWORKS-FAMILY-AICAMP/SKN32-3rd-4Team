"""Recover high-confidence disability-classification payment-rate candidates.

The S5 coordinate extractor intentionally rejected many prose-shaped two-column
layouts.  Disability classification appendices are a special case: a numbered
classification list and a same-length payment-rate vector provide a strong
domain invariant.  This command scans those rejected tables but only emits
quarantined candidate facts when all structural checks pass.

No emitted fact is serving- or citation-eligible until human approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data" / "extracted"
DEFAULT_OUTPUT = ROOT / "data" / "candidates" / "s7_disability_rates"

ITEM_MARK = re.compile(r"(?<!\d)(\d{1,2})\)\s*")
RATE_TOKEN = re.compile(r"(?<![0-9A-Za-z가-힣])(?:100|[1-9]\d?)(?![0-9A-Za-z가-힣])")
HEADER_CLASS = re.compile(r"장해\s*의?\s*분류")
HEADER_RATE = re.compile(r"지급\s*률")
SECTION_BREAK = re.compile(r"(?:^|\s)[나-하]\s*[.．]\s*(?:장해판정|판정기준)")


def _s5_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.json") if path.parent.name.startswith("s5_"))


def _table_text(table: dict) -> str:
    return " ".join(
        str(value)
        for record in table.get("records") or []
        for value in (record.get("cols") or {}).values()
    )


def _ordered_cells(record: dict) -> list[str]:
    cols = record.get("cols") or {}

    def key(item: tuple[str, object]) -> tuple[int, str]:
        raw = str(item[0])
        return (int(raw), raw) if raw.isdigit() else (10_000, raw)

    return [str(value or "") for _, value in sorted(cols.items(), key=key)]


def _split_items(text: str) -> tuple[list[int], list[str]]:
    cut = SECTION_BREAK.search(text)
    if cut:
        text = text[: cut.start()]
    matches = list(ITEM_MARK.finditer(text))
    if not matches:
        return [], []
    ordinals: list[int] = []
    descriptions: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        desc = " ".join(text[match.end() : end].split()).strip(" ;,·")
        ordinals.append(int(match.group(1)))
        descriptions.append(desc)
    return ordinals, descriptions


def _candidate_from_table(doc: dict, page: dict, table: dict) -> dict | None:
    records = table.get("records") or []
    if not records:
        return None
    blob = _table_text(table)
    if not (HEADER_CLASS.search(blob) and HEADER_RATE.search(blob)):
        return None

    header_index = None
    for index, record in enumerate(records):
        cells = _ordered_cells(record)
        if HEADER_CLASS.search(" ".join(cells)) and HEADER_RATE.search(" ".join(cells)):
            header_index = index
            break
    if header_index is None:
        return None

    left_parts: list[str] = []
    right_parts: list[str] = []
    for record in records[header_index + 1 :]:
        cells = _ordered_cells(record)
        if len(cells) < 2:
            continue
        if SECTION_BREAK.search(cells[0]):
            break
        left_parts.append(cells[0])
        right_parts.append(" ".join(cells[1:]))

    left = " ".join(left_parts)
    right = " ".join(right_parts)
    ordinals, descriptions = _split_items(left)
    rates = [int(token) for token in RATE_TOKEN.findall(right)]
    expected = list(range(1, len(ordinals) + 1))
    checks = {
        "header_pair": True,
        "at_least_two_items": len(ordinals) >= 2,
        "sequential_ordinals": ordinals == expected,
        "nonempty_descriptions": bool(descriptions) and all(descriptions),
        "item_rate_count_equal": len(ordinals) == len(rates),
        "rate_range_1_100": bool(rates) and all(1 <= rate <= 100 for rate in rates),
    }
    if not all(checks.values()):
        return {
            "accepted_by_invariant": False,
            "checks": checks,
            "item_count": len(ordinals),
            "rate_count": len(rates),
        }

    source = doc.get("source") or {}
    sha256 = str(source.get("sha256") or Path(str(source.get("url") or "")).stem)
    facts = [
        {
            "fact_type": "disability_payment_rate",
            "ordinal": ordinal,
            "classification": description,
            "payment_rate_percent": rate,
            "serving_eligible": False,
            "citation_eligible": False,
            "approval_status": "candidate",
        }
        for ordinal, description, rate in zip(ordinals, descriptions, rates)
    ]
    return {
        "accepted_by_invariant": True,
        "candidate_id": hashlib.sha256(
            f"{sha256}:{page.get('page')}:{table.get('table_id')}".encode("utf-8")
        ).hexdigest()[:24],
        "source_sha256": sha256,
        "source_sha12": sha256[:12],
        "insurer": source.get("insurer"),
        "product_name": source.get("product_name"),
        "page": page.get("page"),
        "table_id": table.get("table_id"),
        "method": table.get("method"),
        "original_is_table": table.get("is_table"),
        "original_reject_why": table.get("reject_why") or [],
        "checks": checks,
        "facts": facts,
    }


def scan(files: list[Path], shard_index: int, shard_count: int) -> tuple[list[dict], dict]:
    selected = files[shard_index::shard_count]
    candidates: list[dict] = []
    stats: Counter = Counter()
    for path in selected:
        stats["documents_scanned"] += 1
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stats["document_read_errors"] += 1
            continue
        for page in doc.get("pages") or []:
            stats["pages_scanned"] += 1
            for table in page.get("tables_coords") or []:
                stats["coordinate_tables_scanned"] += 1
                blob = _table_text(table)
                if not (HEADER_CLASS.search(blob) and HEADER_RATE.search(blob)):
                    continue
                stats["header_pair_tables"] += 1
                result = _candidate_from_table(doc, page, table)
                if not result:
                    continue
                if result.get("accepted_by_invariant"):
                    candidates.append(result)
                    stats["candidate_tables"] += 1
                    stats["candidate_facts"] += len(result["facts"])
                    if table.get("is_table") is False:
                        stats["recovered_from_rejected_tables"] += 1
                else:
                    stats["invariant_rejections"] += 1
                    for name, passed in result["checks"].items():
                        if not passed:
                            stats[f"rejected_{name}"] += 1
    return candidates, dict(sorted(stats.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("require 0 <= shard-index < shard-count")

    files = _s5_files(args.input)
    candidates, stats = scan(files, args.shard_index, args.shard_count)
    args.output.mkdir(parents=True, exist_ok=True)
    suffix = f"shard{args.shard_index:02d}-of-{args.shard_count:02d}"
    jsonl_path = args.output / f"candidates_{suffix}.jsonl"
    summary_path = args.output / f"summary_{suffix}.json"
    with jsonl_path.open("w", encoding="utf-8") as stream:
        for row in candidates:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "schema_version": "s7-disability-rate-candidate-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(args.input),
        "source_files_total": len(files),
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "gate": "header pair + sequential numbered items + nonempty descriptions + equal rate vector + 1..100",
        "release_policy": "candidate_only; serving/citation blocked until human approval",
        "stats": stats,
        "candidate_jsonl": str(jsonl_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
