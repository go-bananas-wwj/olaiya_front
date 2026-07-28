"""证据层级/强度分类：功效断言的结构化证据底座（总纲 I1/I3）。

规则（data/tools/backfill_evidence_level.py 与 evidence_loader 共用同一套），
按序命中即返回 —— 顺序即「保守优先」，弱证据类型并存时取更低层级：
1. note 含「口服」→ oral
2. note 含「动物/豚鼠/小鼠/大鼠」→ animal（豚鼠等即动物，不算猜）
3. note 含「体外」→ in_vitro
4. note 含「综述」→ review
5. evidence.type == regulation → regulation
6. note 含「消费者」→ human_ct
7. note 含「人体/双盲/RCT/临床」→ human_rct；但含「观察性」时否决（观察性研究非干预试验）
8. 以上皆未命中且为 paper → 用同一组关键词扫 excerpt；
   excerpt 中裸「人体」不算数（「人体皮肤外植体/人体细胞」是离体语境）
9. 仍无信号 → unknown（数据铁律：拿不准落 unknown，禁止猜测）
"""

from app.models.evidence import Evidence, EvidenceType

HUMAN_RCT = "human_rct"
HUMAN_CT = "human_ct"
IN_VITRO = "in_vitro"
ANIMAL = "animal"
ORAL = "oral"
REVIEW = "review"
REGULATION = "regulation"
UNKNOWN = "unknown"

EVIDENCE_LEVELS = (HUMAN_RCT, HUMAN_CT, IN_VITRO, ANIMAL, ORAL, REVIEW, REGULATION, UNKNOWN)

# 各层级的默认强度分（0-1）；新建/回填断言时按层级取默认值
DEFAULT_EVIDENCE_STRENGTH = {
    HUMAN_RCT: 1.0,
    HUMAN_CT: 0.8,
    IN_VITRO: 0.5,
    ANIMAL: 0.4,
    ORAL: 0.3,
    REVIEW: 0.35,
    REGULATION: 0.9,
    UNKNOWN: 0.2,
}

# 规则 1-4：弱证据降级关键词（note 与 excerpt 通用）
_WEAK_RULES = (
    (("口服",), ORAL),
    (("动物", "豚鼠", "小鼠", "大鼠"), ANIMAL),  # 豚鼠等即动物，不算猜
    (("体外",), IN_VITRO),
    (("综述",), REVIEW),
)
_HUMAN_CT_KW = ("消费者",)
# excerpt 语境刻意不含裸「人体」与「临床」：前者避免把离体（外植体/细胞）误判为人体试验，
# 后者避免把「开放/单臂临床试验」拔高为 RCT —— excerpt 只认强信号
_HUMAN_RCT_NOTE_KW = ("人体", "双盲", "RCT", "临床")
_HUMAN_RCT_EXCERPT_KW = ("双盲", "RCT", "随机对照", "随机分组")
_OBSERVATIONAL_VETO = "观察性"


def default_strength(level: str) -> float:
    return DEFAULT_EVIDENCE_STRENGTH[level]


def _match_weak(text: str | None) -> str | None:
    if not text:
        return None
    for keywords, level in _WEAK_RULES:
        if any(k in text for k in keywords):
            return level
    return None


def _match_human(text: str | None, human_rct_kw: tuple[str, ...]) -> str | None:
    if not text or _OBSERVATIONAL_VETO in text:
        return None
    if any(k in text for k in _HUMAN_CT_KW):
        return HUMAN_CT
    if any(k in text for k in human_rct_kw):
        return HUMAN_RCT
    return None


def classify_evidence_level(note: str | None, evidence: Evidence) -> str:
    """判定一条断言的证据层级；拿不准一律 unknown。"""
    level = _match_weak(note)  # 规则 1-4
    if level is not None:
        return level
    if evidence.type == EvidenceType.REGULATION:  # 规则 5
        return REGULATION
    level = _match_human(note, _HUMAN_RCT_NOTE_KW)  # 规则 6-7
    if level is not None:
        return level
    if evidence.type == EvidenceType.PAPER:  # 规则 8：excerpt 兜底
        level = _match_weak(evidence.excerpt) or _match_human(evidence.excerpt, _HUMAN_RCT_EXCERPT_KW)
        if level is not None:
            return level
    return UNKNOWN  # 规则 9
