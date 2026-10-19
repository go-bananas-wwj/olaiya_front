"""Build a reproducible offline ingredient-layout artifact for a pinned DB/index.

Use .venv/bin/python with the optional dependencies in an isolated --target
folder; the web runtime does not need UMAP/Numba/torch. Output belongs in
ignored data/models/, then upload to the private dataset, never source Git.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import sqlite3
import sys

# Fix threads before importing numerical libraries. UMAP itself is single-threaded.
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('NUMBA_NUM_THREADS', '1')


def frozen_2d(path, expected_sha256, ids, signature, snapshot, dimensions, index_sha):
    """Require the exact published 2D artifact; never refit old coordinates."""
    raw = Path(path).read_bytes()
    if not expected_sha256 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('frozen 2D artifact checksum mismatch')
    data = json.loads(raw)
    expected = {'version':'ingredient-umap-v1','catalog_signature':signature,'source_snapshot':snapshot,
                'input_dimensions':dimensions,'source_index_sha256':index_sha}
    if not isinstance(data, dict) or any(data.get(k) != v for k,v in expected.items()):
        raise ValueError('frozen 2D artifact source mismatch')
    points = data.get('points')
    if not isinstance(points,list) or len(points) != len(ids):
        raise ValueError('frozen 2D artifact must cover the complete catalog')
    seen = set()
    for row in points:
        if not isinstance(row,dict) or type(row.get('id')) is not int or row['id'] in seen:
            raise ValueError('frozen 2D artifact requires unique product IDs')
        seen.add(row['id'])
        if any(type(row.get(k)) not in (int,float) or not -1e6 <= row[k] <= 1e6 or not math.isfinite(row[k]) for k in ('x','y')):
            raise ValueError('frozen 2D coordinates must be finite')
    if seen != set(ids):
        raise ValueError('frozen 2D product IDs differ from catalog')
    return data


def projection_quality(matrix, coordinates):
    """Same whole-catalog 10-NN metric as frozen v1; ties use stable Faiss order."""
    import faiss
    import numpy as np
    high = faiss.IndexFlatIP(matrix.shape[1]); high.add(matrix)
    _, high_rows = high.search(matrix, 32)
    low = faiss.IndexFlatL2(coordinates.shape[1]); low.add(np.ascontiguousarray(coordinates,dtype='float32'))
    _, low_rows = low.search(coordinates, 12)
    high_nn = [[int(i) for i in row if i >= 0 and i != r][:10] for r,row in enumerate(high_rows)]
    low_nn = [[int(i) for i in row if i >= 0 and i != r][:10] for r,row in enumerate(low_rows)]
    recall = float(np.mean([len(set(a)&set(b))/10 for a,b in zip(high_nn,low_nn)]))
    sample = np.random.default_rng(417).choice(len(matrix),min(200,len(matrix)),replace=False)
    cosine = matrix[sample]@matrix.T
    cosine[np.arange(len(sample)),sample] = 2
    order = np.argsort(-cosine,axis=1)
    ranks = np.empty_like(order); ranks[np.arange(len(sample))[:,None],order] = np.arange(len(matrix))[None,:]
    penalty = sum(max(0,int(ranks[s,neighbor])-10) for s,row in enumerate(sample) for neighbor in low_nn[row])
    trust = 1-2*penalty/(len(sample)*10*(2*len(matrix)-31))
    return {'neighbor_recall_10':recall,'sample_size':len(sample),'trustworthiness':float(trust)}


def build(database, index_dir, output, snapshot_revision, base_layout=None, base_layout_sha256=None):
    import faiss
    import numpy as np
    import umap
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
    from app.services.product_space import catalog_signature
    database, index_dir, output = Path(database).resolve(), Path(index_dir).resolve(), Path(output).resolve()
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        ids = [row[0] for row in db.execute('SELECT id FROM products ORDER BY id')]
    index_path = index_dir / 'products.faiss'
    index = faiss.read_index(str(index_path))
    metadata = json.loads((index_dir / 'products.json').read_text())
    source_ids = metadata['ids']
    if len(source_ids) != index.ntotal or len(set(source_ids)) != len(source_ids):
        raise ValueError('index rows/ID mapping must be aligned and unique')
    rows = {pid: row for row, pid in enumerate(source_ids)}
    if not ids or any(pid not in rows for pid in ids):
        raise ValueError('every catalog product must have a source vector')
    matrix = np.ascontiguousarray(np.vstack([index.reconstruct(rows[pid]) for pid in ids]), dtype='float32')
    if not np.isfinite(matrix).all() or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=.001):
        raise ValueError('expected finite, unit-normalized ingredient embeddings')
    engine = create_engine(f'sqlite:///file:{database}?mode=ro&uri=true')
    with Session(engine) as session:
        signature = catalog_signature(session)
    engine.dispose()
    index_sha = hashlib.sha256(index_path.read_bytes()).hexdigest()
    base = frozen_2d(base_layout,base_layout_sha256,ids,signature,snapshot_revision,index.d,index_sha) if base_layout else None
    if base_layout and output == Path(base_layout).resolve():
        raise ValueError('the frozen 2D source artifact may never be overwritten')
    # Stable first-observation ordering; identical source vectors retain one position.
    _, first, inverse = np.unique(matrix, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first)
    unique = matrix[first[order]]
    reverse = np.empty(len(order), dtype=int); reverse[order] = np.arange(len(order))
    expansion = reverse[inverse]
    if len(unique) < 16:
        raise ValueError('layout needs at least 16 distinct source vectors')
    faiss.omp_set_num_threads(2)
    exact = faiss.IndexFlatIP(index.d); exact.add(unique)
    similarities, neighbors = exact.search(unique, 32)
    knn = np.zeros((len(unique), 15), dtype='int64')
    distances = np.zeros_like(knn, dtype='float32')
    for row in range(len(unique)):
        hits = [(int(i), max(0., float(1-s))) for i, s in zip(neighbors[row], similarities[row]) if i >= 0 and i != row][:14]
        knn[row, 0] = row
        knn[row, 1:] = [i for i, _ in hits]
        distances[row, 1:] = [distance for _, distance in hits]
    mapper = umap.UMAP(n_components=3 if base else 2, n_neighbors=15, min_dist=.15, metric='cosine',
                       random_state=417, n_jobs=1, n_epochs=500, init='spectral',
                       force_approximation_algorithm=True, precomputed_knn=(knn, distances, None))
    coordinates = np.asarray(mapper.fit_transform(unique)[expansion], dtype='float32')
    if not np.isfinite(coordinates).all():
        raise ValueError('nonfinite layout')
    quality = projection_quality(matrix,coordinates)
    result = {
        'version': 'ingredient-umap-v1', 'source_snapshot': snapshot_revision,
        'catalog_signature': signature, 'input_dimensions': index.d,
        'source_index_sha256': index_sha,
        'parameters': {'n_neighbors': 15, 'min_dist': .15, 'random_state': 417, 'metric': 'cosine',
                       'n_epochs': 500, 'n_jobs': 1, 'exact_duplicates_collapsed': True},
        'quality': quality,
        'packages': {name: version(name) for name in ('umap-learn', 'numpy', 'numba', 'llvmlite', 'scipy', 'scikit-learn', 'pynndescent')},
        'points': [{'id': pid, 'x': float(xy[0]), 'y': float(xy[1])} for pid, xy in zip(ids, coordinates)]}
    if base:
        from sklearn.decomposition import PCA
        # Fit on all original rows (catalog-frequency weighting). Transform unique
        # vectors once, then expand, so duplicates remain bit-identical in 3D.
        pca = PCA(n_components=3,svd_solver='full')
        pca.fit(matrix)
        pca_coordinates = np.ascontiguousarray(pca.transform(unique)[expansion],dtype='float32')
        if not np.isfinite(pca_coordinates).all():
            raise ValueError('nonfinite PCA layout')
        by_id = {row['id']:row for row in base['points']}
        result.update(version='ingredient-projector-v2',parameters=base['parameters'],quality=base['quality'],
                      base_layout_sha256=base_layout_sha256,
                      umap_3d={'status':'ready','dimensions':3,'parameters':result['parameters'].copy(),'quality':quality},
                      pca={'status':'ready','dimensions':3,'parameters':{'centered':True,'svd_solver':'full'},
                           'explained_variance_ratio':[float(v) for v in pca.explained_variance_ratio_],
                           'quality':projection_quality(matrix,pca_coordinates)},
                      points=[{**by_id[pid],'umap3d':[float(v) for v in xyz],
                               'pca3d':[float(v) for v in pcs]} for pid,xyz,pcs in zip(ids,coordinates,pca_coordinates)])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, allow_nan=False, separators=(',', ':')))
    print(json.dumps({'products':len(ids),'unique_vectors':len(unique),'version':result['version'],
                      'quality':result['quality'],'umap_3d':result.get('umap_3d'),'pca':result.get('pca'),
                      'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--index-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--snapshot-revision', required=True)
    parser.add_argument('--base-layout', type=Path, help='Exact frozen v1 artifact; enables the v2 projector bundle')
    parser.add_argument('--base-layout-sha256', help='Published SHA256 of the frozen v1 artifact')
    args = parser.parse_args()
    build(args.database, args.index_dir, args.output, args.snapshot_revision,args.base_layout,args.base_layout_sha256)
