from app.models.evidence import Evidence, EvidenceType


def test_create_paper_evidence(session):
    e = Evidence(
        type=EvidenceType.PAPER,
        title="Improvement of naturally aged skin with vitamin A (retinol)",
        source="Archives of Dermatology, 2007;143(5):606-612",
        year=2007,
        url="https://pubmed.ncbi.nlm.nih.gov/17515510/",
        excerpt="Topical 0.4% retinol improved fine wrinkling.",
    )
    session.add(e)
    session.commit()
    got = session.query(Evidence).filter_by(title=e.title).one()
    assert got.type == EvidenceType.PAPER
    assert got.year == 2007


def test_all_evidence_types(session):
    """每个枚举值都能入库（含 database 官方数据库词表类型）。"""
    for t in EvidenceType:
        session.add(Evidence(type=t, title=f"t-{t.value}", source="s"))
    session.commit()
    assert session.query(Evidence).count() == len(EvidenceType)
    assert "database" in {t.value for t in EvidenceType}
