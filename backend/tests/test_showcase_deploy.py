import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_health_does_not_expose_credentials(monkeypatch):
    monkeypatch.setenv("CFZ_LLM_CHANNEL", "cloud")
    monkeypatch.setenv("CFZ_CLOUD_API_KEY", "private-test-key")
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.json()["roundtable_configured"] is True
    assert "private-test-key" not in response.text


def bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(source / "cfz.db") as db:
        db.execute("create table example (value text)")
    (source / "products.faiss").write_bytes(b"test-index")
    files = []
    for name in ("cfz.db", "products.faiss"):
        data = (source / name).read_bytes()
        files.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"version": "test-v1", "files": files}
    (source / "manifest.json").write_text(json.dumps(manifest))
    return source, manifest


def test_bootstrap_checks_all_assets_before_installing(tmp_path):
    from deploy.bootstrap import install_snapshot
    source, manifest = bundle(tmp_path)
    (source / "products.faiss").write_bytes(b"corrupt-index")
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="checksum|size"):
        install_snapshot(source, target, manifest)
    assert not (target / "cfz.db").exists()


def test_bootstrap_preserves_existing_database_and_checks_existing_index(tmp_path):
    from deploy.bootstrap import install_snapshot
    source, manifest = bundle(tmp_path)
    target = tmp_path / "target"
    install_snapshot(source, target, manifest)
    with sqlite3.connect(target / "cfz.db") as db:
        db.execute("insert into example values ('local change')")
    install_snapshot(source, target, manifest)
    with sqlite3.connect(target / "cfz.db") as db:
        assert db.execute("select value from example").fetchone()[0] == "local change"
    (target / "products.faiss").write_bytes(b"corrupt-index")
    with pytest.raises(ValueError, match="checksum|size"):
        install_snapshot(source, target, manifest)


def test_bootstrap_rejects_path_traversal(tmp_path):
    from deploy.bootstrap import install_snapshot
    source, manifest = bundle(tmp_path)
    manifest["files"][0]["path"] = "../outside.db"
    with pytest.raises(ValueError, match="path"):
        install_snapshot(source, tmp_path / "target", manifest)


def test_export_snapshot_keeps_database_and_index_ids_consistent(tmp_path):
    from deploy.export_snapshot import export_snapshot
    db_path = tmp_path / "source.db"
    with sqlite3.connect(db_path) as db:
        db.execute("create table products (id integer primary key)")
        db.execute("insert into products values (1)")
        db.execute("create table ingredients (id integer primary key)")
        db.execute("insert into ingredients values (2)")
    index = tmp_path / "index"
    index.mkdir()
    import faiss
    import numpy as np
    for kind, ids in (("products", [1]), ("ingredients", [999])):
        vectors = faiss.IndexFlatIP(2)
        vectors.add(np.array([[1.0, 0.0]], dtype="float32"))
        faiss.write_index(vectors, str(index / f"{kind}.faiss"))
        (index / f"{kind}.json").write_text(json.dumps({"ids": ids}))
    with pytest.raises(ValueError, match="ingredients"):
        export_snapshot(db_path, index, tmp_path / "export", "test-v1")


def test_explicit_pruning_keeps_vector_rows_matched_and_records_removed_ids(tmp_path):
    from deploy.export_snapshot import export_snapshot
    import faiss
    import numpy as np
    db_path = tmp_path / "source.db"
    with sqlite3.connect(db_path) as db:
        for kind in ("products", "ingredients"):
            db.execute(f"create table {kind} (id integer primary key)")
            db.execute(f"insert into {kind} values (7)")
    indexes = tmp_path / "indexes"
    indexes.mkdir()
    for kind in ("products", "ingredients"):
        index = faiss.IndexFlatIP(2)
        index.add(np.array([[1, 0], [0, 1]], dtype="float32"))
        faiss.write_index(index, str(indexes / f"{kind}.faiss"))
        (indexes / f"{kind}.json").write_text(json.dumps({"ids": [99, 7]}))
    output = tmp_path / "export"
    manifest = export_snapshot(db_path, indexes, output, "v1", prune_deleted_ids=True)
    assert manifest["pruned_deleted_index_ids"] == {"products": [99], "ingredients": [99]}
    assert json.loads((output / "products.json").read_text())["ids"] == [7]
    np.testing.assert_array_equal(faiss.read_index(str(output / "products.faiss")).reconstruct(0), [0, 1])
    assert faiss.read_index(str(indexes / "products.faiss")).ntotal == 2
