"""Independent release check for the S7-backed chatbot path."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    accepted = json.loads((ROOT / "config" / "accepted_extraction.json").read_text(encoding="utf-8"))
    supplemental = json.loads((ROOT / accepted["supplemental_facts"]).read_text(encoding="utf-8"))
    facts_dir = Path(os.getenv("S7_FACT_ROOT", ROOT / "data" / "work" / "s7_1_approved_facts"))
    paths = [facts_dir / n for n in ("approved_facts.jsonl", "chunks.jsonl", "occurrences.jsonl")]
    if not all(p.exists() for p in paths):
        print("FAIL missing S7 artifacts: " + ", ".join(str(p) for p in paths if not p.exists()))
        return 1
    facts = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    approved = [f for f in facts if f.get("serving_eligible") and f.get("citation_eligible")]
    hashes = {f.get("content_hash") for f in approved}
    chunks = {json.loads(line).get("content_hash") for line in paths[1].read_text(encoding="utf-8").splitlines() if line.strip()}
    occurrences = [json.loads(line) for line in paths[2].read_text(encoding="utf-8").splitlines() if line.strip()]
    os.environ.setdefault("S7_FACT_ROOT", str(facts_dir))
    from app.adapters import file_glossary_source
    file_glossary_source._reset_for_tests()
    rows = [r for r in file_glossary_source._load() if r.kind == "s7_approved_fact"]
    served = len([o for o in occurrences if o.get("content_hash") in hashes and o.get("content_hash") in chunks])
    checks = {
        "release_accepted": supplemental.get("release_state") == "accepted",
        "release_serving": supplemental.get("serving_eligible") is True,
        "approved_facts": len(approved),
        "served_occurrences": served,
        "chatbot_s7_passages": len(rows),
        "s7_serving": file_glossary_source.meta().get("s7_serving") is True,
        "approved_count_matches": len(approved) == supplemental["approval"]["approved_facts"],
        "content_count_matches": len(chunks) == supplemental["materialized"]["contents"],
        "occurrence_count_matches": served == supplemental["materialized"]["occurrences"],
    }
    print(json.dumps({"release_id": accepted.get("release_id"), **checks}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
