"""efficacy 规范名映射：自由文本功效 → 有限功效族（总纲 I3 数据底座）。

断言的 efficacy 是自由文本（「美白」/「美白（抑制黑素小体转运）」/「美白提亮」…），
跨成分同功效无法对齐。canonicalize 按关键词规则归一到规范功效族，写入
EfficacyAssertion.efficacy_canonical（evidence_loader 新建断言时填充、
data/tools/backfill_efficacy_canonical.py 全量回填），功效指纹按规范族聚合。

规则按序命中即返回，顺序即优先级：
- 控油祛痘必须在舒缓之前：祛痘类断言常带「抗炎」字样（如「祛痘（抗菌抗炎）」），
  舒缓先命中会把痤疮功效错并入舒缓族；
- 均不命中落「其他」（与数据铁律同口径：不猜测细分类目）。
"""

# (规范名, 关键词组)，任一关键词为 efficacy 子串即命中
# 美白族含「黄褐斑」：黄褐斑即色素沉着宣称（「淡斑」意图的覆盖补全），
# 否则「淡化黄褐斑（…）」类断言会碎裂进「其他」
CANONICAL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("美白", ("美白", "提亮", "淡斑", "黄褐斑", "黑素", "酪氨酸酶")),
    ("控油祛痘", ("控油", "祛痘", "痤疮", "粉刺", "痘")),
    ("抗皱", ("抗皱", "抗老", "细纹", "皱纹", "胶原", "紧致", "光老化")),
    ("抗氧化", ("抗氧化", "光防护", "自由基", "抗氧")),
    ("保湿", ("保湿", "水合", "锁水")),
    ("修护", ("修护", "屏障", "修复")),
    ("舒缓", ("舒缓", "抗敏", "镇静", "抗炎", "消炎", "泛红")),
    ("焕肤", ("焕肤", "去角质", "剥脱", "换肤")),
    ("防腐", ("防腐",)),
)

OTHER = "其他"


def canonicalize(efficacy: str | None) -> str:
    """自由文本功效 → 规范功效族名；空值或均不命中返回「其他」。"""
    if not efficacy:
        return OTHER
    for canonical, keywords in CANONICAL_RULES:
        if any(k in efficacy for k in keywords):
            return canonical
    return OTHER
