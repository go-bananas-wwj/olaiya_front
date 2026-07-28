"""证据层级/强度分类：功效断言的结构化证据底座（总纲 I1/I3）。

规则（data/tools/backfill_evidence_level.py 与 evidence_loader 共用同一套），
按序命中即返回 —— 顺序即「保守优先」，弱证据类型并存时取更低层级：
1. note 含「口服」→ oral
2. note 含「综述」→ review
3. note 含「动物/豚鼠/小鼠/大鼠」→ animal（豚鼠等即动物，不算猜）
4. note 含「体外」→ in_vitro（「人体外用」除外：那里「体外」只是子串假象）
5. evidence.type == regulation → regulation
6. note 含「消费者」→ human_ct
7. note 含人体信号时按研究设计分级（含「观察性」一律否决：观察性研究非干预试验）：
   含「开放/无对照/病例系列」→ human_open（开放设计不得拔高为 RCT）；
   含「双盲/RCT/随机」强信号 → human_rct；
   仅含「人体/临床」弱信号 → human_open（无随机对照设计字样，最多算开放试验）
8. 以上皆未命中且为 paper → 用同一组关键词扫 excerpt；
   excerpt 只认 RCT 强信号，裸「人体/临床」不算数（「人体皮肤外植体/人体细胞」
   是离体语境，「开放/单臂临床试验」摘要字样也不拔高）
9. 仍无信号 → unknown（数据铁律：拿不准落 unknown，禁止猜测）
"""

import re

from app.models.evidence import Evidence, EvidenceType

HUMAN_RCT = "human_rct"
HUMAN_CT = "human_ct"
HUMAN_OPEN = "human_open"
IN_VITRO = "in_vitro"
ANIMAL = "animal"
ORAL = "oral"
REVIEW = "review"
REGULATION = "regulation"
UNKNOWN = "unknown"

EVIDENCE_LEVELS = (HUMAN_RCT, HUMAN_CT, HUMAN_OPEN, IN_VITRO, ANIMAL, ORAL, REVIEW, REGULATION, UNKNOWN)

# 各层级的默认强度分（0-1）；新建/回填断言时按层级取默认值
DEFAULT_EVIDENCE_STRENGTH = {
    HUMAN_RCT: 1.0,
    HUMAN_CT: 0.8,
    HUMAN_OPEN: 0.55,
    IN_VITRO: 0.5,
    ANIMAL: 0.4,
    ORAL: 0.3,
    REVIEW: 0.35,
    REGULATION: 0.9,
    UNKNOWN: 0.2,
}

# 规则 1-4：弱证据降级关键词（note 与 excerpt 通用）
_WEAK_RULES = (
    (re.compile("口服"), ORAL),
    (re.compile("综述"), REVIEW),
    (re.compile("动物|豚鼠|小鼠|大鼠"), ANIMAL),  # 豚鼠等即动物，不算猜
    (re.compile(r"(?<!人)体外"), IN_VITRO),  # 「人体外用」是外用语境，非体外实验
)
_HUMAN_CT_KW = ("消费者",)
# RCT 强信号（随机对照设计字样）。note 侧与 excerpt 侧都刻意不含裸「人体」：
# 避免把离体语境（外植体/细胞）误判为人体试验
_HUMAN_RCT_NOTE_KW = ("双盲", "RCT", "随机")
_HUMAN_RCT_EXCERPT_KW = ("双盲", "RCT", "随机对照", "随机分组")
# note 侧弱人体信号：仅命中而无强信号时最多算 human_open，不拔高为 RCT
_HUMAN_OPEN_KW = ("人体", "临床")
# 开放设计否决词：命中即归 human_open 而非 human_rct —— 与「观察性」否决并列，
# 但开放试验尚有信号，归 human_open 而非 unknown
_HUMAN_OPEN_VETO = ("开放", "无对照", "病例系列")
_OBSERVATIONAL_VETO = "观察性"


def default_strength(level: str) -> float:
    return DEFAULT_EVIDENCE_STRENGTH[level]


def _match_weak(text: str | None) -> str | None:
    if not text:
        return None
    for pattern, level in _WEAK_RULES:
        if pattern.search(text):
            return level
    return None


def _match_human_note(text: str | None) -> str | None:
    """note 侧人体信号分级：消费者测试 / 开放试验 / RCT；观察性一律否决。"""
    if not text or _OBSERVATIONAL_VETO in text:
        return None
    if any(k in text for k in _HUMAN_CT_KW):
        return HUMAN_CT
    has_rct_signal = any(k in text for k in _HUMAN_RCT_NOTE_KW)
    has_open_signal = any(k in text for k in _HUMAN_OPEN_KW)
    if not (has_rct_signal or has_open_signal):
        return None
    if has_rct_signal and not any(k in text for k in _HUMAN_OPEN_VETO):
        return HUMAN_RCT
    return HUMAN_OPEN


def _match_human_excerpt(text: str | None) -> str | None:
    """excerpt 侧只认强信号：开放/单臂临床字样不拔高，弱信号直接放过。"""
    if not text or _OBSERVATIONAL_VETO in text:
        return None
    if any(k in text for k in _HUMAN_CT_KW):
        return HUMAN_CT
    if any(k in text for k in _HUMAN_RCT_EXCERPT_KW):
        return HUMAN_RCT
    return None


def classify_evidence_level(note: str | None, evidence: Evidence) -> str:
    """判定一条断言的证据层级；拿不准一律 unknown。"""
    level = _match_weak(note)  # 规则 1-4
    if level is not None:
        return level
    if evidence.type == EvidenceType.REGULATION:  # 规则 5
        return REGULATION
    level = _match_human_note(note)  # 规则 6-7
    if level is not None:
        return level
    if evidence.type == EvidenceType.PAPER:  # 规则 8：excerpt 兜底
        level = _match_weak(evidence.excerpt) or _match_human_excerpt(evidence.excerpt)
        if level is not None:
            return level
    return UNKNOWN  # 规则 9
