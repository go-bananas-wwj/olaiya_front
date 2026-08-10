"""INCI 成分名中文化 + 噪声清洗 loader。

数据源：data/seed/inci_cn_map.json（IECIC 2021 官方目录提取，含 source 与抽查核对说明；
由 data/tools/extract_iecic_pdf.py + data/tools/build_inci_cn_map.py 产出，禁止 LLM 机翻）。

清洗规则（normalize_inci）：
- 去空括号 `[]` 后缀、去 `<N%` 浓度尾巴、去 `->` 尾巴、去尾部 `*`/`^` 标记、去前导 `*`/`^`
  营销标记（`*VITAMIN C`→`VITAMIN C`；剥完仍无映射的保持剥后干净名，不猜翻译）；
- 反斜杠多语名（英\\拉丁\\法，如 `WATER\\AQUA\\EAU`）与含 EXTRAIT 的斜杠/无分隔双语名
  取英文 INCI 段；弯引号归直引号；首尾空白与内部多余空格归一；
- `[NANO]` 是有效纳米标识，保留不动；普通斜杠共聚物名（CAPRYLIC/CAPRIC ...）不动。

附加规范化（resolve_bilingual 入口）：
- 欧莱雅内部配方码括号 `(F.I.L. xxx/1)` 剥除后走既有规则，剥除的码记入 merge_log（不丢信息）；
- USAN→INCI 别名（data/seed/usan_inci_alias.json，NIH PubChem 同 CID 同义词双向核验产出，
  构建器 data/tools/build_usan_alias.py）：AVOBENZONE/OCTISALATE 等美国 USAN 名规范化到
  IECIC 键后走既有合并/回填。别名只用于匹配，中文名永远来自 IECIC 映射。

斜杠/括号双语名规则（resolve_bilingual，美式 dual labeling，如 PARFUM/FRAGRANCE、
TITANIUM DIOXIDE (CI 77891)）：全名精确命中 IECIC 映射的不动（共聚物 CAPRYLIC/CAPRIC ...）；
否则拆斜杠两段/括号主内段逐段查映射（InciResolver：精确键 → 去括号段精确键 → 去括号
派生键，派生键同样出自 IECIC 条目且仅取无歧义者），恰一段命中取命中段的 IECIC 规范键，
两段都命中取非 CI 号段（同为非 CI 取首段/主段）并记歧义日志；中文名相同的双段视为同物
直接取规范键。多重护栏防误并：≥3 段斜杠须 ≥2 段命中（多语同物才处理，藻类混配等不动）、
非命中段疑似拉丁双名（属+种）不动、命中键与非命中段共享 ≥2 个物质词（同物种不同部位/
粗细度）不动、形态词（OIL/EXTRACT/BUTTER...）不一致且无共享物质词不动、PEG/PPG 段
（共聚物命名）不动、括号主段含 ,;()/[]· （多成分拼接）不动；XXX (NANO) 归一到 [NANO] 形态；
括号移位形态（BUTYROSPERMUM PARKII (SHEA BUTTER)）仅当移位后精确命中 IECIC 键才采用；
工艺限定词括号（HYDROLYZED/FERMENTED 等）仅当 IECIC 有对应工艺条目（如 HYDROLYZED XXX）
才映射过去，否则保持原样不吞工艺词；括号内是 CI 号而主段未命中映射时同样保持原样
（防 ORANGE 5 LAKE (CI 45370) 色淀变体被吞）。
无法判定的一律保持原样。

合并规则：清洗后与库内其他成分行撞名（大小写无关）时合并——product_ingredients 与
efficacy_assertions 的 ingredient_id 改指保留行（优先保留本名已是规范名的行，否则 id 最小者），
(product_id, ingredient_id) 已存在的链接跳过并删除多余链接，随后删除重复成分行。全部写 merge_log。

回填规则：用规范化 inci_name 查映射表，命中且现 cn_name 不含中文才更新；已有中文名
（手工核实种子）不覆盖；未命中保持原样，绝不猜测翻译。合并时 dup 有中文名而 keeper
没有则转移给 keeper。收尾清理：无中文的占位 cn_name 对齐清洗后的 inci_name；
含中文的 cn_name 只去 */^ 与空 [] 尾巴（保守，干净手工名不动）。

运行：PYTHONPATH="backend:." .venv/bin/python data/loaders/inci_cn_loader.py [--seed 路径] [--dry-run]
"""

import argparse
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.ingredient import EfficacyAssertion, Ingredient
from app.models.product import ProductIngredient

SEED_PATH = Path(__file__).resolve().parents[1] / "seed" / "inci_cn_map.json"

_WS = re.compile(r"\s+")
_CN = re.compile(r"[一-鿿]")
_EMPTY_BRACKET = re.compile(r"\s*\[\s*\]\s*$")
_CONC_TAIL = re.compile(r"\s*<\s*\d+(?:\.\d+)?\s*%\s*$")
_ARROW_TAIL = re.compile(r"\s*->.*$")
_STAR_TAIL = re.compile(r"[\s*^]*[*^]+$")  # 尾部 */^ 标记（如 NIACINAMIDE*、XXX^**）
_STAR_HEAD = re.compile(r"^[*^\s]+")  # 前导 */^ 营销标记（如 *VITAMIN C、^**PRO-VITAMIN B5）
_EXTRAIT_TAIL = re.compile(r"\s+EXTRAIT\s+.*$", re.IGNORECASE)
_FIL_PAREN = re.compile(r"\s*\(((?:CODE )?F\.I\.L\.:? [^()]*)\)\s*$", re.IGNORECASE)  # 欧莱雅内部配方码
ALIAS_SEED_PATH = Path(__file__).resolve().parents[1] / "seed" / "usan_inci_alias.json"

# 工艺限定词括号：XXX (HYDROLYZED)/(FERMENTED)。能映射到 IECIC 对应条目才动
# （候选键仍须过 resolver 精确命中，绝不猜）；没有对应条目就保持原样，不吞工艺词。
_PROCESS_PAREN = {
    "HYDROLYZED": lambda main: [f"HYDROLYZED {main}"],
    "HYDROLYSED": lambda main: [f"HYDROLYZED {main}"],
    "FERMENTED": lambda main: [f"{main} FERMENT"],
}

# —— 双语名规范化（resolve_bilingual）用 ——
_BRACKET_SEG = re.compile(r"\s*(?:\([^()]*\)|\[[^\[\]]*\])")  # 圆/方括号段（含 (NANO)/[NANO]）
_TRAILING_PAREN = re.compile(r"^(.+?)\s*\(([^()]{2,})\)\s*$")  # 结尾括号形态 XXX (YYY)
_COMPOSITE = re.compile(r"[()\[\],;/·]")  # 括号主段含这些 = 多成分拼接，不处理
_CI_NUM = re.compile(r"^CI \d+$")  # 着色剂编号段（INCI 名优先于 CI 号）
_BINOMIAL = re.compile(r"^[A-Z][A-Z-]{2,17} [A-Z][A-Z-]{2,17}$")  # 疑似拉丁双名（属+种短词）
_PEG_PPG = re.compile(r"\bP[PE]G-\d")  # PEG/PPG 段是共聚物命名，不是双语
_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9-]*")
# 形态/部位词：判断两段是否同物时不算「物质词」
_FORM_WORDS = {"EXTRACT", "OIL", "BUTTER", "WAX", "CERA", "WATER", "AQUA", "JUICE",
               "POWDER", "STARCH", "PROTEIN", "GUM", "SALT", "KERNEL", "SEED", "FRUIT",
               "LEAF", "ROOT", "FLOWER", "BRAN", "GERM", "PEEL", "BARK", "BUD", "RESIN"}
_FORM_CLASS = {"OIL": "oil", "EXTRACT": "extract", "BUTTER": "butter", "WAX": "wax",
               "CERA": "wax", "WATER": "water", "AQUA": "water", "JUICE": "juice",
               "POWDER": "powder", "STARCH": "starch", "PROTEIN": "protein",
               "GUM": "gum", "SALT": "salt"}


def normalize_inci(name: str) -> str:
    """INCI 名规范化：去噪声尾巴、多语名取英文段、空白归一。规则见模块 docstring。"""
    s = (name or "").replace("’", "'").replace("‘", "'")
    if "\\" in s or ("EXTRAIT" in s.upper() and "/" in s):
        # 英\拉丁\法 多语拼接（或 EXTRAIT 斜杠双语）：取第一个不含 EXTRAIT 的段
        segs = [seg.strip() for seg in re.split(r"[\\/]+", s) if seg.strip()]
        latin = [seg for seg in segs if "EXTRAIT" not in seg.upper()]
        s = latin[0] if latin else (segs[0] if segs else "")
    s = _EXTRAIT_TAIL.sub("", s)  # 无分隔符的法文尾巴（YEAST EXTRACT FAEX EXTRAIT DE LEVURE）
    s = _EMPTY_BRACKET.sub("", s)
    s = _CONC_TAIL.sub("", s)
    s = _ARROW_TAIL.sub("", s)
    s = _STAR_TAIL.sub("", s)
    s = _STAR_HEAD.sub("", s)  # 前导营销标记：剥后仍无映射就保持剥后干净名，不猜翻译
    return _WS.sub(" ", s).strip()


def load_seed(path: Path = SEED_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class InciResolver:
    """IECIC 映射查询：精确键 → 结尾句点变体（ALCOHOL DENAT vs ALCOHOL DENAT. 双向）→
    去括号段精确键（含 [NANO]）→ 去括号派生键（仅无歧义）。
    派生键同样来自 IECIC 条目（如 BUTYROSPERMUM PARKII (SHEA) BUTTER 派生出
    BUTYROSPERMUM PARKII BUTTER），多条目坍缩到同一派生键且中文名不一致的弃用。"""

    def __init__(self, mapping: dict):
        self.map = mapping
        derived: dict[str, list[tuple[str, str]]] = {}
        for key, entry in mapping.items():
            sk = _BRACKET_SEG.sub("", key).strip()
            if sk and sk != key:
                derived.setdefault(sk, []).append((key, entry["cn_name"]))
        self.derived = {sk: keys[0][0] for sk, keys in derived.items()
                        if len({cn for _, cn in keys}) == 1}

    def resolve(self, name: str) -> str | None:
        """返回 name 对应的 IECIC 规范键（映射表原键），查不到返回 None。"""
        k = _WS.sub(" ", (name or "")).strip().upper()
        if k in self.map:
            return k
        if k + "." in self.map:  # 结尾句点变体（ALCOHOL DENAT vs ALCOHOL DENAT.）
            return k + "."
        if k.endswith(".") and k[:-1] in self.map:  # 反向句点变体（TRIETHANOLAMINE.）
            return k[:-1]
        sk = _BRACKET_SEG.sub("", k).strip()
        if sk != k and sk in self.map:
            return sk
        return self.derived.get(sk)

    def cn_of(self, key: str) -> str:
        return self.map[key]["cn_name"]


def _substance_tokens(name: str) -> set[str]:
    """物质词集合：≥3 位字母词，去掉形态/部位词（OIL/EXTRACT/SEED...）。"""
    return {t for t in _TOKEN.findall(name.upper())
            if len(t) >= 3 and any(c.isalpha() for c in t) and t not in _FORM_WORDS}


def _form_class(name: str) -> str | None:
    words = name.upper().split()
    return _FORM_CLASS.get(words[-1]) if words else None


def _one_hit_ok(hit_key: str, other_seg: str) -> bool:
    """恰一段命中时判定是否双语同物（而非混配/粗细度不同的两种成分）。"""
    other = other_seg.upper()
    hit_tokens = hit_key.split()
    other_tokens = other.split()
    # 非命中段是命中键的词级前缀：通用名/具体名（ACACIA SENEGAL/ACACIA SENEGAL GUM）
    if len(other_tokens) < len(hit_tokens) and hit_tokens[:len(other_tokens)] == other_tokens:
        return False
    # 非命中段疑似拉丁双名（属+种，无形态词）：可能是另一物种的混配
    if _BINOMIAL.match(other) and other_tokens[-1] not in _FORM_WORDS:
        return False
    shared = _substance_tokens(other) & _substance_tokens(hit_key)
    # 共享 ≥2 个物质词：同物种不同部位/粗细度（NELUMBIUM SPECIOSUM EXTRACT/...FLOWER EXTRACT）
    if len(shared) >= 2:
        return False
    # 形态词不一致且毫无共享物质词（ZEA MAYS / CORN GERM OIL）
    if not shared and _form_class(other) != _form_class(hit_key):
        return False
    return True


def resolve_bilingual(name: str, resolver: InciResolver,
                      aliases: dict[str, str] | None = None) -> tuple[str, str | None]:
    """斜杠/括号双语名规范化：返回 (新 inci_name, 日志标记 or None)。
    全名精确命中映射（共聚物等）与无法判定的形态都保持原样。规则见模块 docstring。
    aliases：USAN→INCI 别名表（data/seed/usan_inci_alias.json，PubChem 同 CID 核验，
    键大写、值为 IECIC 规范键），仅用于规范化匹配，中文名永远来自 IECIC 映射。"""
    tags: list[str] = []
    s = normalize_inci(name)
    m_fil = _FIL_PAREN.search(s)
    if m_fil:  # 欧莱雅内部配方码括号：剥除后记日志（码不丢），再走既有规则
        tags.append(f"fil({m_fil.group(1)})")
        s = _WS.sub(" ", _FIL_PAREN.sub("", s)).strip()
    if s.upper() in resolver.map:
        return s, "+".join(tags) or None  # (a) 全名精确命中，不动（可能仅剥了 F.I.L.）
    if aliases and s.upper() in aliases:
        tags.append("usan-alias")
        return aliases[s.upper()], "+".join(tags)  # USAN 名规范化到 IECIC 键
    if s.endswith("."):
        r = resolver.resolve(s)  # 尾部句点变体（TRIETHANOLAMINE.）：命中规范键则归一
        if r:
            return r, "+".join(tags) or None

    if "/" in s:
        segs = [seg.strip() for seg in s.split("/") if seg.strip()]
        if len(segs) >= 2 and not _PEG_PPG.search(s):
            hits = [(seg, resolver.resolve(seg)) for seg in segs]
            got = [(seg, k) for seg, k in hits if k]
            if len(segs) == 2 and len(got) == 1:
                (hseg, hk) = got[0]
                oseg = next(seg for seg, k in hits if not k)
                if _one_hit_ok(hk, oseg):
                    return hk, "+".join(tags + [f"slash-one({oseg} 未命中)"])
            elif len(got) >= 2:  # 两段都命中；≥3 段须 ≥2 命中（多语同物才处理，混配不动）
                uniq: list[tuple[str, str]] = []
                for seg, k in got:
                    if k not in {u[1] for u in uniq}:
                        uniq.append((seg, k))
                nonci = [u for u in uniq if not _CI_NUM.match(u[1])]
                pick_seg, pick_key = (nonci or uniq)[0]
                others = [k for _, k in uniq if k != pick_key]
                if not others:
                    return pick_key, "+".join(tags + ["slash-same"])  # 双段同键（含 [NANO]/括号变体）
                if len({resolver.cn_of(k) for _, k in uniq}) == 1:
                    return pick_key, "+".join(tags + ["slash-same-cn"])
                # 中文名不同：CI 号段直取（与 INCI 名段无共享物质词）；非 CI 段要求
                # 与其他命中段无共享物质词（ROYAL JELLY/ROYAL JELLY EXTRACT 这类不同物不动）
                if _CI_NUM.match(pick_key):
                    return pick_key, "+".join(tags + [f"slash-ambiguous(candidates={[k for _, k in uniq]})"])
                other_segs = [seg for seg, k in uniq if k != pick_key]
                if all(not (_substance_tokens(pick_seg) & _substance_tokens(o))
                       for o in other_segs):
                    return pick_key, "+".join(tags + [f"slash-ambiguous(candidates={[k for _, k in uniq]})"])
        return s, "+".join(tags) or None

    m = _TRAILING_PAREN.match(s)
    if m:
        main, inner = m.group(1).strip(), m.group(2).strip()
        if not _COMPOSITE.search(main):  # 主段含拼接符 = 多成分串，不动
            km, ki = resolver.resolve(main), resolver.resolve(inner)
            # 工艺限定词括号（HYDROLYZED/FERMENTED 等）：仅当能映射到 IECIC 对应
            # 工艺条目（如 HYDROLYZED XXX）才动，否则保持原样，不让 paren-main 吞工艺词
            if inner.upper() in _PROCESS_PAREN:
                for cand in _PROCESS_PAREN[inner.upper()](main):
                    kc = resolver.resolve(cand)
                    if kc:
                        return kc, "+".join(tags + [f"paren-process({inner} -> {kc})"])
                return s, "+".join(tags) or None
            if inner.upper() == "NANO" and km:
                return f"{km} [NANO]", "+".join(tags + ["paren-nano"])  # 归一到既有 [NANO] 形态
            if km and ki and km != ki:
                nonci = [k for k in (km, ki) if not _CI_NUM.match(k)]
                pick = nonci[0] if nonci else km  # 主段优先，CI 号让位 INCI 名
                return pick, "+".join(tags + [f"paren-ambiguous({main!r}|{inner!r} -> {pick!r})"])
            if km:
                return km, "+".join(tags + ["paren-main"])
            if ki and not _CI_NUM.match(ki):
                return ki, "+".join(tags + ["paren-inner"])
            # 括号内是 CI 号而主段未命中映射：保持原样（防 ORANGE 5 LAKE (CI 45370) 色淀变体被吞）
            # 括号移位形态：BUTYROSPERMUM PARKII (SHEA BUTTER) -> 试 (SHEA) BUTTER
            words = inner.split()
            if len(words) >= 2:
                kc = resolver.resolve(f"{main} ({words[0]}) {' '.join(words[1:])}")
                if kc and "(" in kc:  # 仅接受移位后精确命中带括号的 IECIC 键
                    return kc, "+".join(tags + ["paren-shift"])
    return s, "+".join(tags) or None


def _merge_into(session: Session, keeper: Ingredient, dup: Ingredient, stats: dict) -> None:
    """把 dup 的全部关联改指 keeper 后删除 dup。冲突的 (product_id, ingredient_id) 链接直接删除。
    守卫：dup 有中文名而 keeper 没有时，先把 dup 的中文名转移给 keeper（不丢手工核实名）。"""
    if not _CN.search(keeper.cn_name or "") and _CN.search(dup.cn_name or ""):
        stats["merge_log"].append(
            f"cn-transfer #{dup.id} {dup.cn_name!r} -> #{keeper.id}（原 {keeper.cn_name!r}）")
        keeper.cn_name = dup.cn_name
    existing = {l.product_id for l in
                session.query(ProductIngredient).filter_by(ingredient_id=keeper.id)}
    for link in session.query(ProductIngredient).filter_by(ingredient_id=dup.id).all():
        if link.product_id in existing:
            session.delete(link)  # 保留行已有同产品链接，删多余链接
        else:
            link.ingredient_id = keeper.id
            existing.add(link.product_id)
    for assertion in session.query(EfficacyAssertion).filter_by(ingredient_id=dup.id).all():
        assertion.ingredient_id = keeper.id
    stats["merge_log"].append(
        f"merge #{dup.id} {dup.inci_name!r} -> #{keeper.id} {keeper.inci_name!r}")
    session.delete(dup)
    session.flush()
    stats["merged"] += 1


def run_cleanup(session: Session, seed: dict | None = None,
                seed_path: Path = SEED_PATH,
                aliases: dict[str, str] | None = None) -> dict:
    """清洗 + 合并 + 回填 cn_name，返回统计。幂等。
    aliases：USAN→INCI 别名表（键大写 → IECIC 规范键），只用于规范化匹配。"""
    if seed is None:
        seed = load_seed(seed_path)
    mapping = seed["map"]  # 键已由 build_inci_cn_map.norm_inci 规范化
    resolver = InciResolver(mapping)
    stats: dict = {"renamed": 0, "merged": 0, "backfilled": 0, "already_cn": 0,
                   "cn_synced": 0, "cn_tail_cleaned": 0, "bilingual": 0,
                   "usan_alias": 0, "fil_stripped": 0,
                   "unmapped": 0, "unmapped_names": set(), "merge_log": []}

    # —— 阶段一：规范化 inci_name（含斜杠/括号双语规则），撞名合并 ——
    resolved: dict[int, str] = {}
    groups: dict[str, list[Ingredient]] = {}
    for row in session.query(Ingredient).order_by(Ingredient.id).all():
        new_name, tag = resolve_bilingual(row.inci_name, resolver, aliases=aliases)
        resolved[row.id] = new_name
        if tag:
            stats["merge_log"].append(f"{tag} #{row.id} {row.inci_name!r} -> {new_name!r}")
            stats["bilingual"] += 1
            stats["usan_alias"] += "usan-alias" in tag
            stats["fil_stripped"] += "fil(" in tag
        groups.setdefault(new_name.upper(), []).append(row)
    for key, grp in groups.items():
        cleaned = resolved[grp[0].id]
        keeper = next((r for r in grp if r.inci_name.upper() == key), grp[0])
        for row in grp:
            if row is not keeper:
                _merge_into(session, keeper, row, stats)
        if keeper.inci_name != cleaned:
            stats["merge_log"].append(f"rename #{keeper.id} {keeper.inci_name!r} -> {cleaned!r}")
            keeper.inci_name = cleaned
            stats["renamed"] += 1
    session.flush()

    # —— 阶段二：命中映射才回填 cn_name；已有中文名不覆盖；未命中保持原样 ——
    for row in session.query(Ingredient).all():
        rkey = resolver.resolve(normalize_inci(row.inci_name))
        entry = mapping.get(rkey) if rkey else None
        has_cn = bool(_CN.search(row.cn_name or ""))
        if entry is None:
            if not has_cn:
                stats["unmapped"] += 1
                stats["unmapped_names"].add(row.inci_name)
            continue
        if has_cn:
            stats["already_cn"] += 1
            continue
        if row.cn_name != entry["cn_name"]:  # 官名与现值相同（如 CI 着色剂官名即编号）不计回填
            row.cn_name = entry["cn_name"]
            stats["backfilled"] += 1
    session.flush()

    # —— 阶段三：cn_name 脏尾巴清理 ——
    # 无中文的 cn_name 是占位值（约定见 incidecoder_loader），一律对齐清洗后的 inci_name，
    # 修掉改名后残留的旧脏名（*/^/[]/EXTRAIT 尾巴）；含中文的 cn 只去 */^ 与空 [] 尾巴
    # （保守，不动主体文字），干净的手工中文名不受影响。
    for row in session.query(Ingredient).all():
        cn = row.cn_name or ""
        if _CN.search(cn):
            cleaned_cn = _STAR_TAIL.sub("", _EMPTY_BRACKET.sub("", cn)).strip()
            if cleaned_cn != cn:
                stats["merge_log"].append(f"cn-tail #{row.id} {cn!r} -> {cleaned_cn!r}")
                row.cn_name = cleaned_cn
                stats["cn_tail_cleaned"] += 1
        elif cn != row.inci_name:
            rkey = resolver.resolve(normalize_inci(row.inci_name))
            if rkey and mapping[rkey]["cn_name"] == cn:
                continue  # 官名即编号（CI 着色剂等）：阶段二已回填官名，不回对齐成 inci
            stats["merge_log"].append(f"cn-sync #{row.id} {cn!r} -> {row.inci_name!r}")
            row.cn_name = row.inci_name
            stats["cn_synced"] += 1
    session.flush()
    return stats


def coverage_report(session: Session, map_keys: set[str] | None = None,
                    resolver: InciResolver | None = None) -> dict:
    """中文化覆盖率：按成分行数 + 按 product_ingredients 关联加权。
    map_keys/resolver 传入时，官名即编号的 CI 着色剂（命中映射但无汉字）也算已覆盖，
    不进未映射清单；resolver 覆盖去括号/派生键命中（如 CI 77266 [NANO]）。"""
    rows = session.query(Ingredient).all()

    def covered(r: Ingredient) -> bool:
        if _CN.search(r.cn_name or ""):
            return True
        name = normalize_inci(r.inci_name)
        if resolver is not None:
            return resolver.resolve(name) is not None
        return bool(map_keys) and name.upper() in map_keys

    with_cn = sum(1 for r in rows if covered(r))
    links = session.query(ProductIngredient).all()
    cn_ids = {r.id for r in rows if covered(r)}
    links_cn = sum(1 for l in links if l.ingredient_id in cn_ids)
    # top 未映射（按产品覆盖数）
    counts: dict[int, int] = {}
    for l in links:
        counts[l.ingredient_id] = counts.get(l.ingredient_id, 0) + 1
    unmapped = [(counts.get(r.id, 0), r.inci_name) for r in rows if not covered(r)]
    unmapped.sort(reverse=True)
    return {"ingredients": len(rows), "with_cn": with_cn,
            "links": len(links), "links_cn": links_cn, "top_unmapped": unmapped[:30]}


def load_aliases(path: Path = ALIAS_SEED_PATH) -> dict[str, str]:
    """USAN→INCI 别名表（data/seed/usan_inci_alias.json，PubChem 同 CID 核验）。
    文件缺失时返回空表（别名是增量机制，不是必需依赖）。"""
    if not Path(path).exists():
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k.upper(): v for k, v in raw.get("alias", {}).items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", default=str(SEED_PATH), help="映射 seed 路径")
    parser.add_argument("--alias", default=str(ALIAS_SEED_PATH), help="USAN 别名 seed 路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    init_db()
    seed = load_seed(Path(args.seed))
    resolver = InciResolver(seed["map"])
    aliases = load_aliases(Path(args.alias))
    with SessionLocal() as s:
        stats = run_cleanup(s, seed=seed, aliases=aliases)
        rep = coverage_report(s, map_keys=set(seed["map"]), resolver=resolver)
        if args.dry_run:
            s.rollback()
        else:
            s.commit()
    print(f"清洗改名={stats['renamed']} 合并删除={stats['merged']} "
          f"回填中文名={stats['backfilled']} 已有中文跳过={stats['already_cn']} "
          f"双语规范化={stats['bilingual']} "
          f"（其中 USAN别名={stats['usan_alias']} F.I.L.剥除={stats['fil_stripped']}） "
          f"cn对齐={stats['cn_synced']} cn去尾={stats['cn_tail_cleaned']} "
          f"未映射={stats['unmapped']}{'（dry-run 已回滚）' if args.dry_run else ''}")
    for line in stats["merge_log"]:
        print(" ", line)
    pct = rep["with_cn"] / max(rep["ingredients"], 1) * 100
    wpct = rep["links_cn"] / max(rep["links"], 1) * 100
    print(f"覆盖率：成分 {rep['with_cn']}/{rep['ingredients']}（{pct:.1f}%），"
          f"按关联加权 {rep['links_cn']}/{rep['links']}（{wpct:.1f}%）")
    print("top 30 未映射成分（按产品覆盖数）：")
    for cnt, name in rep["top_unmapped"]:
        print(f"  {cnt:>5}  {name}")


if __name__ == "__main__":
    main()
