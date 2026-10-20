import pytest

def test_append_only_catalog_rebind_preserves_coordinates_and_refuses_changed_old_formula():
    from data.tools.rebind_product_space import rebind
    base={'points':[{'id':1,'x':.2,'y':.3}],'catalog_signature':'old','source_snapshot':'old','version':'ingredient-projector-v3'}
    out=rebind(base,[1],[(1,2,None)],[1,3],[(1,2,None),(3,4,None)],'new','revision')
    assert out['points']==base['points'] and out['source_snapshot']=='revision'
    assert out['unplaced_product_ids']==[3] and base['source_snapshot']=='old'
    with pytest.raises(ValueError,match='changed'):
        rebind(base,[1],[(1,2,None)],[1,3],[(1,5,None)],'new','revision')
