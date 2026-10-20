"""Load reviewed facts and reuse existing records into a writable DB snapshot.

Use CFZ_DATABASE_URL to select a staging database. Never pass a frozen release
snapshot as the target. Raw captures and model files are not needed by this tool.
"""
import argparse
import json
import os
import tempfile
from pathlib import Path
from app.db import SessionLocal,init_db
from data.loaders.official_catalog_loader import import_catalogue
from data.loaders.selection_catalog_loader import load_selection_catalog


def build(official,legacy,manifest):
    document=json.loads(Path(official).read_text());old=json.loads(Path(legacy).read_text())
    target=Path(manifest)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and not target.is_file():raise ValueError('manifest target must be a file')
    temporary=None
    try:
        init_db()
        with SessionLocal.begin() as session:
            fresh=import_catalogue(session,document['records'])
            reused=load_selection_catalog(session,legacy,apply_verified_updates=True)
            output={'version':'selection-catalog-v1','scope_note':document['scope_note']+' 另复用已核验品类的既有记录；来源与版本不明时不跨记录补价或补成分。',
                    'items':fresh['items']+old['items']}
            ids=[r['product_id'] for r in output['items']]
            if len(set(ids))!=len(ids):raise ValueError('overlapping source identities')
            # Validate and prewrite in the transaction; failures must roll back.
            content=json.dumps(output,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,prefix=target.name+'.',delete=False) as f:
                temporary=Path(f.name);f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(temporary,target)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return {'official':len(fresh['items']),'added':fresh['added'],'reused':reused['verified']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official',default='data/research/selection_catalog_20261020.json')
    parser.add_argument('--legacy',default='data/research/selection_legacy_audit.json')
    parser.add_argument('--manifest',default='data/seed/selection_catalog.json')
    args=parser.parse_args();print(json.dumps(build(args.official,args.legacy,args.manifest)))
