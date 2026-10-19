"""Versioned eight-axis evidence geometry, independent from semantic embeddings.

All axes share catalog-wide scales; missing/unrated values are never zeros.
HTTP only validates a pinned offline PCA bundle and calculates original-space
RMS distances. No numerical fitting, model calls, or database mutations occur.
"""
import hashlib
import json
import math
from pathlib import Path

from ..config import settings
from .capability_profile import DIRECTIONS, METHOD_VERSION as INDEX_METHOD
from .product_space import _number, product_space

METHOD_VERSION = 'evidence-space-v1'
METRIC = 'scaled-rms'
NOTE = '仅比较八个方向均有合格证据的产品；各方向共用全库尺度，未知不补零。距离越小表示已收录证据画像越接近，不是成品功效或质量评分。'


def _scored(product, axis):
    return product['statuses'][axis] == 'scored' and _number(product['scores'][axis], 0)


def evidence_geometry(data):
    scales = [max([1] + [p['scores'][i] for p in data['products'] if _scored(p, i)]) for i in range(len(DIRECTIONS))]
    eligible_ids = [p['id'] for p in data['products'] if all(_scored(p, i) for i in range(len(DIRECTIONS)))]
    return {'scales':scales, 'eligible_ids':eligible_ids}


def evidence_profile_signature(data):
    values = [METHOD_VERSION, INDEX_METHOD, list(DIRECTIONS),
              [[p['id'], p['scores'], p['statuses']] for p in sorted(data['products'], key=lambda p:p['id'])]]
    return hashlib.sha256(json.dumps(values, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _projection(data, geometry):
    unavailable = {'status':'unavailable', 'method':'pca', 'input_dimensions':8, 'dimensions':3,
                   'pca':{'status':'unavailable', 'dimensions':3},
                   'note':'八方向证据投影未配置或未通过校验；仍可搜索产品并查看证据对比。'}
    path, digest = settings.product_space_layout_path, settings.product_space_layout_sha256
    if not path or not digest:
        return {}, unavailable
    try:
        if Path(path).stat().st_size > 4_000_000:
            return {}, unavailable
        raw = Path(path).read_bytes()
        if len(raw) > 4_000_000 or hashlib.sha256(raw).hexdigest() != digest:
            return {}, unavailable
        artifact = json.loads(raw)
        if not isinstance(artifact, dict) or any(artifact.get(k) != v for k,v in {
            'version':'ingredient-projector-v3', 'source_snapshot':settings.snapshot_revision,
            'catalog_signature':data['catalog_signature']}.items()):
            return {}, unavailable
        space = artifact.get('evidence_space')
        if not isinstance(space, dict) or any(space.get(k) != v for k,v in {
            'method_version':METHOD_VERSION, 'index_method':INDEX_METHOD, 'metric':METRIC,
            'directions':list(DIRECTIONS), 'scales':geometry['scales'],
            'profile_signature':evidence_profile_signature(data)}.items()):
            return {}, unavailable
        projection = space.get('projection')
        if not isinstance(projection, dict) or any(projection.get(k) != v for k,v in {
            'status':'ready', 'method':'pca', 'input_dimensions':8, 'dimensions':3,
            'parameters':{'centered':True,'svd_solver':'full'}}.items()):
            return {}, unavailable
        ratios = projection.get('explained_variance_ratio')
        if not isinstance(ratios,list) or len(ratios) != 3 or not all(_number(v,0,1) for v in ratios) or sum(ratios) > 1.000001:
            return {}, unavailable
        points = space.get('points')
        if not isinstance(points,list):
            return {}, unavailable
        coordinates = {}
        for row in points:
            if not isinstance(row,dict) or type(row.get('id')) is not int or row['id'] in coordinates:
                return {}, unavailable
            vector = row.get('pca3d')
            if not isinstance(vector,list) or len(vector) != 3 or not all(_number(v) for v in vector):
                return {}, unavailable
            coordinates[row['id']] = vector
        if set(coordinates) != set(geometry['eligible_ids']):
            return {}, unavailable
        meta = {**projection, 'pca':{**projection, 'quality':{}}, 'note':NOTE}
        return coordinates, meta
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return {}, unavailable


def evidence_product_space(session):
    source = product_space(session)
    geometry = evidence_geometry(source)
    coordinates, projection = _projection(source, geometry)
    eligible = set(geometry['eligible_ids'])
    items = [{**p, 'eligible':p['id'] in eligible,
              'missing_directions':[DIRECTIONS[i] for i in range(len(DIRECTIONS)) if not _scored(p,i)],
              'coordinates':coordinates[p['id']][:2] if p['id'] in coordinates else None,
              'coordinates_3d':coordinates.get(p['id']), 'pca_coordinates':coordinates.get(p['id'])}
             for p in source['products']]
    payload = {**source, 'products':items, 'method_version':METHOD_VERSION, 'index_method':INDEX_METHOD,
               'metric':METRIC, 'scales':geometry['scales'], 'eligible_count':len(eligible),
               'excluded_count':len(items)-len(eligible), 'coordinate_count':len(coordinates),
               'coordinate_count_3d':len(coordinates), 'pca_coordinate_count':len(coordinates),
               'projection':projection, 'note':NOTE, 'profile_signature':evidence_profile_signature(source)}
    payload.pop('revision', None)
    payload['revision'] = hashlib.sha256(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()
    return payload


def evidence_space_neighbors(data, product_id, limit=100):
    products = data['products']
    target = next((p for p in products if p['id'] == product_id), None)
    if target is None:
        raise KeyError(product_id)
    geometry = evidence_geometry(data)
    missing = [DIRECTIONS[i] for i in range(len(DIRECTIONS)) if not _scored(target,i)]
    result = {'product_id':product_id, 'method_version':METHOD_VERSION, 'index_method':INDEX_METHOD,
              'metric':METRIC, 'scales':geometry['scales'], 'compared_directions':list(DIRECTIONS),
              'missing_directions':missing, 'note':NOTE, 'items':[], 'available':not missing}
    if missing:
        return {**result, 'reason':'八个方向的证据资料尚未齐全，不把未知补成零；该产品暂不进入证据空间。', 'candidate_count':0}
    eligible = set(geometry['eligible_ids'])
    items = []
    for p in products:
        if p['id'] not in eligible or p['id'] == product_id:
            continue
        distance = math.sqrt(sum(((p['scores'][i]-target['scores'][i])/geometry['scales'][i])**2 for i in range(len(DIRECTIONS)))/len(DIRECTIONS))
        items.append({**p,'distance':round(distance,8)})
    items.sort(key=lambda p:(p['distance'],p['id']))
    return {**result, 'reason':None, 'candidate_count':len(items), 'items':items[:limit]}
