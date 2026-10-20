"""Optional, source-bound product visuals and page excerpts, not efficacy assertions."""
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from ..config import settings


@lru_cache(maxsize=2)
def _read(path,mtime,size):
    try:
        data=json.loads(Path(path).read_text())
        return data['records'] if isinstance(data,dict) and data.get('version')=='product-presentations-v1' and isinstance(data.get('records'),dict) else {}
    except (OSError,ValueError,TypeError):return {}


def product_presentation(product):
    path=Path(settings.product_presentations_path)
    try:
        stat=path.stat();row=_read(str(path),stat.st_mtime_ns,stat.st_size).get(str(product.id))
    except OSError:return None
    if not isinstance(row,dict) or any(row.get(key)!=getattr(product,key) for key in ('id','name','brand','source_url')):return None
    source=row.get('source_url')
    if not isinstance(source,str) or not source:return None
    image=row.get('image_url')
    if image and not isinstance(image,str):image=None
    if image:
        try:u=urlparse(image)
        except ValueError:image=None;u=None
        if u is not None and (u.scheme!='https' or u.hostname!='incidecoder-content.storage.googleapis.com'):image=None
    summary=row.get('summary_excerpt')
    if not isinstance(summary,str):summary=None
    # Defence in depth: old or hand-edited assets cannot expose a whole article.
    if summary:summary=' '.join(summary.split()[:25])
    return {'image_url':image,'summary_excerpt':summary,'summary_truncated':bool(row.get('summary_truncated')),
            'source_url':source,'source_kind':'community_product_page',
            'recorded_at':row.get('recorded_at')}
