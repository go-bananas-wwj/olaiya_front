"""Whole-catalog summaries and optional pinned, offline ingredient-layout coordinates.

No imputation, per-product SQL, model calls, or fitting in HTTP requests. The
existing evidence-index rules are shared with the full provenance endpoint.
"""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..config import settings
from ..models.product import Product, ProductIngredient
from ..models.ingredient import EfficacyAssertion
from .capability_profile import DIRECTIONS, METHOD_VERSION, INDEX_NOTE, index_sum, select_index_assertions
from .selection_catalog import verified_items
from .comparison_metadata import matching_price_points, price_fields

_CACHE = {}
_LOCK = threading.RLock()
_TTL = 60


def reset_space_cache():
    with _LOCK:
        _CACHE.clear()


def _file_stamp(path):
    try:
        s = Path(path).stat()
        return (s.st_mtime_ns, s.st_size)
    except (OSError, ValueError):
        return None


def _cache_key(session):
    bind = session.get_bind()
    engine = getattr(bind, 'engine', bind)
    url = engine.url
    files = ()
    if url.get_backend_name() == 'sqlite' and url.database not in (None, '', ':memory:'):
        path = str(Path(url.database).resolve())
        files = (path, _file_stamp(path), _file_stamp(path + '-wal'))
    return (id(engine), files, settings.snapshot_revision,
            settings.product_space_layout_path, _file_stamp(settings.product_space_layout_path),
            settings.product_space_layout_sha256, settings.selection_catalog_path, _file_stamp(settings.selection_catalog_path))


def _signature(products, links):
    # The layout is tied to the exact product/ingredient/order universe; labels
    # may be corrected without inventing new geometric relationships.
    source = [[p.id for p in products], [list(row) for row in links]]
    return hashlib.sha256(json.dumps(source, separators=(',', ':')).encode()).hexdigest()


def _links(session):
    return session.execute(select(ProductIngredient.product_id, ProductIngredient.ingredient_id,
                                  ProductIngredient.position).order_by(ProductIngredient.id)).all()


def catalog_signature(session):
    return _signature(session.execute(select(Product).order_by(Product.id)).scalars().all(), _links(session))


def _number(value, low=-1e6, high=1e6):
    # Check bounds before isfinite: enormous JSON integers must not overflow float.
    return type(value) in (int, float) and low <= value <= high and math.isfinite(value)


def _space_metadata(value, pca=False):
    if not isinstance(value, dict) or value.get('status') != 'ready' or value.get('dimensions') != 3:
        return None
    parameters, quality = value.get('parameters'), value.get('quality')
    if not isinstance(parameters, dict) or not isinstance(quality, dict):
        return None
    if any(k in quality and not _number(quality[k], 0, 1) for k in ('neighbor_recall_10', 'trustworthiness')):
        return None
    if 'sample_size' in quality and (type(quality['sample_size']) is not int or quality['sample_size'] < 0):
        return None
    meta = {'status':'ready', 'dimensions':3,
            'quality':{k:quality[k] for k in ('neighbor_recall_10','trustworthiness','sample_size') if k in quality}}
    if pca:
        ratios = value.get('explained_variance_ratio')
        if not isinstance(ratios, list) or len(ratios) != 3 or not all(_number(v, 0, 1) for v in ratios) or sum(ratios) > 1.000001:
            return None
        if parameters.get('centered') is not True or parameters.get('svd_solver') != 'full':
            return None
        meta.update(explained_variance_ratio=ratios, parameters={'centered':True,'svd_solver':'full'})
    else:
        if any(type(parameters.get(k)) is not int or parameters[k] < 0 for k in ('n_neighbors','random_state')):
            return None
        if not _number(parameters.get('min_dist'),0,1) or parameters.get('metric') != 'cosine':
            return None
        meta['parameters']={k:parameters[k] for k in ('n_neighbors','random_state','min_dist','metric')}
    return meta


def _optional_space(data, product_ids, key, point_key, pca=False):
    unavailable = {'status':'unavailable', 'dimensions':3}
    if data['version'] not in ('ingredient-projector-v2', 'ingredient-projector-v3'):
        return {}, unavailable
    meta = _space_metadata(data.get(key), pca=pca)
    if meta is None:
        return {}, unavailable
    coordinates = {}
    for row in data['points']:
        vector = row.get(point_key)
        if vector is None:
            continue
        if not isinstance(vector, list) or len(vector) != 3 or not all(_number(v) for v in vector):
            return {}, unavailable
        if row['id'] in product_ids:
            coordinates[row['id']] = vector
    if not coordinates:
        return {}, unavailable
    return coordinates, meta


def _layout(signature, product_ids):
    unavailable = {'status': 'unavailable', 'method': None,
                   'umap_3d':{'status':'unavailable','dimensions':3}, 'pca':{'status':'unavailable','dimensions':3},
                   'note': '成分投影未配置或未通过校验；仍可按原始证据维度查看全库。'}
    path, expected = settings.product_space_layout_path, settings.product_space_layout_sha256
    if not path or not expected:
        return {}, {}, {}, unavailable
    try:
        if Path(path).stat().st_size > 4_000_000:
            return {}, {}, {}, unavailable
        raw = Path(path).read_bytes()
        if len(raw) > 4_000_000 or hashlib.sha256(raw).hexdigest() != expected:
            return {}, {}, {}, unavailable
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}, {}, {}, unavailable
        if data.get('version') not in ('ingredient-umap-v1', 'ingredient-projector-v2', 'ingredient-projector-v3') or data.get('catalog_signature') != signature:
            return {}, {}, {}, unavailable
        if data.get('source_snapshot') != settings.snapshot_revision:
            return {}, {}, {}, unavailable
        parameters, quality = data.get('parameters', {}), data.get('quality', {})
        if not isinstance(parameters, dict) or not isinstance(quality, dict) or not isinstance(data.get('points'), list):
            return {}, {}, {}, unavailable
        dimension = data.get('input_dimensions')
        if type(dimension) is not int or not 1 <= dimension <= 100000:
            return {}, {}, {}, unavailable
        for field in ('neighbor_recall_10', 'trustworthiness'):
            if field in quality and (type(quality[field]) not in (int, float) or not math.isfinite(quality[field]) or not 0 <= quality[field] <= 1):
                return {}, {}, {}, unavailable
        if 'sample_size' in quality and (type(quality['sample_size']) is not int or quality['sample_size'] < 0):
            return {}, {}, {}, unavailable
        for field in ('n_neighbors', 'random_state'):
            if field in parameters and (type(parameters[field]) is not int or parameters[field] < 0):
                return {}, {}, {}, unavailable
        if 'min_dist' in parameters and (type(parameters['min_dist']) not in (int, float) or not math.isfinite(parameters['min_dist']) or not 0 <= parameters['min_dist'] <= 1):
            return {}, {}, {}, unavailable
        if 'metric' in parameters and parameters['metric'] != 'cosine':
            return {}, {}, {}, unavailable
        coordinates = {}
        seen = set()
        for row in data['points']:
            if not isinstance(row, dict):
                return {}, {}, {}, unavailable
            pid, x, y = row['id'], row['x'], row['y']
            if type(pid) is not int or pid in seen or not all(_number(v) for v in (x, y)):
                return {}, {}, {}, unavailable
            seen.add(pid)
            if pid in product_ids:
                coordinates[pid] = [x, y]
        umap3d, umap_meta = _optional_space(data, product_ids, 'umap_3d', 'umap3d')
        pca3d, pca_meta = _optional_space(data, product_ids, 'pca', 'pca3d', pca=True)
        return coordinates, umap3d, pca3d, {
            'status': 'ready', 'method': 'ingredient-umap-v1',
            'artifact_version':data['version'], 'umap_3d':umap_meta, 'pca':pca_meta,
            'input_dimensions': data.get('input_dimensions'),
            'parameters': {k: parameters[k] for k in ('n_neighbors', 'min_dist', 'random_state', 'metric') if k in parameters},
            'quality': {k: quality[k] for k in ('neighbor_recall_10', 'sample_size', 'trustworthiness') if k in quality},
            'note': '成分表语义的二维投影，只用于探索；距离、方向与群落大小不代表配比、功效或质量。相似候选按原始向量核验。',
        }
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return {}, {}, {}, unavailable


def product_space(session):
    key = _cache_key(session)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _TTL:
            return cached[1]
        # Fixed four SELECTs, including latest matching price provenance.
        products = session.execute(select(Product).order_by(Product.id)).scalars().all()
        links = _links(session)
        assertions = session.query(EfficacyAssertion).options(joinedload(EfficacyAssertion.evidence)).order_by(EfficacyAssertion.id).all()
        prices = matching_price_points(session, [p.id for p in products])
        signature = _signature(products, links)
        coordinates, coordinates3d, pca_coordinates, projection = _layout(signature, {p.id for p in products})
        selected, _, unrated = select_index_assertions(assertions)
        by_ingredient = defaultdict(list)
        for (iid, family), assertion in selected.items():
            by_ingredient[iid].append((family, assertion))
        ingredients = defaultdict(set)
        for pid, iid, _ in links:
            ingredients[pid].add(iid)
        items = []
        verified = verified_items(products)
        for p in products:
            ids = ingredients[p.id]
            families = defaultdict(list)
            scored_ids, source_ids = set(), set()
            for iid in ids:
                for family, a in by_ingredient[iid]:
                    families[family].append(a)
                    scored_ids.add(iid); source_ids.add(a.evidence_id)
            scores = [index_sum(a.evidence_strength for a in families[f]) if families[f] else None for f in DIRECTIONS]
            statuses = ['scored' if families[f] else ('unrated' if any(unrated[(iid, f)] for iid in ids) else 'no_evidence') for f in DIRECTIONS]
            price = price_fields(p, prices.get(p.id))
            if price['price_current'] is not None and (not math.isfinite(price['price_current']) or price['price_current'] < 0):
                price['price_current'] = None
            items.append({'id': p.id, 'name': p.name, 'brand': p.brand, 'nmpa_id': p.nmpa_id,
                          'category':p.category,'category_verified':p.id in verified,'selection_sample':p.id in verified,
                          'ingredient_list_status':verified.get(p.id,{}).get('ingredient_list_status','existing_record'),
                          'scores': scores, 'statuses': statuses, 'ingredient_count': len(ids),
                          'evidence_ingredient_count': len(scored_ids), 'source_count': len(source_ids),
                          'coordinates': coordinates.get(p.id), 'coordinates_3d':coordinates3d.get(p.id),
                          'pca_coordinates':pca_coordinates.get(p.id), **price})
        payload = {'total': len(items), 'directions': list(DIRECTIONS), 'method_version': METHOD_VERSION,
                   'snapshot_revision': settings.snapshot_revision, 'catalog_signature': signature,
                   'coordinate_count': len(coordinates), 'coordinate_count_3d':len(coordinates3d),
                   'pca_coordinate_count':len(pca_coordinates), 'projection': projection,
                   'note': INDEX_NOTE, 'products': items}
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        payload['revision'] = hashlib.sha256(encoded).hexdigest()
        # Bound cache growth when tests or local tools use multiple engines/revisions.
        _CACHE.clear()
        _CACHE[key] = (time.monotonic(), payload)
        return payload


def evidence_neighbors(data, product_id, limit=3):
    """Compare a fixed set of the reference's rated directions, never fill gaps.

    Candidates must cover every reference direction. RMS distance uses shared
    whole-catalog maxima, not per-product normalization or an efficacy percent.
    This is the existing evidence index's profile, not the legacy dose fingerprint.
    """
    products = data['products']
    target = next((p for p in products if p['id'] == product_id), None)
    if target is None:
        raise KeyError(product_id)
    known = [i for i, value in enumerate(target['scores'])
             if type(value) in (int, float) and math.isfinite(value) and target['statuses'][i] == 'scored']
    result = {'product_id': product_id, 'method_version': 'evidence-neighbors-v1',
              'index_method': METHOD_VERSION, 'compared_directions': [data['directions'][i] for i in known],
              'note': '仅比较参照产品已有评级的方向；候选须覆盖这些方向。全库同维度共用尺度，未知不补零，不表示配方或成品效果等同。',
              'items': []}
    if len(known) < 3 or not any(target['scores'][i] > 0 for i in known):
        return {**result, 'available': False, 'reason': '参照产品至少需要三个有评级的方向，当前资料不足以比较证据轮廓。'}
    scales = {i: max(1, *(p['scores'][i] for p in products if type(p['scores'][i]) in (int, float) and math.isfinite(p['scores'][i]))) for i in known}
    items = []
    for candidate in products:
        if candidate['id'] == product_id or any(candidate['statuses'][i] != 'scored' or type(candidate['scores'][i]) not in (int, float) or not math.isfinite(candidate['scores'][i]) for i in known):
            continue
        distance = math.sqrt(sum(((candidate['scores'][i]-target['scores'][i])/scales[i])**2 for i in known)/len(known))
        items.append({**candidate, 'distance': round(distance, 8)})
    items.sort(key=lambda p: (p['distance'], p['id']))
    return {**result, 'available': True, 'candidate_count': len(items), 'items': items[:limit]}
