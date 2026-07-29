"""成分俗名/别名表：用户语言（VC、377、玻尿酸…）→ INCI 名（大写）。

RAG 证据检索（rag_qa）与 Agent 工具（agent_tools）共用同一张表——注册表给
LLM 用，与用户是同一语言。检索时先查别名表直达 INCI，再落回名字子串匹配；
别名命中优先于子串命中，防止「维生素C」被「生育酚（维生素E）」类长名或
分词兜底截胡。别名至少 2 字符，拉丁别名大小写无关，数字开头（377）合法。
"""

# INCI -> 别名元组（一个 INCI 可挂多个别名；同一别名挂多个 INCI 时，
# 声明顺序即命中顺序，如 玻尿酸 → 透明质酸、透明质酸钠）
INCI_ALIASES: dict[str, tuple[str, ...]] = {
    "ASCORBIC ACID": ("维生素C", "左旋VC", "维C", "VC"),
    "PHENYLETHYL RESORCINOL": ("SymWhite377", "377"),
    "RETINOL": ("维A", "A醇"),
    "TOCOPHEROL": ("维生素E", "生育酚", "维E"),
    "PANTHENOL": ("维生素B5", "泛醇", "B5"),
    "HYALURONIC ACID": ("玻尿酸",),
    "SODIUM HYALURONATE": ("玻尿酸",),
    "HYDROXYPROPYL TETRAHYDROPYRANTRIOL": ("玻色因",),
    "ECTOIN": ("依克多因",),
    "TRANEXAMIC ACID": ("传明酸",),
    "SALICYLIC ACID": ("水杨酸",),
    "NIACINAMIDE": ("烟酰胺",),
    "ACETYL HEXAPEPTIDE-8": ("阿基瑞林",),
    "COPPER TRIPEPTIDE-1": ("蓝铜胜肽",),
    "GLYCYRRHIZA GLABRA (LICORICE) ROOT EXTRACT": ("光甘草定",),
    "BAKUCHIOL": ("补骨脂酚",),
    "ERGOTHIONEINE": ("麦角硫因",),
    "CERAMIDE NP": ("神经酰胺",),
}


def _build_alias_index() -> dict[str, tuple[str, ...]]:
    """别名 -> INCI 元组（多目标保持 INCI_ALIASES 声明顺序）。"""
    index: dict[str, list[str]] = {}
    for inci, aliases in INCI_ALIASES.items():
        for alias in aliases:
            index.setdefault(alias, []).append(inci)
    return {alias: tuple(incis) for alias, incis in index.items()}


ALIAS_INDEX: dict[str, tuple[str, ...]] = _build_alias_index()

# 精确别名查询（拉丁大小写无关）： alias.upper() -> INCI 元组
_ALIAS_EXACT: dict[str, tuple[str, ...]] = {a.upper(): incis for a, incis in ALIAS_INDEX.items()}


def alias_exact(name: str) -> tuple[str, ...] | None:
    """整个查询词恰为别名时返回其 INCI 元组（大小写无关），否则 None。"""
    return _ALIAS_EXACT.get(name.strip().upper())


def aliases_in_text(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """文本中出现的别名 [(别名, INCI 元组)]：长别名优先，同长按出现位置。

    拉丁别名大小写无关（中文不受 upper 影响，统一转大写比对）。
    """
    upper = text.upper()
    hits: list[tuple[str, tuple[str, ...], int]] = []
    for alias, incis in ALIAS_INDEX.items():
        pos = upper.find(alias.upper())
        if pos >= 0:
            hits.append((alias, incis, pos))
    hits.sort(key=lambda t: (-len(t[0]), t[2]))
    return [(alias, incis) for alias, incis, _ in hits]
