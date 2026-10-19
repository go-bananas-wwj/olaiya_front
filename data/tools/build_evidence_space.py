"""Append offline evidence PCA to an immutable, checked semantic v2 bundle.

Only numpy is needed; HTTP never runs this builder. Artifacts belong under
ignored data/models/ and the private dataset, not in source Git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'backend'))


def build_evidence_bundle(data):
    import numpy as np
    from app.services.evidence_space import METHOD_VERSION, METRIC, evidence_geometry, evidence_profile_signature
    from app.services.capability_profile import METHOD_VERSION as INDEX_METHOD, DIRECTIONS
    geometry = evidence_geometry(data)
    eligible = set(geometry['eligible_ids'])
    products = [p for p in data['products'] if p['id'] in eligible]
    ratios = np.zeros(3, dtype='float64')
    coordinates = np.zeros((len(products),3), dtype='float64')
    if products:
        matrix = np.asarray([p['scores'] for p in products],dtype='float64') / np.asarray(geometry['scales'])
        centered = matrix - matrix.mean(axis=0)
        _, singular, components = np.linalg.svd(centered, full_matrices=False)
        count = min(3,len(singular))
        # Resolve SVD sign ambiguity with the largest loading. Transform exact
        # duplicate profiles once, so duplicate observations stay bit-identical.
        for i in range(count):
            if components[i,np.argmax(np.abs(components[i]))] < 0:
                components[i] *= -1
        unique, inverse = np.unique(centered,axis=0,return_inverse=True)
        coordinates[:,:count] = (unique @ components[:count].T)[inverse]
        variance = float(np.sum(singular ** 2))
        if variance > 0:
            ratios[:count] = singular[:count] ** 2 / variance
    return {'method_version':METHOD_VERSION, 'index_method':INDEX_METHOD, 'metric':METRIC,
            'directions':list(DIRECTIONS), 'scales':geometry['scales'],
            'profile_signature':evidence_profile_signature(data),
            'projection':{'status':'ready','method':'pca','dimensions':3,'input_dimensions':8,
                          'parameters':{'centered':True,'svd_solver':'full'},
                          'explained_variance_ratio':ratios.tolist()},
            'points':[{'id':p['id'],'pca3d':coordinates[i].tolist()} for i,p in enumerate(products)]}


def build(database, base_layout, base_layout_sha256, output, snapshot_revision):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.config import settings
    from app.services.product_space import product_space, reset_space_cache
    database, base_layout, output = Path(database).resolve(), Path(base_layout).resolve(), Path(output).resolve()
    if output == base_layout:
        raise ValueError('the frozen semantic bundle may never be overwritten')
    raw = base_layout.read_bytes()
    if not base_layout_sha256 or hashlib.sha256(raw).hexdigest() != base_layout_sha256:
        raise ValueError('semantic bundle checksum mismatch')
    base = json.loads(raw)
    if base.get('version') != 'ingredient-projector-v2' or base.get('source_snapshot') != snapshot_revision:
        raise ValueError('semantic bundle version/snapshot mismatch')
    engine = create_engine(f'sqlite:///file:{database}?mode=ro&uri=true')
    old = (settings.snapshot_revision, settings.product_space_layout_path, settings.product_space_layout_sha256)
    try:
        settings.snapshot_revision = snapshot_revision
        settings.product_space_layout_path = str(base_layout)
        settings.product_space_layout_sha256 = base_layout_sha256
        reset_space_cache()
        with Session(engine) as session:
            data = product_space(session)
        if base.get('catalog_signature') != data['catalog_signature'] or data['projection']['status'] != 'ready':
            raise ValueError('semantic bundle catalog/coordinate mismatch')
        result = {**base,'version':'ingredient-projector-v3','semantic_bundle_sha256':base_layout_sha256,
                  'evidence_space':build_evidence_bundle(data)}
    finally:
        settings.snapshot_revision,settings.product_space_layout_path,settings.product_space_layout_sha256 = old
        reset_space_cache();engine.dispose()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,allow_nan=False,separators=(',',':')))
    print(json.dumps({'version':result['version'],'eligible_count':len(result['evidence_space']['points']),
                      'total':data['total'],'scales':result['evidence_space']['scales'],
                      'explained_variance_ratio':result['evidence_space']['projection']['explained_variance_ratio'],
                      'profile_signature':result['evidence_space']['profile_signature'],
                      'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--base-layout',type=Path,required=True)
    parser.add_argument('--base-layout-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--snapshot-revision',required=True)
    args = parser.parse_args()
    build(args.database,args.base_layout,args.base_layout_sha256,args.output,args.snapshot_revision)
