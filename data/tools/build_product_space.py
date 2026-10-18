"""Build a reproducible offline ingredient-layout artifact for a pinned DB/index.

Use .venv/bin/python with the optional dependencies in an isolated --target
folder; the web runtime does not need UMAP/Numba/torch. Output belongs in
ignored data/models/, then upload to the private dataset, never source Git.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sqlite3
import sys

# Fix threads before importing numerical libraries. UMAP itself is single-threaded.
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('NUMBA_NUM_THREADS', '1')


def build(database, index_dir, output, snapshot_revision):
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
    mapper = umap.UMAP(n_components=2, n_neighbors=15, min_dist=.15, metric='cosine',
                       random_state=417, n_jobs=1, n_epochs=500, init='spectral',
                       force_approximation_algorithm=True, precomputed_knn=(knn, distances, None))
    coordinates = np.asarray(mapper.fit_transform(unique)[expansion], dtype='float32')
    if not np.isfinite(coordinates).all():
        raise ValueError('nonfinite layout')
    high = faiss.IndexFlatIP(index.d); high.add(matrix)
    _, high_rows = high.search(matrix, 32)
    low = faiss.IndexFlatL2(2); low.add(coordinates)
    _, low_rows = low.search(coordinates, 12)
    high_nn = [[int(i) for i in row if i >= 0 and i != r][:10] for r, row in enumerate(high_rows)]
    low_nn = [[int(i) for i in row if i >= 0 and i != r][:10] for r, row in enumerate(low_rows)]
    recall = float(np.mean([len(set(a) & set(b))/10 for a, b in zip(high_nn, low_nn)]))
    # Sample trustworthiness against full, original-space ranks, not projected ranks.
    sample = np.random.default_rng(417).choice(len(ids), min(200, len(ids)), replace=False)
    cosine = matrix[sample] @ matrix.T
    cosine[np.arange(len(sample)), sample] = 2
    order = np.argsort(-cosine, axis=1)
    ranks = np.empty_like(order); ranks[np.arange(len(sample))[:, None], order] = np.arange(len(ids))[None, :]
    penalty = sum(max(0, int(ranks[s, neighbor])-10) for s, row in enumerate(sample) for neighbor in low_nn[row])
    trust = 1-2*penalty/(len(sample)*10*(2*len(ids)-31))
    engine = create_engine(f'sqlite:///file:{database}?mode=ro&uri=true')
    with Session(engine) as session:
        signature = catalog_signature(session)
    engine.dispose()
    result = {
        'version': 'ingredient-umap-v1', 'source_snapshot': snapshot_revision,
        'catalog_signature': signature, 'input_dimensions': index.d,
        'source_index_sha256': hashlib.sha256(index_path.read_bytes()).hexdigest(),
        'parameters': {'n_neighbors': 15, 'min_dist': .15, 'random_state': 417, 'metric': 'cosine',
                       'n_epochs': 500, 'n_jobs': 1, 'exact_duplicates_collapsed': True},
        'quality': {'neighbor_recall_10': recall, 'sample_size': len(sample), 'trustworthiness': trust},
        'packages': {name: version(name) for name in ('umap-learn', 'numpy', 'numba', 'llvmlite', 'scipy', 'scikit-learn', 'pynndescent')},
        'points': [{'id': pid, 'x': float(xy[0]), 'y': float(xy[1])} for pid, xy in zip(ids, coordinates)]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, separators=(',', ':')))
    print(json.dumps({'products': len(ids), 'unique_vectors': len(unique), 'neighbor_recall_10': recall,
                      'trustworthiness': trust, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--index-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--snapshot-revision', required=True)
    args = parser.parse_args()
    build(args.database, args.index_dir, args.output, args.snapshot_revision)
