"""GPU 박스에서 다시 잰 **탐침 값만** 로컬 결과에 합친다.

★왜 별도 스크립트인가 — 덮어쓰면 멀쩡한 측정을 날린다.

    「벡터무변화」 계산이 틀려(§5-10) 21건을 다시 재야 했는데,
    순위 지표(MRR·R@k·`ranks`)는 **유효하다.** 통째로 갈아 끼우면
    짝비교에 쓰는 `ranks` 가 사라져 §3-1 을 다시 못 만든다.
    그래서 **탐침 관련 키만** 골라 옮긴다.

★조건이 다르면 옮기지 않는다.

    재측정을 fp32 로 하거나 다른 GPU 에서 하면 옛 값과 비교할 수 없다.
    `dtype` 이 어긋나면 **거부하고 이유를 말한다** — 조용히 섞으면
    표에 든 숫자가 무엇으로 잰 것인지 아무도 모르게 된다.

    4bit 4건은 원래 RunPod(RTX 2000 Ada)에서 쟀는데 그 기계는 반납됐다.
    랩 박스(RTX 4070 SUPER)로 다시 재므로 **GPU 가 다르다.**
    정밀도는 같으므로 옮기되, `probes_device` 로 드러나게 둔다.

쓰는 법:
    python -m scripts.eval.merge_probe_remeasure <내려받은_폴더>
    python -m scripts.eval.merge_probe_remeasure <폴더> --allow-dtype-mismatch
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_OUT = _ROOT / "data" / "eval" / "embed_bench_results"

#: 옮길 키. ★이 목록에 없는 것은 건드리지 않는다.
_PROBE_KEYS = (
    "proviso_delta_mean", "proviso_delta_min", "proviso_blind_count",
    "proviso_probes", "probe_norm_min", "probe_norm_max", "blind_eps",
)


def merge(src_dir: pathlib.Path, *, allow_mismatch: bool = False) -> int:
    if not src_dir.is_dir():
        print(f"폴더가 없습니다: {src_dir}")
        return 1
    moved = skipped = missing = 0
    for src in sorted(src_dir.glob("*.json")):
        new = json.loads(src.read_text(encoding="utf-8"))
        dst = _OUT / src.name
        if not dst.exists():
            #: ★조용히 새로 만들지 않는다. 이름이 어긋난 것일 수 있다.
            print(f"  ? 로컬에 대응 파일이 없습니다 — 건너뜀: {src.name}")
            missing += 1
            continue
        old = json.loads(dst.read_text(encoding="utf-8"))
        if "blind_eps" not in new:
            print(f"  ! 옛 공식으로 잰 것입니다 — 건너뜀: {src.name}")
            skipped += 1
            continue
        #: 재측정 쪽의 실제 정밀도. `dtype` 은 병합 전이면 새 파일의 것이다.
        got = new.get("probes_dtype") or new.get("dtype")
        want = old.get("dtype")
        if got != want and not allow_mismatch:
            print(f"  ★정밀도가 다릅니다({want} → {got}) — 건너뜀: {src.name}")
            print("    같은 조건으로 다시 재거나 --allow-dtype-mismatch 를 주세요.")
            skipped += 1
            continue
        before = old.get("proviso_blind_count")
        old.update({k: new[k] for k in _PROBE_KEYS if k in new})
        old["probes_remeasured"] = True
        old["probes_device"] = new.get("probes_device") or new.get("device")
        old["probes_dtype"] = got
        old["probes_dtype_matches_original"] = (got == want)
        dst.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✓ {old['model']:52} {before} → {old['proviso_blind_count']}"
              f"  ({old['probes_device']} · {got})")
        moved += 1
    print(f"\n합침 {moved} · 건너뜀 {skipped} · 대응없음 {missing}")
    #: ★아직 옛 공식인 것이 남아 있으면 **세어서 말한다.** 조용히 끝내지 않는다.
    stale = [json.loads(p.read_text(encoding="utf-8"))["model"]
             for p in sorted(_OUT.glob("*.json"))
             if "blind_eps" not in json.loads(p.read_text(encoding="utf-8"))]
    if stale:
        print(f"★아직 재측정 안 된 것 {len(stale)}건 — 표에 ☠로 남습니다:")
        for m in stale:
            print(f"    {m}")
    else:
        print("★전부 재측정됐습니다.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="GPU 박스에서 내려받은 결과 폴더")
    ap.add_argument("--allow-dtype-mismatch", action="store_true",
                    help="정밀도가 달라도 옮긴다(권장하지 않음)")
    a = ap.parse_args()
    return merge(pathlib.Path(a.src), allow_mismatch=a.allow_dtype_mismatch)


if __name__ == "__main__":
    sys.exit(main())
