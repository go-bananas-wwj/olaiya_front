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


def test_all_four_evidence_types(session):
    for t in EvidenceType:
        session.add(Evidence(type=t, title=f"t-{t.value}", source="s"))
    session.commit()
    assert session.query(Evidence).count() == 4
