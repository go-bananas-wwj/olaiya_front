"""Evidence-space geometry is complete-case, scaled, pinned, and separate from semantics."""
import copy
import json

import pytest

from app.config import settings
from app.services.capability_profile import DIRECTIONS
from backend.tests.test_product_space import client, data, pin_bundle, projector_bundle


def sample():
    scores = [[0] * 8, [1, 2, 0, 0, 0, 0, 0, 0], [2, 4, 0, 0, 0, 0, 0, 0], [None] + [0] * 7]
    return {'total': 4, 'products': [dict(id=i + 1, name=f'样本{i}', brand='测试', scores=s,
            statuses=['scored' if v is not None else 'no_evidence' for v in s]) for i, s in enumerate(scores)],
            'directions': list(DIRECTIONS), 'snapshot_revision': 'snapshot', 'catalog_signature': 'catalog'}


def test_scaled_rms_uses_same_eight_axes_and_never_imputes_missing():
    from app.services.evidence_space import evidence_space_neighbors, evidence_geometry
    raw = sample(); geometry = evidence_geometry(raw)
    assert geometry['scales'] == [2, 4, 1, 1, 1, 1, 1, 1]
    assert geometry['eligible_ids'] == [1, 2, 3]
    result = evidence_space_neighbors(raw, 1, 100)
    assert result['metric'] == 'scaled-rms' and result['available']
    assert [p['id'] for p in result['items']] == [2, 3]
    assert result['items'][0]['distance'] == .25
    assert result['items'][1]['distance'] == .5
    assert result['compared_directions'] == list(DIRECTIONS)
    missing = evidence_space_neighbors(raw, 4)
    assert not missing['available'] and missing['items'] == []
    assert missing['missing_directions'] == ['保湿']
    with pytest.raises(KeyError): evidence_space_neighbors(raw, 999)


def test_scales_use_scored_whole_catalog_and_unrated_value_is_not_a_zero():
    from app.services.evidence_space import evidence_geometry
    raw = sample(); raw['products'][3]['scores'][1] = 8
    assert evidence_geometry(raw)['scales'][1] == 8  # partial records still set whole-catalog scale
    raw['products'][3]['statuses'][1] = 'unrated'
    assert evidence_geometry(raw)['scales'][1] == 4
    raw['products'][0]['statuses'][0] = 'unrated'
    assert evidence_geometry(raw)['eligible_ids'] == [2, 3]


def test_evidence_endpoint_retains_missing_products_without_semantic_coordinates(client, session, data):
    response = client.get('/api/product-space/evidence')
    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == payload['excluded_count'] == 3
    assert payload['eligible_count'] == 0 and len(payload['products']) == 3
    assert payload['method_version'] == 'evidence-space-v1'
    assert payload['index_method'] == 'evidence-index-v1'
    assert payload['metric'] == 'scaled-rms'
    assert payload['projection']['status'] == 'unavailable'
    for row in payload['products']:
        assert not row['eligible'] and row['missing_directions']
        assert row['coordinates'] is row['coordinates_3d'] is row['pca_coordinates'] is None
    assert response.headers['etag']
    assert client.get('/api/product-space/evidence', headers={'If-None-Match':response.headers['etag']}).status_code == 304
    neighbors = client.get(f'/api/products/{data[0][0].id}/evidence-space-neighbors?limit=100')
    assert neighbors.status_code == 200 and not neighbors.json()['available']
    assert client.get('/api/products/999999/evidence-space-neighbors').status_code == 404
    assert client.get('/api/products/1/evidence-space-neighbors?limit=101').status_code == 422


def test_pinned_evidence_layout_validates_profile_and_keeps_semantic_spaces(client, session, data, tmp_path, monkeypatch):
    from app.services.evidence_space import evidence_profile_signature, evidence_geometry
    from app.services.product_space import product_space
    raw = product_space(session)
    content = projector_bundle(session, data[0]); content['version'] = 'ingredient-projector-v3'
    content['evidence_space'] = {'method_version':'evidence-space-v1', 'index_method':'evidence-index-v1',
        'metric':'scaled-rms', 'directions':list(DIRECTIONS), 'scales':evidence_geometry(raw)['scales'],
        'profile_signature':evidence_profile_signature(raw),
        'projection':{'status':'ready', 'method':'pca', 'dimensions':3, 'input_dimensions':8,
            'parameters':{'centered':True, 'svd_solver':'full'}, 'explained_variance_ratio':[0,0,0]}, 'points':[]}
    pin_bundle(content, tmp_path, monkeypatch)
    semantic = client.get('/api/product-space').json()
    assert semantic['coordinate_count_3d'] == 2 and semantic['pca_coordinate_count'] == 2
    payload = client.get('/api/product-space/evidence').json()
    assert payload['projection']['status'] == 'ready'
    content['evidence_space']['profile_signature'] = 'stale'; pin_bundle(content, tmp_path, monkeypatch)
    assert client.get('/api/product-space/evidence').json()['projection']['status'] == 'unavailable'
    assert client.get('/api/product-space').json()['coordinate_count_3d'] == 2


def test_evidence_projection_bundle_is_offline_and_exact_duplicate_profiles_coincide():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('evidence_builder', Path(__file__).resolve().parents[2] / 'data/tools/build_evidence_space.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    raw = sample(); raw['products'].append({**copy.deepcopy(raw['products'][1]), 'id':5})
    bundle = builder.build_evidence_bundle(raw)
    assert len(bundle['points']) == 4
    by_id = {row['id']:row['pca3d'] for row in bundle['points']}
    assert by_id[2] == by_id[5]
    assert 4 not in by_id
    assert len(bundle['projection']['explained_variance_ratio']) == 3
    assert sum(bundle['projection']['explained_variance_ratio']) == pytest.approx(1)
    assert bundle['scales'] == [2,4,1,1,1,1,1,1]
    json.dumps(bundle,allow_nan=False)


def complete_bundle(session, data):
    import importlib.util
    from pathlib import Path
    from app.services.product_space import product_space, reset_space_cache
    from backend.tests.test_capability_profile import assertion
    from app.services.capability_profile import DIRECTIONS
    for family in DIRECTIONS:
        assertion(session, data[1][0], weight=.3, efficacy=family)
    reset_space_cache()
    raw = product_space(session)
    spec = importlib.util.spec_from_file_location('evidence_builder_full', Path(__file__).resolve().parents[2] / 'data/tools/build_evidence_space.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    content = projector_bundle(session, data[0]); content['version'] = 'ingredient-projector-v3'
    content['evidence_space'] = builder.build_evidence_bundle(raw)
    return content


def test_nonempty_projection_and_neighbor_ids_are_complete_case_and_self_excluding(client,session,data,tmp_path,monkeypatch):
    content = complete_bundle(session,data); pin_bundle(content,tmp_path,monkeypatch)
    payload = client.get('/api/product-space/evidence').json()
    assert payload['eligible_count'] == payload['coordinate_count'] == 2
    assert payload['excluded_count'] == 1
    for row in payload['products'][:2]:
        assert row['eligible'] and row['missing_directions'] == []
        assert row['coordinates'] == row['pca_coordinates'][:2]
        assert row['coordinates_3d'] == row['pca_coordinates']
    assert payload['products'][0]['pca_coordinates'] == payload['products'][1]['pca_coordinates']
    assert payload['products'][2]['coordinates'] is None
    pid = data[0][0].id
    result = client.get(f'/api/products/{pid}/evidence-space-neighbors?limit=100').json()
    assert result['available'] and result['candidate_count'] == 1
    assert result['items'][0]['id'] == data[0][1].id and result['items'][0]['distance'] == 0
    # Eight-direction scoring changes invalidate only the evidence projection.
    from backend.tests.test_capability_profile import assertion
    from app.services.product_space import reset_space_cache
    assertion(session,data[1][0],weight=1,efficacy='美白'); reset_space_cache()
    changed = client.get('/api/product-space/evidence').json()
    assert changed['eligible_count'] == 2 and changed['coordinate_count'] == 0
    assert changed['projection']['status'] == 'unavailable'
    assert client.get('/api/product-space').json()['coordinate_count_3d'] == 2


@pytest.mark.parametrize('bad', ['extra-id','duplicate-id','missing-id','nan','bool','wrong-length','scales','method','variance','snapshot','hash'])
def test_malformed_evidence_bundle_degrades_only_evidence_projection(client,session,data,tmp_path,monkeypatch,bad):
    content = complete_bundle(session,data); evidence = content['evidence_space']
    if bad == 'extra-id': evidence['points'].append({'id':999999,'pca3d':[1,2,3]})
    elif bad == 'duplicate-id': evidence['points'].append(evidence['points'][0])
    elif bad == 'missing-id': evidence['points'].pop()
    elif bad == 'nan': evidence['points'][0]['pca3d'][0] = float('nan')
    elif bad == 'bool': evidence['points'][0]['pca3d'][0] = True
    elif bad == 'wrong-length': evidence['points'][0]['pca3d'] = [1,2]
    elif bad == 'scales': evidence['scales'][0] += 1
    elif bad == 'method': evidence['method_version'] = 'unversioned'
    elif bad == 'variance': evidence['projection']['explained_variance_ratio'] = [.5,.8,.5]
    elif bad == 'snapshot': content['source_snapshot'] = 'stale'
    pin_bundle(content,tmp_path,monkeypatch)
    if bad == 'hash': monkeypatch.setattr(settings,'product_space_layout_sha256','wrong')
    payload = client.get('/api/product-space/evidence').json()
    assert payload['eligible_count'] == 2 and payload['coordinate_count'] == 0
    assert payload['projection']['status'] == 'unavailable'
    assert all(p['coordinates'] is p['pca_coordinates'] is None for p in payload['products'])
    if bad not in ('hash','snapshot'):
        assert client.get('/api/product-space').json()['coordinate_count_3d'] == 2


def test_empty_and_singleton_pca_remain_finite_without_fabricated_missing_points():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('evidence_builder_degenerate', Path(__file__).resolve().parents[2] / 'data/tools/build_evidence_space.py')
    builder = importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    raw = sample();raw['products'] = raw['products'][-1:]
    assert builder.build_evidence_bundle(raw)['points'] == []
    raw['products'] = sample()['products'][:1]
    bundle = builder.build_evidence_bundle(raw)
    assert bundle['points'] == [{'id':1,'pca3d':[0,0,0]}]
    assert bundle['projection']['explained_variance_ratio'] == [0,0,0]
