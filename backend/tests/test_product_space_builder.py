"""Frozen 2D source checks do not require optional numerical dependencies."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


spec=importlib.util.spec_from_file_location('space_builder',Path(__file__).resolve().parents[2]/'data/tools/build_product_space.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


def frozen(tmp_path):
    value={'version':'ingredient-umap-v1','source_snapshot':'snapshot','catalog_signature':'signature',
           'input_dimensions':4096,'source_index_sha256':'index-sha','parameters':{},'quality':{},
           'points':[{'id':3,'x':1.234567890123,'y':-2.},{'id':8,'x':0.,'y':3.}]}
    path=tmp_path/'frozen.json';path.write_text(json.dumps(value))
    return path,value,hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_coordinates_keep_all_original_values(tmp_path):
    path,value,digest=frozen(tmp_path)
    result=builder.frozen_2d(path,digest,[3,8],'signature','snapshot',4096,'index-sha')
    assert result==value
    assert result['points'][0]['x']==1.234567890123


@pytest.mark.parametrize('field,value',[
    ('source_snapshot','different'),('catalog_signature','stale'),('input_dimensions',2),
    ('source_index_sha256','wrong'),('points',[{'id':3,'x':1.,'y':2.}]),
    ('points',[{'id':3,'x':float('nan'),'y':2.},{'id':8,'x':1.,'y':3.}]),
    ('points',[{'id':3,'x':1.,'y':2.},{'id':3,'x':1.,'y':2.}]),
])
def test_frozen_bundle_cannot_be_rebound_to_different_sources(tmp_path,field,value):
    path,content,_=frozen(tmp_path);content[field]=value;path.write_text(json.dumps(content))
    with pytest.raises(ValueError):
        builder.frozen_2d(path,hashlib.sha256(path.read_bytes()).hexdigest(),[3,8],'signature','snapshot',4096,'index-sha')


def test_frozen_bundle_hash_is_mandatory_and_checked(tmp_path):
    path,_,_=frozen(tmp_path)
    for digest in ('','incorrect'):
        with pytest.raises(ValueError):
            builder.frozen_2d(path,digest,[3,8],'signature','snapshot',4096,'index-sha')
