"""Build small, auditable colour-group metadata from the frozen original vectors.

No projection coordinates or product claims enter clustering. No weights/vectors
are included in the output. Run with the project Python environment.
"""
import argparse
import hashlib
import json
from pathlib import Path

import faiss
import numpy as np


def build(index_path, metadata_path, output_path, k=8, seed=20261020):
    index = faiss.read_index(str(index_path))
    metadata = json.loads(Path(metadata_path).read_text())
    ids = metadata['ids']
    assert len(ids) == len(set(ids)) == index.ntotal and index.d == metadata['dim']
    vectors = index.reconstruct_n(0, index.ntotal).astype('float32')
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    assert np.isfinite(vectors).all() and (norms > 0).all()
    vectors /= norms
    rng = np.random.default_rng(seed)
    centers = [vectors[rng.integers(len(vectors))]]
    for _ in range(1, k):
        distance = np.maximum(0, 1 - (vectors @ np.array(centers).T).max(axis=1))
        centers.append(vectors[rng.choice(len(vectors), p=distance / distance.sum())])
    centers = np.array(centers)
    previous = None
    for iteration in range(100):
        labels = (vectors @ centers.T).argmax(axis=1)
        if previous is not None and np.array_equal(labels, previous):
            break
        for cluster in range(k):
            members = vectors[labels == cluster]
            assert len(members), 'Empty cluster: inspect source before choosing a new configuration'
            center = members.mean(axis=0)
            centers[cluster] = center / np.linalg.norm(center)
        previous = labels.copy()
    # Canonical group numbering follows the smallest real record ID per group.
    order = sorted(range(k), key=lambda c: min(i for i, label in zip(ids, labels) if label == c))
    remap = {cluster: number for number, cluster in enumerate(order)}
    labels = [remap[int(label)] for label in labels]
    result = {'version': 'composition-families-v1', 'method': 'spherical-kmeans',
              'k': k, 'seed': seed, 'iterations': iteration + 1, 'input_dimensions': index.d,
              'source_index_sha256': hashlib.sha256(Path(index_path).read_bytes()).hexdigest(),
              'counts': [labels.count(c) for c in range(k)],
              'note': '原始成分语义向量的统计群组，非功效或临床分类；未嵌入记录不分组。',
              'assignments': list(zip(ids, labels))}
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
    print({key: result[key] for key in ['version', 'k', 'iterations', 'counts', 'source_index_sha256']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.index, args.metadata, args.output)
