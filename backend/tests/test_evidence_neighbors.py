"""Reference-based evidence neighbors never impute missing dimensions."""
import pytest
from fastapi.testclient import TestClient
from app.main import app, get_db
from backend.tests.test_product_space import data as space_data


def product(pid,scores):
    return {'id':pid,'name':str(pid),'scores':scores,'statuses':['scored' if x is not None else 'no_evidence' for x in scores]}


def test_fixed_reference_basis_no_unknown_imputation_and_true_zero():
    from app.services.product_space import evidence_neighbors
    products=[product(1,[1.,2.,0.,None]),product(2,[1.,2.,0.,None]),
              product(3,[1.,None,0.,3.]),product(4,[1.1,2.1,0.,4.]),product(5,[4.,4.,1.,None])]
    data={'directions':['保湿','抗皱','修护','抗氧化'],'products':products}
    result=evidence_neighbors(data,1,3)
    assert result['available'] and result['method_version']=='evidence-neighbors-v1'
    assert result['compared_directions']==['保湿','抗皱','修护']
    assert [i['id'] for i in result['items']]==[2,4,5]
    assert result['items'][0]['distance']==0
    assert 3 not in [i['id'] for i in result['items']]
    assert result['items'][0]['scores'][2]==0


def test_sparse_reference_does_not_claim_a_shape():
    from app.services.product_space import evidence_neighbors
    d={'directions':['保湿','抗皱','修护'],'products':[product(1,[1,None,None]),product(2,[1,1,1])]}
    r=evidence_neighbors(d,1,3)
    assert not r['available'] and r['items']==[] and r['reason']


def test_neighbor_ties_are_stable_and_missing_id_is_clear():
    from app.services.product_space import evidence_neighbors
    d={'directions':['保湿','抗皱','修护'],'products':[product(3,[1,1,1]),product(1,[1,1,1]),product(2,[1,1,1])]}
    assert [p['id'] for p in evidence_neighbors(d,3,2)['items']]==[1,2]
    with pytest.raises(KeyError):evidence_neighbors(d,999,3)


def test_all_zero_reference_and_insufficient_candidates_are_explicit():
    from app.services.product_space import evidence_neighbors
    zero={'directions':['保湿','抗皱','修护'],'products':[product(1,[0,0,0]),product(2,[0,0,0])]}
    assert not evidence_neighbors(zero,1)['available']
    empty={'directions':['保湿','抗皱','修护'],'products':[product(1,[1,1,1]),product(2,[1,None,1])]}
    result=evidence_neighbors(empty,1)
    assert result['available'] and result['candidate_count']==0 and result['items']==[]


def test_unrated_numeric_field_cannot_enter_known_basis_or_candidate():
    from app.services.product_space import evidence_neighbors
    a=product(1,[1,1,1]);b=product(2,[1,1,1]);b['statuses'][1]='unrated'
    d={'directions':['保湿','抗皱','修护'],'products':[a,b]}
    assert evidence_neighbors(d,1)['items']==[]
    a['statuses'][1]='unrated'
    assert not evidence_neighbors(d,1)['available']


def test_neighbor_http_limits_not_found_and_sparse_state(session,space_data):
    from app.services.product_space import reset_space_cache
    reset_space_cache();app.dependency_overrides[get_db]=lambda:session
    try:
        with TestClient(app) as client:
            pid=space_data[0][0].id
            r=client.get(f'/api/products/{pid}/space-neighbors');assert r.status_code==200
            assert not r.json()['available'] and r.json()['reason']
            assert client.get('/api/products/999999/space-neighbors').status_code==404
            assert client.get(f'/api/products/{pid}/space-neighbors?limit=0').status_code==422
            assert client.get(f'/api/products/{pid}/space-neighbors?limit=13').status_code==422
    finally:
        app.dependency_overrides.clear();reset_space_cache()
