import json
import pytest


def test_overlapping_manifest_is_rejected_before_database_commit(tmp_path,monkeypatch):
    import data.tools.build_selection_catalog as tool
    state={'committed':False}
    class Transaction:
        def __enter__(self):return object()
        def __exit__(self,kind,value,trace):state['committed']=kind is None
    class Factory:
        def begin(self):return Transaction()
    monkeypatch.setattr(tool,'SessionLocal',Factory());monkeypatch.setattr(tool,'init_db',lambda:None)
    monkeypatch.setattr(tool,'import_catalogue',lambda *a:{'items':[{'product_id':1}],'added':1})
    monkeypatch.setattr(tool,'load_selection_catalog',lambda *a,**k:{'verified':1})
    official=tmp_path/'official.json';official.write_text(json.dumps({'records':[],'scope_note':'test'}))
    legacy=tmp_path/'legacy.json';legacy.write_text(json.dumps({'items':[{'product_id':1}]}))
    target=tmp_path/'manifest.json';target.write_text('{"old":true}')
    with pytest.raises(ValueError,match='overlapping'):tool.build(official,legacy,target)
    assert not state['committed'] and json.loads(target.read_text())=={'old':True}
