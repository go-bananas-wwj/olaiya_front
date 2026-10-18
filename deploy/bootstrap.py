"""Verify a pinned private snapshot before starting the single-worker showcase."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile


def checked_path(root: Path, name: str) -> Path:
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("invalid snapshot path")
    path = root / name
    if path.is_symlink():
        raise ValueError("snapshot path must not be a symlink")
    return path


def verify(path: Path, entry: dict) -> None:
    if not path.is_file() or path.stat().st_size != entry["size"]:
        raise ValueError(f"snapshot size mismatch: {entry['path']}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != entry["sha256"]:
        raise ValueError(f"snapshot checksum mismatch: {entry['path']}")


def install_snapshot(source: Path, target: Path, manifest: dict) -> None:
    entries = manifest["files"]
    if not entries or len({e["path"] for e in entries}) != len(entries):
        raise ValueError("invalid snapshot paths")
    # Validate everything before copying any asset. Never overwrite a local DB.
    for entry in entries:
        verify(checked_path(source, entry["path"]), entry)
        destination = checked_path(target, entry["path"])
        if destination.exists() and entry["path"] != "cfz.db":
            verify(destination, entry)
    target.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        destination = checked_path(target, entry["path"])
        if destination.exists():
            continue
        temporary = destination.with_suffix(destination.suffix + ".partial")
        shutil.copyfile(source / entry["path"], temporary)
        os.replace(temporary, destination)
    if (target / "cfz.db").exists():
        with sqlite3.connect(f"file:{target / 'cfz.db'}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("persistent database integrity check failed")
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def install_product_layout(options, api_factory):
    """Fetch one small immutable layout, separately from the existing DB snapshot.

    A validated local layout restarts without Hub access; never install over a
    corrupted existing artifact. Its catalog signature is checked by the API.
    """
    revision = options.product_space_layout_revision
    expected = options.product_space_layout_sha256
    if not revision and not expected:
        return None
    if not re.fullmatch(r'[a-f0-9]{40}', revision) or not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ValueError('configure pinned product layout revision and checksum')
    root = Path(options.showcase_data_dir) / 'layouts' / revision
    path = checked_path(root, 'product-space-layout.json')
    if path.exists():
        if path.stat().st_size > 4_000_000 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('persistent layout checksum mismatch')
        print('Reusing verified offline ingredient layout', flush=True)
        return path
    with tempfile.TemporaryDirectory(prefix='cfz-layout-') as staging:
        downloaded = api_factory().download_file(options.snapshot_repo, 'dataset', 'product-space-layout.json',
                                                revision=revision, local_dir=Path(staging), expected_sha256=expected)
        if downloaded.stat().st_size > 4_000_000 or hashlib.sha256(downloaded.read_bytes()).hexdigest() != expected:
            raise ValueError('downloaded layout checksum mismatch')
        root.mkdir(parents=True, exist_ok=True)
        temporary = checked_path(root, 'layout.partial')
        shutil.copyfile(downloaded, temporary)
        os.replace(temporary, path)
    return path


def main() -> None:
    from app.config import settings
    from modelscope_hub import HubApi

    revision = settings.snapshot_revision
    expected_manifest = settings.snapshot_manifest_sha256
    if not settings.snapshot_repo or not re.fullmatch(r"[a-f0-9]{40}", revision) or not re.fullmatch(r"[a-f0-9]{64}", expected_manifest):
        raise ValueError("configure CFZ_SNAPSHOT_REPO, immutable CFZ_SNAPSHOT_REVISION and CFZ_SNAPSHOT_MANIFEST_SHA256")
    target = Path(settings.showcase_data_dir) / revision
    manifest_file = target / "manifest.json"
    # A valid local installation restarts without requiring Hub availability.
    if manifest_file.exists():
        if hashlib.sha256(manifest_file.read_bytes()).hexdigest() != expected_manifest:
            raise ValueError("persistent manifest checksum mismatch")
        manifest = json.loads(manifest_file.read_text())
        required = {"cfz.db", "products.faiss", "products.json", "ingredients.faiss", "ingredients.json"}
        if {e["path"] for e in manifest["files"]} != required:
            raise ValueError("snapshot paths do not match required assets")
        for entry in manifest["files"]:
            path = checked_path(target, entry["path"])
            if entry["path"] != "cfz.db":
                verify(path, entry)
            elif not path.is_file():
                raise ValueError("persistent database is missing")
        with sqlite3.connect(f"file:{target / 'cfz.db'}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("persistent database integrity check failed")
    else:
        api = HubApi(token=settings.snapshot_token.get_secret_value() if settings.snapshot_token else None)
        with tempfile.TemporaryDirectory(prefix="cfz-bootstrap-") as staging:
            source = Path(staging)
            downloaded = api.download_file(settings.snapshot_repo, "dataset", "manifest.json", revision=revision, local_dir=source)
            if hashlib.sha256(downloaded.read_bytes()).hexdigest() != expected_manifest:
                raise ValueError("downloaded manifest checksum mismatch")
            manifest = json.loads(downloaded.read_text())
            required = {"cfz.db", "products.faiss", "products.json", "ingredients.faiss", "ingredients.json"}
            if {e["path"] for e in manifest["files"]} != required:
                raise ValueError("snapshot paths do not match required assets")
            for entry in manifest["files"]:
                checked_path(source, entry["path"])
                api.download_file(settings.snapshot_repo, "dataset", entry["path"], revision=revision,
                                  local_dir=source, expected_sha256=entry["sha256"])
            install_snapshot(source, target, manifest)
    environment = dict(os.environ)
    environment["CFZ_DATABASE_URL"] = f"sqlite:///{target / 'cfz.db'}"
    environment["CFZ_FAISS_INDEX_DIR"] = str(target)
    try:
        layout = install_product_layout(settings, lambda: HubApi(token=settings.snapshot_token.get_secret_value() if settings.snapshot_token else None))
        if layout is not None:
            environment['CFZ_PRODUCT_SPACE_LAYOUT_PATH'] = str(layout)
            print('Verified offline ingredient layout ready', flush=True)
    except Exception as error:
        # A broken optional visualization asset cannot hide the raw evidence.
        environment['CFZ_PRODUCT_SPACE_LAYOUT_PATH'] = ''
        print(f'Ingredient layout unavailable ({type(error).__name__}); raw evidence coordinates remain available', flush=True)
    # Credentials for downloading assets are not needed by the web worker.
    environment.pop("CFZ_SNAPSHOT_TOKEN", None)
    print("Verified snapshot ready; starting showcase on :7860", flush=True)
    os.execvpe(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"], environment)


if __name__ == "__main__":
    main()
