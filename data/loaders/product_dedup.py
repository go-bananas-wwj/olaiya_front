"""跨语言重复产品识别与合并：中英文双建档的产品行合并为一行，幂等、可审计、支持 --dry-run。

背景：产品库多源混建——种子/盖德采集为中文名行（如「适乐肤 VC 精华乳」），
INCIDecoder 采集为英文名行（如「CeraVe Vitamin C Serum」），同一产品可能各占一行，
污染相似检索。盖德行成分挂中文名成分行、INCIDecoder 行挂 INCI 成分行，
所以比对前须把成分归一到「规范键」：IECIC 2021 官方中文名（查不到则用 cn_name /
INCI 大写兜底），禁止 LLM 机翻。

识别判据（宁漏勿误判，全部满足才算疑似对）：
- 跨语言对（一方名含中文、另一方纯拉丁名），同品牌组（品牌取中文部分归组）：
  成分规范键 Jaccard ≥ 0.90，或 (0.85 ≤ J < 0.90 且较小集合被包含率 ≥ 0.96)；
  且包含率 ≥ 0.93、成分数差 ≤ 2、较小成分数 ≥ 11。
  且必须「互为最相似」：中文行只取分数最高的英文候选，英文行也只接受分数最高的中文行，
  避免同系列短配方产品（洁面/卸妆液）互相误吸。
- 英文-英文对（INCIDecoder 同产品换 slug / 笔误重收录）：Jaccard ≥ 0.98、较小成分数 ≥ 12、
  且 same_product_name() 判定名称一致（token 多重集相同 / 仅词重复 / 仅编辑距离 ≤2 的
  笔误差异）；色号（Rose/Pure Gold）、肤质（Normal/Dry Skin）、版本（Enriched、
  Intense/Fresh Moist）等语义差异即使配方近乎相同也不合并（loader 本就有意按 slug 分建变体）。
- 中文-中文对永不合并（不同 NMPA 备案产品可能共用配方基底，无法区分）。

合并规则：
- 同一连通簇内选 keeper：位次（position）条数多者优先 → 成分条数多者 →
  有 INCIDecoder source_url 者优先 → id 小者优先。其余行按分数从高到低依次并入。
- product_claims / price_points 外键改指 keeper；efficacy_assertions 不挂产品，无需处理。
- product_ingredients：keeper 一条成分都没有时整体改指；否则按规范键对齐，
  keeper 行为空的列（position / disclosed_conc / conc_low / conc_high / conc_confidence /
  safety_risk / is_active / purpose，见 _FILL_PI_FIELDS）从被合并行补齐，冲突保留 keeper 并记日志；
  被合并行独有的成分不搬（避免把中文 stub 成分行混进 keeper 的 INCI 表），删除前计数记日志。
- products 标量字段（nmpa_id / registrant / filing_date / category / price_current / spec）
  keeper 为空时从被合并行补，冲突保留 keeper 并记日志；nmpa_id 有 UNIQUE 约束，冲突只记不动。
- 被合并行中文名不改写 keeper.name，完整留在 merge_log.detail 供审计与后续别名化。
- 所有合并写 merge_log（kind='merge'，(kind, dup_id) 唯一），重跑自动跳过，天然幂等。

品牌双名归一（--no-brand-normalize 可关）：brand 同时含中文与拉丁的双名写法
（如「理肤泉 La Roche-Posay」），若其中文部分或拉丁部分作为独立品牌已存在且产品数更多，
归一到多数派写法并写 merge_log（kind='brand_normalize'）；无多数派目标（如「OLAY 玉兰油」
本身就是多数派）则不动。归一先于查重，使双名行进入正确的品牌组。

运行：
  PYTHONPATH="backend:." .venv/bin/python data/loaders/product_dedup.py --dry-run   # 只出清单
  PYTHONPATH="backend:." .venv/bin/python data/loaders/product_dedup.py            # 实跑合并
  PYTHONPATH="backend:." .venv/bin/python data/loaders/product_dedup.py --repair /tmp/cfz_backup_before_dedup.db [--dry-run]
    # 补救：v1 合并丢失的 conc_*/盖德画像列从备份库补回 keeper（幂等，merge_log kind='repair'）

历史口径说明（v1 已执行合并不返工，如实记录）：
- v1 的 slug 括号正则未要求连字符，#317「Moisturising Cream (Europe)」→#310 与
  #3032（eu-version slug）→#604 两对按当时规则合并（merge_log #29/#32）；两对配方 J=1.0
  实际无害，不回滚、不删日志。现正则要求括号含连字符，(Europe) 类地区版落入语义差异判定、不再合并。
- v1 合并只搬 position/disclosed_conc，dup #1（12 条 conc_*）、#74（35 条 conc_*）及
  9 个中文 dup 的盖德画像列随删行丢失，已由 --repair 模式从备份补回（merge_log kind='repair'）。
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db

IECIC_MAP_PATH = Path(__file__).resolve().parents[1] / "seed" / "inci_cn_map.json"

_CJK = re.compile(r"[一-龥]")
_WS = re.compile(r"\s+")

# 判据阈值（见 docstring）
X_JACCARD = 0.90            # 跨语言 Jaccard 主阈值
X_JACCARD_LO = 0.85         # 跨语言 Jaccard 放宽下限（需更高包含率）
X_CONTAIN_RELAX = 0.96      # 放宽档要求的包含率
X_CONTAIN = 0.93            # 跨语言包含率下限
X_MAX_COUNT_DIFF = 2        # 跨语言成分数差上限
X_MIN_COUNT = 11            # 跨语言较小成分数下限（短配方同系列易撞车）
EN_JACCARD = 0.98           # 英文-英文 Jaccard 阈值
EN_MIN_COUNT = 12           # 英文-英文较小成分数下限

# merge_log 表结构见 backend/app/models/product.py MergeLog（init_db 建表）


def has_cjk(s: str | None) -> bool:
    return bool(_CJK.search(s or ""))


def load_iecic_map(path: Path = IECIC_MAP_PATH) -> dict[str, str]:
    """IECIC 2021 INCI(大写) → 官方中文名。"""
    raw = json.loads(path.read_text(encoding="utf-8"))["map"]
    return {k.upper(): v["cn_name"] for k, v in raw.items()}


def ingredient_key(inci_name: str, cn_name: str, iecic: dict[str, str]) -> str:
    """成分规范键：优先 IECIC 官方中文名（兼容 ALCOHOL DENAT. 结尾点变体），
    其次含中文的 cn_name，最后 INCI 大写兜底。中英文成分行借此对齐。"""
    u = (inci_name or "").upper().strip()
    for cand in (u, u.rstrip("."), u + "."):
        if cand in iecic:
            return _WS.sub(" ", iecic[cand]).strip()
    if has_cjk(cn_name):
        return _WS.sub(" ", cn_name).strip()
    return "INCI:" + u


def brand_group(brand: str | None) -> str:
    """品牌归组键：取全部中文字符；无中文（SK-II / The Ordinary）用原串。"""
    cjk = "".join(_CJK.findall(brand or ""))
    return cjk if cjk else (brand or "")


_SLUG_PAREN = re.compile(r"[（(][a-z0-9]+-[a-z0-9-]*[）)]")
_TOK = re.compile(r"[a-z0-9]+")


def _name_tokens(name: str) -> list[str]:
    """英文名 token 序列：小写、只剥 slug 形括号（必须含连字符，如「（la-roche-posay-xxx-2）」）。
    「(Europe)」「(Rose Gold)」「(2022 Reformulation)」等无连字符括号是语义标注，保留进 token，
    走差异判定——(Europe) 这类地区版本差异按「不合并」处理（见 same_product_name）。"""
    base = _SLUG_PAREN.sub(" ", name.lower())
    return _TOK.findall(base)


def _edit_dist(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein 距离，超过 cap 提前返回 cap+1（token 很短，DP 足够）。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def same_product_name(a: str, b: str) -> bool:
    """英文-英文「同产品重收录」名称判定（宁漏勿误判）：
    - token 多重集完全相同（大小写/标点/slug 括号差异）→ 是；
    - 一方多出的 token 在另一方出现过（词重复，如 'Effaclar Effaclar …'）→ 是；
    - 其余差异 token 能一一配对且编辑距离 ≤ 2（笔误重收录，如 Effaclar/Effaclear、
      Mosturising/Moisturizing）→ 是；
    色号（Rose/Pure Gold）、肤质（Normal/Dry Skin）、版本（Intense/Fresh Moist、Enriched、
    (Europe) 地区版）等语义差异 → 否。
    注：v1 正则误把无连字符括号当 slug，导致 #317「Moisturising Cream (Europe)」→#310、
    #3032（eu-version slug）→#604 两对已合并（merge_log #29/#32）；两对配方 J=1.0 实际无害，
    不回滚、不删日志，本修复只影响未来运行。"""
    from collections import Counter
    ca, cb = Counter(_name_tokens(a)), Counter(_name_tokens(b))
    extra_a, extra_b = ca - cb, cb - ca
    if not extra_a and not extra_b:
        return True
    sa, sb = set(ca), set(cb)
    if set(extra_a) <= sb and set(extra_b) <= sa:
        return True  # 一方只是重复了对方已有的词
    la, lb = sorted(extra_a.elements()), sorted(extra_b.elements())
    if len(la) != len(lb) or len(la) > 2:
        return False
    return all(_edit_dist(x, y, cap=2) <= 2 for x, y in zip(la, lb))


@dataclass
class ProductInfo:
    id: int
    name: str
    brand: str
    source_url: str
    keys: frozenset = field(default_factory=frozenset)   # 成分规范键集
    n_ingredients: int = 0
    n_positioned: int = 0

    @property
    def is_incidecoder(self) -> bool:
        return "incidecoder" in self.source_url

    @property
    def name_has_cjk(self) -> bool:
        return has_cjk(self.name)

    def keeper_score(self) -> tuple:
        """keeper 优先级：位次全 → 成分多 → INCIDecoder 来源 → id 小。"""
        return (self.n_positioned, self.n_ingredients, self.is_incidecoder, -self.id)


@dataclass
class Edge:
    a: int
    b: int
    jaccard: float
    containment: float
    kind: str  # 'cross_lang' | 'same_lang'


def collect_product_index(session: Session, iecic: dict[str, str]) -> dict[int, ProductInfo]:
    """全库产品 → 成分规范键集 / 位次统计索引。"""
    ing_key = {}
    for iid, inci, cn in session.execute(
            text("SELECT id, inci_name, cn_name FROM ingredients")):
        ing_key[iid] = ingredient_key(inci, cn, iecic)
    prods = {}
    for pid, name, brand, url in session.execute(
            text("SELECT id, name, brand, source_url FROM products")):
        prods[pid] = ProductInfo(id=pid, name=name, brand=brand or "",
                                 source_url=url or "")
    keys: dict[int, set] = {}
    for pid, iid, pos in session.execute(
            text("SELECT product_id, ingredient_id, position FROM product_ingredients")):
        keys.setdefault(pid, set()).add(ing_key[iid])
        p = prods.get(pid)
        if p is not None:
            p.n_ingredients += 1
            if pos is not None:
                p.n_positioned += 1
    for pid, ks in keys.items():
        if pid in prods:
            prods[pid].keys = frozenset(ks)
    return prods


def _pair_metrics(a: ProductInfo, b: ProductInfo) -> tuple[float, float] | None:
    """(Jaccard, 较小集包含率)；任一方无成分返回 None。"""
    if not a.keys or not b.keys:
        return None
    inter = len(a.keys & b.keys)
    if not inter:
        return None
    return inter / len(a.keys | b.keys), inter / min(len(a.keys), len(b.keys))


def find_duplicate_edges(prods: dict[int, ProductInfo]) -> list[Edge]:
    """按 docstring 判据找重复边：跨语言互为最相似 + 英文-英文变体。中文-中文不报。"""
    groups: dict[str, list[ProductInfo]] = {}
    for p in prods.values():
        if p.keys:
            groups.setdefault(brand_group(p.brand), []).append(p)

    cross: list[Edge] = []
    same_lang: list[Edge] = []
    for members in groups.values():
        cn = [p for p in members if p.name_has_cjk]
        en = [p for p in members if not p.name_has_cjk]
        for a in cn:
            for b in en:
                m = _pair_metrics(a, b)
                if m is None:
                    continue
                j, contain = m
                if min(len(a.keys), len(b.keys)) < X_MIN_COUNT:
                    continue
                if abs(len(a.keys) - len(b.keys)) > X_MAX_COUNT_DIFF:
                    continue
                if contain < X_CONTAIN:
                    continue
                if j >= X_JACCARD or (j >= X_JACCARD_LO and contain >= X_CONTAIN_RELAX):
                    cross.append(Edge(a.id, b.id, round(j, 4), round(contain, 4), "cross_lang"))
        for i, a in enumerate(en):
            for b in en[i + 1:]:
                m = _pair_metrics(a, b)
                if m is None:
                    continue
                j, _ = m
                if j < EN_JACCARD or min(len(a.keys), len(b.keys)) < EN_MIN_COUNT:
                    continue
                if same_product_name(a.name, b.name):
                    same_lang.append(Edge(a.id, b.id, round(j, 4), 1.0, "same_lang"))

    # 跨语言「互为最相似」过滤：分数 = (jaccard, containment, 成分数, -id)
    def edge_key(e: Edge, other: ProductInfo) -> tuple:
        return (e.jaccard, e.containment, other.n_ingredients, -other.id)

    best_of_cn: dict[int, Edge] = {}
    for e in cross:
        cur = best_of_cn.get(e.a)
        if cur is None or edge_key(e, prods[e.b]) > edge_key(cur, prods[cur.b]):
            best_of_cn[e.a] = e
    best_of_en: dict[int, Edge] = {}
    for e in cross:
        cur = best_of_en.get(e.b)
        if cur is None or edge_key(e, prods[e.a]) > edge_key(cur, prods[cur.a]):
            best_of_en[e.b] = e
    mutual = [e for e in best_of_cn.values() if best_of_en.get(e.b) is e]
    return mutual + same_lang


class _UnionFind:
    def __init__(self):
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


def cluster_edges(edges: list[Edge]) -> list[list[int]]:
    """重复边 → 连通簇（每簇一个产品组）。"""
    uf = _UnionFind()
    for e in edges:
        uf.union(e.a, e.b)
    clusters: dict[int, list[int]] = {}
    for e in edges:
        clusters.setdefault(uf.find(e.a), set()).update((e.a, e.b))  # type: ignore[arg-type]
    return [sorted(ids) for ids in clusters.values()]  # type: ignore[return-value]


def _log(session: Session, kind: str, keeper_id, dup_id, keeper_name, dup_name,
         brand, jaccard, detail: dict) -> None:
    session.execute(text(
        "INSERT INTO merge_log (kind, keeper_id, dup_id, keeper_name, dup_name,"
        " brand, jaccard, detail, created_at)"
        " VALUES (:kind, :kid, :did, :kn, :dn, :brand, :j, :detail, :ts)"),
        dict(kind=kind, kid=keeper_id, did=dup_id, kn=keeper_name, dn=dup_name,
             brand=brand, j=jaccard, detail=json.dumps(detail, ensure_ascii=False),
             ts=datetime.now(timezone.utc).isoformat(timespec="seconds")))


def already_merged(session: Session, kind: str, dup_id: int) -> bool:
    return session.execute(text(
        "SELECT 1 FROM merge_log WHERE kind=:k AND dup_id=:d LIMIT 1"),
        dict(k=kind, d=dup_id)).first() is not None


def choose_keeper(cluster: list[int], prods: dict[int, ProductInfo]) -> tuple[int, list[int]]:
    """簇内选 keeper，返回 (keeper_id, 其余按并入顺序——分数高者先并入，优先补 keeper 空位)。"""
    ordered = sorted(cluster, key=lambda pid: prods[pid].keeper_score(), reverse=True)
    return ordered[0], ordered[1:]


_FILL_PRODUCT_FIELDS = ("nmpa_id", "registrant", "filing_date", "category",
                        "price_current", "spec")

# 成分关联行「keeper 空则补」的列：位次/披露浓度 + 浓度推断结果 + 盖德画像列
_FILL_PI_FIELDS = ("position", "disclosed_conc",
                   "conc_low", "conc_high", "conc_confidence",
                   "safety_risk", "is_active", "purpose")


def merge_products(session: Session, keeper_id: int, dup_id: int,
                   jaccard: float | None, iecic: dict[str, str],
                   dry_run: bool = False) -> dict | None:
    """把 dup_id 并入 keeper_id。已合并过（merge_log 有记录）返回 None（幂等跳过），
    否则返回动作明细（同时写 merge_log）。dry_run 只算明细不落库。"""
    if already_merged(session, "merge", dup_id):
        return None
    kp = session.execute(text(
        "SELECT id, name, brand, nmpa_id, registrant, filing_date, category,"
        " price_current, spec, source_url FROM products WHERE id=:i"),
        dict(i=keeper_id)).mappings().first()
    dp = session.execute(text(
        "SELECT id, name, brand, nmpa_id, registrant, filing_date, category,"
        " price_current, spec, source_url FROM products WHERE id=:i"),
        dict(i=dup_id)).mappings().first()
    if kp is None or dp is None:
        return None

    detail: dict = {"keeper_url": kp["source_url"], "dup_url": dp["source_url"],
                    "filled_fields": {}, "conflicts": {}, "fk_moved": {},
                    "pi_filled": [], "dup_only_ingredients_dropped": 0}

    # 1) 标量字段：keeper 空则补，冲突记日志（nmpa_id 冲突绝不动，UNIQUE 约束）
    for f in _FILL_PRODUCT_FIELDS:
        kv, dv = kp[f], dp[f]
        if kv is None and dv is not None:
            detail["filled_fields"][f] = dv
        elif kv is not None and dv is not None and kv != dv:
            detail["conflicts"][f] = {"keeper": kv, "dup_dropped": dv}

    # 2) 外键改指
    for tbl in ("product_claims", "price_points"):
        n = session.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE product_id=:d"),
                            dict(d=dup_id)).scalar_one()
        detail["fk_moved"][tbl] = n

    # 3) 成分表：keeper 空则整体改指；否则规范键对齐，keeper 为 NULL 的列
    #    （_FILL_PI_FIELDS：位次/披露浓度/conc_*/盖德画像列）从 dup 补，冲突保留 keeper
    _pi_cols = ", ".join(f"pi.{f}" for f in _FILL_PI_FIELDS)
    keeper_pi = session.execute(text(
        f"SELECT pi.id, {_pi_cols},"
        " i.inci_name, i.cn_name FROM product_ingredients pi"
        " JOIN ingredients i ON i.id = pi.ingredient_id WHERE pi.product_id=:k"),
        dict(k=keeper_id)).all()
    dup_pi = session.execute(text(
        f"SELECT pi.id, {_pi_cols},"
        " i.inci_name, i.cn_name FROM product_ingredients pi"
        " JOIN ingredients i ON i.id = pi.ingredient_id WHERE pi.product_id=:d"),
        dict(d=dup_id)).all()
    reassign_pi = not keeper_pi and bool(dup_pi)
    if reassign_pi:
        detail["fk_moved"]["product_ingredients"] = len(dup_pi)
    else:
        kmap = {ingredient_key(r.inci_name, r.cn_name, iecic): r for r in keeper_pi}
        dropped = 0
        for r in dup_pi:
            krow = kmap.get(ingredient_key(r.inci_name, r.cn_name, iecic))
            if krow is None:
                dropped += 1
                continue
            for f in _FILL_PI_FIELDS:
                kv, dv = getattr(krow, f), getattr(r, f)
                if kv is None and dv is not None:
                    detail["pi_filled"].append(
                        {"keeper_pi_id": krow.id, "field": f, "value": dv})
                elif kv is not None and dv is not None and kv != dv:
                    detail["pi_conflicts"] = detail.get("pi_conflicts", 0) + 1
        detail["dup_only_ingredients_dropped"] = dropped
        detail["fk_moved"]["product_ingredients_deleted"] = len(dup_pi)

    if dry_run:
        return detail

    # ---- 实写 ----
    # nmpa_id 有 UNIQUE 约束：先释放 dup 占用再补 keeper，否则撞唯一索引
    if "nmpa_id" in detail["filled_fields"]:
        session.execute(text("UPDATE products SET nmpa_id=NULL WHERE id=:d"),
                        dict(d=dup_id))
    for f, v in detail["filled_fields"].items():
        session.execute(text(f"UPDATE products SET {f}=:v WHERE id=:k"),
                        dict(v=v, k=keeper_id))
    for tbl in ("product_claims", "price_points"):
        session.execute(text(f"UPDATE {tbl} SET product_id=:k WHERE product_id=:d"),
                        dict(k=keeper_id, d=dup_id))
    if reassign_pi:
        session.execute(text(
            "UPDATE product_ingredients SET product_id=:k WHERE product_id=:d"),
            dict(k=keeper_id, d=dup_id))
    else:
        for item in detail["pi_filled"]:
            session.execute(text(
                f"UPDATE product_ingredients SET {item['field']}=:v WHERE id=:i"),
                dict(v=item["value"], i=item["keeper_pi_id"]))
        session.execute(text("DELETE FROM product_ingredients WHERE product_id=:d"),
                        dict(d=dup_id))
    session.execute(text("DELETE FROM products WHERE id=:d"), dict(d=dup_id))
    _log(session, "merge", keeper_id, dup_id, kp["name"], dp["name"],
         kp["brand"], jaccard, detail)
    return detail


def normalize_brands(session: Session, dry_run: bool = False) -> list[dict]:
    """双名品牌（中文+拉丁）归一到库内多数派写法；无多数派目标不动。返回动作清单。"""
    counts = dict(session.execute(text(
        "SELECT brand, COUNT(*) FROM products GROUP BY brand")).all())
    actions = []
    for brand, cnt in sorted(counts.items()):
        if not has_cjk(brand) or " " not in brand:
            continue  # 纯中文 / 纯拉丁不是双名
        cjk = "".join(_CJK.findall(brand))
        latin = _WS.sub(" ", _CJK.sub(" ", brand)).strip()
        candidates = [(c, counts.get(c, 0)) for c in (cjk, latin)
                      if c and c != brand]
        target, target_cnt = max(candidates, key=lambda x: x[1], default=(None, 0))
        if not target or target_cnt <= cnt:
            continue  # 没有多数派目标（如「OLAY 玉兰油」自身即多数派）
        todo = [pid for (pid,) in session.execute(text(
            "SELECT p.id FROM products p WHERE p.brand=:b"
            " AND NOT EXISTS (SELECT 1 FROM merge_log m"
            "  WHERE m.kind='brand_normalize' AND m.dup_id=p.id)"),
            dict(b=brand)).all()]
        if not todo:
            continue
        actions.append({"brand_from": brand, "brand_to": target,
                        "products": len(todo), "ids": todo})
        if dry_run:
            continue
        for pid in todo:
            session.execute(text("UPDATE products SET brand=:t WHERE id=:i"),
                            dict(t=target, i=pid))
            _log(session, "brand_normalize", None, pid, None, None, target, None,
                 {"brand_from": brand, "brand_to": target})
    return actions


def repair_from_backup(session: Session, backup_path: str | Path,
                       iecic: dict[str, str], dry_run: bool = False) -> list[dict]:
    """实库补救：v1 合并只搬 position/disclosed_conc，dup 行的 conc_*（浓度推断结果）
    与盖德画像列（safety_risk/is_active/purpose）随删行丢失。本函数从合并前备份库
    把这些列按规范键对齐补回 keeper（keeper 对应列仍为 NULL 才补，冲突保留 keeper 计数）。
    幂等：每个已合并 dup 补完写 merge_log（kind='repair'，(kind, dup_id) 唯一），重跑跳过。
    """
    backup_path = str(Path(backup_path).resolve())
    if not Path(backup_path).exists():
        raise FileNotFoundError(backup_path)
    # 两阶段：先在事务内把主库/备份库数据全部读出并算好补齐清单，
    # 结束事务后 DETACH（SQLite 不允许活动事务中 DETACH），最后实写。
    session.execute(text("ATTACH DATABASE :p AS bak"), dict(p=backup_path))
    try:
        merges = session.execute(text(
            "SELECT dup_id, keeper_id, dup_name, keeper_name FROM merge_log"
            " WHERE kind='merge' ORDER BY dup_id")).all()
        _pi_cols = ", ".join(f"pi.{f}" for f in _FILL_PI_FIELDS)
        plan = []  # (dup_id, keeper_id, dup_name, keeper_name, fills, conflicts)
        report = []
        for dup_id, keeper_id, dup_name, keeper_name in merges:
            if already_merged(session, "repair", dup_id):
                report.append({"dup_id": dup_id, "keeper_id": keeper_id,
                               "skipped": True, "fills": 0, "conflicts": 0})
                continue
            krows = session.execute(text(
                f"SELECT pi.id, {_pi_cols}, i.inci_name, i.cn_name"
                " FROM product_ingredients pi"
                " JOIN ingredients i ON i.id = pi.ingredient_id"
                " WHERE pi.product_id=:k"), dict(k=keeper_id)).all()
            kmap = {ingredient_key(r.inci_name, r.cn_name, iecic): r for r in krows}
            drows = session.execute(text(
                f"SELECT {_pi_cols}, i.inci_name, i.cn_name"
                " FROM bak.product_ingredients pi"
                " JOIN bak.ingredients i ON i.id = pi.ingredient_id"
                " WHERE pi.product_id=:d"), dict(d=dup_id)).all()
            fills, conflicts = [], 0
            for r in drows:
                krow = kmap.get(ingredient_key(r.inci_name, r.cn_name, iecic))
                if krow is None:
                    continue  # dup 独有成分本就没搬，无可补
                for f in _FILL_PI_FIELDS:
                    kv, dv = getattr(krow, f), getattr(r, f)
                    if kv is None and dv is not None:
                        fills.append({"keeper_pi_id": krow.id, "field": f, "value": dv})
                    elif kv is not None and dv is not None and kv != dv:
                        conflicts += 1
            plan.append((dup_id, keeper_id, dup_name, keeper_name, fills, conflicts))
            report.append({"dup_id": dup_id, "keeper_id": keeper_id, "skipped": False,
                           "fills": len(fills), "conflicts": conflicts})
        session.rollback()  # 只读阶段结束：关闭事务以便 DETACH
    finally:
        session.execute(text("DETACH DATABASE bak"))
    if dry_run:
        return report
    for dup_id, keeper_id, dup_name, keeper_name, fills, conflicts in plan:
        for item in fills:
            session.execute(text(
                f"UPDATE product_ingredients SET {item['field']}=:v WHERE id=:i"),
                dict(v=item["value"], i=item["keeper_pi_id"]))
        _log(session, "repair", keeper_id, dup_id, keeper_name, dup_name,
             None, None, {"source": backup_path, "fills": len(fills),
                          "conflicts": conflicts})
    return report


def run(dry_run: bool = True, do_brand_normalize: bool = True) -> dict:
    init_db()
    iecic = load_iecic_map()
    report: dict = {"dry_run": dry_run}
    with SessionLocal() as session:
        if do_brand_normalize:
            report["brand_normalize"] = normalize_brands(session, dry_run=dry_run)
        prods = collect_product_index(session, iecic)
        edges = find_duplicate_edges(prods)
        clusters = cluster_edges(edges)
        jac = {frozenset((e.a, e.b)): e.jaccard for e in edges}
        merges = []
        for cluster in sorted(clusters, key=lambda c: c[0]):
            keeper_id, dups = choose_keeper(cluster, prods)
            k = prods[keeper_id]
            for did in dups:
                d = prods[did]
                j = jac.get(frozenset((keeper_id, did)))
                detail = merge_products(session, keeper_id, did, j, iecic,
                                        dry_run=dry_run)
                merges.append({"keeper_id": keeper_id, "keeper_name": k.name,
                               "dup_id": did, "dup_name": d.name, "brand": k.brand,
                               "jaccard": j, "skipped": detail is None,
                               "detail": detail})
        report["merges"] = merges
        report["summary"] = {
            "products": len(prods),
            "edges": len(edges),
            "clusters": len(clusters),
            "merged" if not dry_run else "would_merge":
                sum(1 for m in merges if not m["skipped"]),
        }
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="只出清单不落库")
    ap.add_argument("--no-brand-normalize", action="store_true", help="跳过品牌双名归一")
    ap.add_argument("--repair", metavar="备份库路径",
                    help="补救模式：从合并前备份库把 dup 丢失的 conc_*/画像列补回 keeper（幂等）")
    args = ap.parse_args()
    if args.repair:
        init_db()
        with SessionLocal() as session:
            report = repair_from_backup(session, args.repair, load_iecic_map(),
                                        dry_run=args.dry_run)
            for r in report:
                tag = "跳过(已补救)" if r["skipped"] else ("候选" if args.dry_run else "补救")
                print(f"[{tag}] dup #{r['dup_id']} → keeper #{r['keeper_id']}："
                      f"补 {r['fills']} 列，冲突保留 keeper {r['conflicts']} 处")
            total = sum(r["fills"] for r in report)
            print(f"汇总：{len(report)} 个已合并 dup，共补 {total} 列"
                  f"（{'dry-run，未落库' if args.dry_run else '已落库'}）")
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        return
    report = run(dry_run=args.dry_run, do_brand_normalize=not args.no_brand_normalize)
    for a in report.get("brand_normalize", []):
        print(f"[品牌归一] {a['brand_from']} → {a['brand_to']}（{a['products']} 行: {a['ids']}）")
    for m in report["merges"]:
        tag = "跳过(已合并)" if m["skipped"] else ("候选" if report["dry_run"] else "合并")
        print(f"[{tag}] #{m['dup_id']}「{m['dup_name']}」 → #{m['keeper_id']}"
              f"「{m['keeper_name']}」（{m['brand']}，J={m['jaccard']}）")
        d = m.get("detail")
        if d:
            if d["filled_fields"]:
                print(f"    补字段: {d['filled_fields']}")
            if d["conflicts"]:
                print(f"    冲突保留 keeper: {d['conflicts']}")
            print(f"    外键: {d['fk_moved']}，dup 独有成分丢弃 {d['dup_only_ingredients_dropped']} 条")
    print("汇总:", json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
