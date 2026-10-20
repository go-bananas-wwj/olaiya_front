"""全库地图：真实覆盖、共享证据口径、缓存与投影失效。"""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main import app, get_db
from app.config import settings
from app.models.product import Product, ProductIngredient
from app.models.ingredient import Ingredient
from app.services.capability_profile import capability_profile, DIRECTIONS
from backend.tests.test_capability_profile import assertion


@pytest.fixture
def data(session):
    products = [Product(name=f'地图样本{i}', brand='测试品牌') for i in range(3)]
    ingredients = [Ingredient(inci_name=f'MAP-{i}', cn_name=f'成分{i}') for i in range(3)]
    session.add_all(products + ingredients); session.flush()
    for p in products[:2]:
        for i, ing in enumerate(ingredients):
            session.add(ProductIngredient(product_id=p.id, ingredient_id=ing.id, position=i+1))
    # A real duplicate link must not increase contributions.
    session.add(ProductIngredient(product_id=products[0].id, ingredient_id=ingredients[0].id, position=None))
    session.commit()
    a=assertion(session,ingredients[0],weight=.8)
    assertion(session,ingredients[0],weight=.5)
    assertion(session,ingredients[0],weight=.8)
    assertion(session,ingredients[1],weight=.8,source=a.evidence)
    assertion(session,ingredients[2],weight=0,efficacy='修护')
    assertion(session,ingredients[2],weight=.2,level='unknown',efficacy='抗皱')
    return products,ingredients


@pytest.fixture
def client(session,monkeypatch):
    # Each case uses isolated database and explicit missing-layout state.
    from app.services.product_space import reset_space_cache
    reset_space_cache()
    monkeypatch.setattr(settings,'product_space_layout_path','')
    monkeypatch.setattr(settings,'product_space_layout_sha256','')
    app.dependency_overrides[get_db]=lambda:session
    try:
        with TestClient(app) as c:yield c
    finally:
        app.dependency_overrides.clear();reset_space_cache()


def test_full_catalog_matches_individual_profiles_without_filling_unknown(client,session,data):
    products,_=data
    r=client.get('/api/product-space');assert r.status_code==200
    payload=r.json();assert payload['total']==3
    assert payload['directions']==list(DIRECTIONS)
    assert payload['method_version']=='evidence-index-v1'
    assert [p['id'] for p in payload['products']]==[p.id for p in products]
    for item in payload['products']:
        expected=capability_profile(session,item['id'])
        assert item['scores']==[d['score'] for d in expected['dimensions']]
        assert item['statuses']==[d['status'] for d in expected['dimensions']]
        assert item['ingredient_count']==expected['coverage']['ingredients_total']
        assert item['evidence_ingredient_count']==expected['coverage']['ingredients_scored']
        assert item['source_count']==expected['coverage']['sources_scored']
        assert item['coordinates'] is None
    a=payload['products'][0]
    assert a['scores'][0]==1.6 and a['scores'][2]==0
    assert a['scores'][1] is None and a['statuses'][1]=='unrated'
    assert a['scores'][3] is None and a['statuses'][3]=='no_evidence'
    assert payload['products'][2]['ingredient_count']==0
    assert all(v is None for v in payload['products'][2]['scores'])
    assert payload['projection']['status']=='unavailable'
    json.dumps(payload,allow_nan=False)


def test_fixed_query_count_etag_and_commit_invalidation(client,session,data):
    selects=[]
    engine=session.get_bind()
    def record(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'):selects.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    try:
        r=client.get('/api/product-space');assert r.status_code==200
        assert len(selects)<=4
        tag=r.headers['etag'];selects.clear()
        cached=client.get('/api/product-space',headers={'If-None-Match':tag})
        assert cached.status_code==304 and not cached.content
        assert len(selects)==0
        # Real write with the same row count must not retain an outdated document.
        data[0][0].name='更新后的真实名称';session.commit()
        changed=client.get('/api/product-space',headers={'If-None-Match':tag})
        assert changed.status_code==200 and changed.headers['etag']!=tag
        assert changed.json()['products'][0]['name']=='更新后的真实名称'
    finally:event.remove(engine,'before_cursor_execute',record)


def test_layout_is_pinned_and_old_or_missing_ids_never_invent_coordinates(client,session,data,tmp_path,monkeypatch):
    from app.services.product_space import catalog_signature
    products,_=data
    content={'version':'ingredient-umap-v1','catalog_signature':catalog_signature(session),
             'source_snapshot':settings.snapshot_revision,'input_dimensions':4096,
             'parameters':{'n_neighbors':30,'min_dist':.15,'random_state':417},
             'quality':{'neighbor_recall_10':.4},
             'points':[{'id':products[0].id,'x':1.,'y':2.},
                       {'id':products[1].id,'x':1.,'y':2.},
                       {'id':999999,'x':100.,'y':200.}]}
    path=tmp_path/'layout.json';path.write_text(json.dumps(content))
    monkeypatch.setattr(settings,'product_space_layout_path',str(path))
    monkeypatch.setattr(settings,'product_space_layout_sha256',hashlib.sha256(path.read_bytes()).hexdigest())
    r=client.get('/api/product-space');assert r.status_code==200
    d=r.json();assert d['coordinate_count']==2
    assert d['products'][0]['coordinates']==[1.,2.]
    assert d['products'][1]['coordinates']==[1.,2.]
    assert d['products'][2]['coordinates'] is None
    assert len(d['products'])==3
    # Corrupt or stale layout fails closed while raw dimensions remain usable.
    path.write_text(json.dumps({**content,'catalog_signature':'stale'}))
    r=client.get('/api/product-space');assert r.status_code==200
    assert r.json()['coordinate_count']==0
    assert r.json()['projection']['status']=='unavailable'
    assert r.json()['products'][0]['scores'][0]==1.6


def test_empty_catalog_has_no_fake_points(client):
    r=client.get('/api/product-space');assert r.status_code==200
    assert r.json()['total']==0 and r.json()['products']==[]


def test_cache_does_not_cross_databases(client,session,data,tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db import Base
    from app.services.product_space import product_space
    first=product_space(session)
    other=create_engine(f'sqlite:///{tmp_path}/other.db');Base.metadata.create_all(other)
    with Session(other) as s:
        s.add(Product(name='独立资料库',brand='其他品牌'));s.commit()
        assert product_space(s)['total']==1
        assert product_space(s)['products'][0]['name']=='独立资料库'
    assert first['total']==3
    other.dispose()


@pytest.mark.parametrize('bad', [None, [], 'invalid', {'quality':{'neighbor_recall_10':float('nan')}},
                               {'quality':[]}, {'parameters':[]}, {'input_dimensions':float('inf')},
                               {'points':[None]}])
def test_malformed_pinned_layout_degrades_only_the_projection(client,session,data,tmp_path,monkeypatch,bad):
    from app.services.product_space import catalog_signature
    content={'version':'ingredient-umap-v1','catalog_signature':catalog_signature(session),
             'source_snapshot':settings.snapshot_revision,'input_dimensions':4096,
             'parameters':{},'quality':{},'points':[]}
    value={**content,**bad} if isinstance(bad,dict) else bad
    path=tmp_path/'broken-layout.json';path.write_text(json.dumps(value))
    monkeypatch.setattr(settings,'product_space_layout_path',str(path))
    monkeypatch.setattr(settings,'product_space_layout_sha256',hashlib.sha256(path.read_bytes()).hexdigest())
    r=client.get('/api/product-space');assert r.status_code==200
    assert r.json()['projection']['status']=='unavailable'
    assert r.json()['total']==3 and r.json()['products'][0]['scores'][0]==1.6


def projector_bundle(session, products):
    from app.services.product_space import catalog_signature
    return {'version':'ingredient-projector-v2','catalog_signature':catalog_signature(session),
            'source_snapshot':settings.snapshot_revision,'input_dimensions':4096,
            'parameters':{'n_neighbors':15,'min_dist':.15,'random_state':417,'metric':'cosine'},
            'quality':{'neighbor_recall_10':.4},
            'umap_3d':{'status':'ready','dimensions':3,
                       'parameters':{'n_neighbors':15,'min_dist':.15,'random_state':417,'metric':'cosine'},
                       'quality':{'neighbor_recall_10':.5}},
            'pca':{'status':'ready','dimensions':3,'parameters':{'centered':True,'svd_solver':'full'},
                   'explained_variance_ratio':[.2,.1,.05],'quality':{'neighbor_recall_10':.3}},
            'points':[{'id':p.id,'x':1.,'y':2.,'umap3d':[1.,2.,3.],
                       'pca3d':[-.1,.2,0.]} for p in products[:2]]}


def pin_bundle(content,tmp_path,monkeypatch):
    path=tmp_path/'projector.json';path.write_text(json.dumps(content))
    monkeypatch.setattr(settings,'product_space_layout_path',str(path))
    monkeypatch.setattr(settings,'product_space_layout_sha256',hashlib.sha256(path.read_bytes()).hexdigest())


def test_projector_bundle_exposes_real_three_dimensional_spaces_without_changing_2d(client,session,data,tmp_path,monkeypatch):
    content=projector_bundle(session,data[0]);pin_bundle(content,tmp_path,monkeypatch)
    payload=client.get('/api/product-space').json()
    assert payload['coordinate_count']==payload['coordinate_count_3d']==payload['pca_coordinate_count']==2
    assert payload['projection']['artifact_version']=='ingredient-projector-v2'
    assert payload['projection']['method']=='ingredient-umap-v1'
    assert payload['projection']['umap_3d']['status']=='ready'
    assert payload['projection']['pca']['explained_variance_ratio']==[.2,.1,.05]
    for p in payload['products'][:2]:
        assert p['coordinates']==[1.,2.] and p['coordinates_3d']==[1.,2.,3.]
        assert p['pca_coordinates']==[-.1,.2,0.]
        assert p['scores'][0]==1.6
    assert payload['products'][2]['coordinates_3d'] is None
    assert payload['products'][2]['pca_coordinates'] is None


@pytest.mark.parametrize('space,key,bad',[
    ('umap_3d','umap3d',[1.,2.]),('umap_3d','umap3d',[1.,2.,float('nan')]),
    ('umap_3d','umap3d',[1.,2.,10**400]),('umap_3d','umap3d',[1.,2.,True]),
    ('pca','pca3d','not-a-vector'),('pca','pca3d',[1.,None,2.]),
])
def test_bad_optional_3d_space_preserves_other_spaces_and_evidence(client,session,data,tmp_path,monkeypatch,space,key,bad):
    content=projector_bundle(session,data[0]);content['points'][0][key]=bad
    pin_bundle(content,tmp_path,monkeypatch)
    response=client.get('/api/product-space');assert response.status_code==200
    payload=response.json();assert payload['projection']['status']=='ready'
    assert payload['projection'][space]['status']=='unavailable'
    assert payload['products'][0]['coordinates']==[1.,2.] and payload['products'][0]['scores'][0]==1.6
    field='coordinates_3d' if space=='umap_3d' else 'pca_coordinates'
    other='pca_coordinates' if space=='umap_3d' else 'coordinates_3d'
    assert all(p[field] is None for p in payload['products'])
    assert payload['products'][0][other] is not None


@pytest.mark.parametrize('bad',[None,[],[.2,.1],[.2,.1,float('nan')],[.8,.8,.1],[-.1,.2,.1]])
def test_pca_requires_finite_explained_variance_without_hiding_umap(client,session,data,tmp_path,monkeypatch,bad):
    content=projector_bundle(session,data[0]);content['pca']['explained_variance_ratio']=bad
    pin_bundle(content,tmp_path,monkeypatch)
    response=client.get('/api/product-space');assert response.status_code==200
    payload=response.json();assert payload['projection']['umap_3d']['status']=='ready'
    assert payload['projection']['pca']['status']=='unavailable'
    assert payload['products'][0]['coordinates_3d']==[1.,2.,3.]


def test_legacy_layout_cannot_claim_three_dimensional_coordinates(client,session,data,tmp_path,monkeypatch):
    content=projector_bundle(session,data[0]);content['version']='ingredient-umap-v1'
    pin_bundle(content,tmp_path,monkeypatch)
    payload=client.get('/api/product-space').json()
    assert payload['projection']['status']=='ready'
    assert payload['projection']['umap_3d']['status']==payload['projection']['pca']['status']=='unavailable'
    assert payload['coordinate_count_3d']==payload['pca_coordinate_count']==0
    assert all(p['coordinates_3d'] is None and p['pca_coordinates'] is None for p in payload['products'])


def test_projection_exposes_index_identity_for_bound_family_colours(client,session,data,tmp_path,monkeypatch):
    content=projector_bundle(session,data[0]);content['source_index_sha256']='a'*64
    pin_bundle(content,tmp_path,monkeypatch)
    assert client.get('/api/product-space').json()['projection']['source_index_sha256']=='a'*64
