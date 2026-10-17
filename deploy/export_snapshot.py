"""导出一致 SQLite 快照与匹配索引；产物只能存放 data/ 下，不进入代码仓库。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


def export_snapshot(database: Path, index_dir: Path, output: Path, version: str, *, prune_deleted_ids: bool = False) -> dict:
    import faiss
    import numpy as np

    if output.exists():
        raise ValueError("output already exists; use a new version directory")
    output.mkdir(parents=True)
    try:
        with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as source:
            with sqlite3.connect(output / "cfz.db") as destination:
                source.backup(destination)
        pruned = {}
        with sqlite3.connect(output / "cfz.db") as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("database integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("database foreign key check failed")
            for kind in ("products", "ingredients"):
                metadata = json.loads((index_dir / f"{kind}.json").read_text())
                ids = metadata["ids"]
                known_ids = {row[0] for row in db.execute(f"SELECT id FROM {kind}")}
                vector_index = faiss.read_index(str(index_dir / f"{kind}.faiss"))
                if len(ids) != len(set(ids)) or vector_index.ntotal != len(ids):
                    raise ValueError(f"{kind} index IDs do not match the database snapshot")
                stale = set(ids) - known_ids
                if stale and not prune_deleted_ids:
                    raise ValueError(f"{kind} index IDs do not match the database snapshot")
                if stale:
                    rows = [i for i, entity_id in enumerate(ids) if entity_id in known_ids]
                    if not rows:
                        raise ValueError(f"{kind} has no surviving index IDs")
                    filtered = faiss.IndexFlatIP(vector_index.d)
                    filtered.add(np.stack([vector_index.reconstruct(row) for row in rows]))
                    faiss.write_index(filtered, str(output / f"{kind}.faiss"))
                    metadata["ids"] = [ids[row] for row in rows]
                    (output / f"{kind}.json").write_text(json.dumps(metadata, ensure_ascii=False))
                    pruned[kind] = sorted(stale)
                    continue
                for suffix in ("json", "faiss"):
                    shutil.copyfile(index_dir / f"{kind}.{suffix}", output / f"{kind}.{suffix}")
        files = [{"path": file.name, "size": file.stat().st_size, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                 for file in sorted(output.iterdir())]
        manifest = {"version": version, "files": files, "pruned_deleted_index_ids": pruned}
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        return manifest
    except Exception:
        # Only remove this tool's newly created, incomplete export directory.
        shutil.rmtree(output)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("cfz.db"))
    parser.add_argument("--index-dir", type=Path, default=Path("data/models/embedding/faiss/qwen3-8b"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--prune-deleted-ids", action="store_true", help="Explicitly remove deleted entities from exported indexes; record IDs in manifest")
    args = parser.parse_args()
    print(json.dumps(export_snapshot(args.database, args.index_dir, args.output, args.version, prune_deleted_ids=args.prune_deleted_ids), ensure_ascii=False, indent=2))
