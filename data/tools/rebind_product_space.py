"""Preserve frozen semantic coordinates after audited append-only catalog imports.

Old product/ingredient/order links must be bit-identical. New records have no
invented embeddings or coordinates. Recompute only the deterministic evidence
PCA offline with the existing method. Both old assets remain untouched.
"""
import argparse
import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace


def rebind(base,old_ids,old_links,new_ids,new_links,signature,revision):
    old=set(old_ids)
    if not old.issubset(new_ids) or list(old_links)!=[r for r in new_links if r[0] in old]:
        raise ValueError('existing product composition/order changed; rebuild requires review')
    result=copy.deepcopy(base)
    result.update(source_snapshot=revision,catalog_signature=signature,
                  rebound_from_snapshot=base['source_snapshot'],
                  unplaced_product_ids=sorted(set(new_ids)-{r['id'] for r in base['points']}),
                  coverage_note='Preserved original semantic universe; appended records remain unplaced until real ingredient embeddings are built.')
    return result


def database_rows(path):
    with sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True) as c:
        return [r[0] for r in c.execute('SELECT id FROM products ORDER BY id')],c.execute('SELECT product_id,ingredient_id,position FROM product_ingredients ORDER BY id').fetchall()


def build(old_database,database,base_layout,base_sha256,output,revision):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.config import settings
    from app.services.product_space import product_space,reset_space_cache,_signature
    from data.tools.build_evidence_space import build_evidence_bundle
    base_layout,output=Path(base_layout),Path(output)
    if base_layout.resolve()==output.resolve() or output.exists():raise ValueError('output must be a new immutable artifact')
    raw=base_layout.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=base_sha256:raise ValueError('base checksum mismatch')
    old_ids,old_links=database_rows(old_database);new_ids,new_links=database_rows(database)
    base=json.loads(raw)
    if base.get('catalog_signature')!=_signature([SimpleNamespace(id=i) for i in old_ids],old_links):
        raise ValueError('base layout does not belong to the old database')
    engine=create_engine(f'sqlite:///file:{Path(database).resolve()}?mode=ro&uri=true')
    previous=(settings.snapshot_revision,settings.product_space_layout_path,settings.product_space_layout_sha256)
    try:
        settings.snapshot_revision=revision;settings.product_space_layout_path='';settings.product_space_layout_sha256='';reset_space_cache()
        with Session(engine) as session:data=product_space(session)
        result=rebind(base,old_ids,old_links,new_ids,new_links,data['catalog_signature'],revision)
        result['base_artifact_sha256']=base_sha256;result['evidence_space']=build_evidence_bundle(data)
    finally:
        settings.snapshot_revision,settings.product_space_layout_path,settings.product_space_layout_sha256=previous
        reset_space_cache();engine.dispose()
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,allow_nan=False,separators=(',',':')))
    return {'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'placed':len(result['points']),'unplaced':len(result['unplaced_product_ids'])}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['old-database','database','base-layout','base-sha256','output','revision']:p.add_argument('--'+n,required=True)
    a=p.parse_args();print(json.dumps(build(a.old_database,a.database,a.base_layout,a.base_sha256,a.output,a.revision)))
