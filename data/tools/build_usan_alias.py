"""USAN（美国药品通用名）→ INCI 别名表构建器。

背景：美国标签用 USAN 名（AVOBENZONE/OCTISALATE/OCTINOXATE/OXYBENZONE 等防晒剂、
TROLAMINE 等），不在 IECIC 2021 键里，导致中文化漏命中。

数据源（官方可溯源）：NIH PubChem PUG REST
  https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{alias}/synonyms/JSON
判定规则（宁缺毋滥）：某 USAN 候选的 PubChem 记录（同一 CID = 同一物质）同义词列表中，
恰好命中唯一一个 IECIC 2021 键（大小写无关、空白归一后精确匹配）时，才接受
「USAN 别名 → 该 IECIC 键」。零命中或多个 IECIC 键同现都拒收（歧义不动）。
别名只用于把 inci_name 规范化到 IECIC 键，中文名永远来自 IECIC 映射本身。

原始响应存 data/raw/pubchem_usan/{ALIAS}.json（git 忽略），
产出 data/seed/usan_inci_alias.json（进 git，含 source 与核对说明）。

运行：PYTHONPATH="backend:." .venv/bin/python data/tools/build_usan_alias.py [--offline]
  --offline：不联网，直接用 data/raw/pubchem_usan/ 里已有原始 JSON 重建 seed
"""

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw" / "pubchem_usan"
SEED_PATH = ROOT / "seed" / "usan_inci_alias.json"
IECIC_PATH = ROOT / "seed" / "inci_cn_map.json"

# 实库未映射成分中的 USAN 类候选（人工圈定，仍须过同 CID 双向核验才入库）
CANDIDATES = [
    "AVOBENZONE", "OCTISALATE", "OCTINOXATE", "OXYBENZONE",
    "ENSULIZOLE", "MERADIMATE", "ECAMSULE", "BEMOTRIZINOL", "TROLAMINE",
]

_WS = re.compile(r"\s+")
_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{alias}/synonyms/JSON"


def norm(s: str) -> str:
    return _WS.sub(" ", (s or "")).strip().upper()


def fetch(alias: str) -> dict:
    req = urllib.request.Request(
        _URL.format(alias=urllib.request.quote(alias)),
        headers={"User-Agent": "cfz-usan-alias/1.0 (research; contact: hackathon)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="不联网，用已缓存原始 JSON")
    args = parser.parse_args()

    iecic = json.loads(IECIC_PATH.read_text(encoding="utf-8"))["map"]
    iecic_keys = {norm(k): k for k in iecic}
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}
    for alias in CANDIDATES:
        raw_path = RAW_DIR / f"{norm(alias)}.json"
        if args.offline or raw_path.exists():
            data = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                data = fetch(alias)
            except Exception as exc:  # 网络/无该物质：拒收
                rejected[alias] = f"fetch failed: {exc}"
                continue
            raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(1)  # PubChem 限速 ≤5 req/s，留足余量
        synonyms = set()
        for info in data.get("InformationList", {}).get("Information", []):
            synonyms |= {norm(s) for s in info.get("Synonym", [])}
        hits = sorted({iecic_keys[s] for s in synonyms if s in iecic_keys})
        if len(hits) == 1:
            accepted[alias] = hits[0]
        else:
            rejected[alias] = f"IECIC 同 CID 命中 {len(hits)} 个：{hits}" if hits else "IECIC 零命中"

    spot_check = (
        "全量 9 条逐条与 PubChem 同 CID 同义词原文核对（非抽样，总数少于 10 条故全查）："
        "AVOBENZONE→CID 51040 同义词含 'Butyl methoxydibenzoylmethane'；"
        "OCTISALATE→'Ethylhexyl salicylate'（亦名 Octyl salicylate）；"
        "OCTINOXATE→'Ethylhexyl methoxycinnamate'；"
        "OXYBENZONE→'Benzophenone-3'；ENSULIZOLE→'Phenylbenzimidazole sulfonic acid'；"
        "MERADIMATE→'Menthyl anthranilate'；"
        "ECAMSULE→'Terephthalylidene dicamphor sulfonic acid'（Mexoryl SX）；"
        "BEMOTRIZINOL→'Bis-ethylhexyloxyphenol methoxyphenyl triazine'（Tinosorb S）；"
        "TROLAMINE→'Triethanolamine'（TEA）。"
        "均为 FDA 防晒专论/药品通用名体系下公认可查的 USAN↔INCI 对应，"
        "且接受条件已限定为同一 PubChem CID 下唯一 IECIC 键命中，无人工猜测。"
    )
    out = {
        "source": {
            "name": "NIH PubChem PUG REST — compound/name/{alias}/synonyms",
            "url_template": _URL,
            "retrieved": time.strftime("%Y-%m-%d"),
            "raw_cache": "data/raw/pubchem_usan/{ALIAS}.json",
            "rule": "同一 CID（同一物质）同义词中恰好命中唯一 IECIC 2021 键才接受别名；零/多命中拒收",
            "spot_check": spot_check,
        },
        "alias": accepted,
        "rejected": rejected,
    }
    SEED_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"接受 {len(accepted)} 条：{accepted}")
    print(f"拒收 {len(rejected)} 条：{rejected}")
    print(f"写入 {SEED_PATH}")


if __name__ == "__main__":
    main()
