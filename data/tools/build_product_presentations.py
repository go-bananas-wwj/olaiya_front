"""Reuse cached product pages for bounded presentation metadata, never efficacy evidence."""
import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


class PresentationParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.image_depth=0;self.summary_depth=0;self.image_url=None;self.parts=[]
    def handle_starttag(self,tag,attributes):
        a=dict(attributes)
        if tag=='div' and a.get('id')=='product-main-image':self.image_depth=1
        elif tag=='div' and self.image_depth:self.image_depth+=1
        if tag=='span' and a.get('id')=='product-details':self.summary_depth=1
        elif tag=='span' and self.summary_depth:self.summary_depth+=1
        if self.image_depth and tag=='source' and a.get('type')=='image/webp' and a.get('srcset'):
            self.image_url=a['srcset'].split(',')[0].strip().split()[0]
        if self.image_depth and tag=='img' and not self.image_url:self.image_url=a.get('src')
    def handle_endtag(self,tag):
        if tag=='div' and self.image_depth:self.image_depth-=1
        if tag=='span' and self.summary_depth:self.summary_depth-=1
    def handle_data(self,data):
        if self.summary_depth:self.parts.append(data)


def parse_presentation(html,slug):
    parser=PresentationParser();parser.feed(html)
    image=parser.image_url
    if image:
        u=urlparse(image)
        if u.scheme!='https' or u.hostname!='incidecoder-content.storage.googleapis.com' or f'/{slug}/' not in u.path:image=None
    summary=re.sub(r'\s+',' ',' '.join(parser.parts)).strip()
    words=summary.split();summary=' '.join(words[:25]) if words else None
    return {'image_url':image,'summary_excerpt':summary,'summary_truncated':len(words)>25}


def build(raw_root,output):
    from app.db import SessionLocal
    from app.models.product import Product
    from sqlalchemy import select
    with SessionLocal() as session:
        products=session.execute(select(Product.id,Product.name,Product.brand,Product.source_url)).all()
    by_source={p.source_url:p for p in products if p.source_url}
    records={}
    for path in sorted(raw_root.rglob('*.json')):
        if path.name.startswith('_'):continue
        try:
            data=json.loads(path.read_text());source=data.get('source',{});url=source.get('url');p=by_source.get(url)
            html_path=path.with_suffix('.html')
            if p is None or not html_path.is_file() or data.get('brand')!=p.brand:continue
            slug=data.get('product_slug');u=urlparse(url)
            if u.scheme!='https' or u.hostname!='incidecoder.com' or u.path!=f'/products/{slug}':continue
            html=html_path.read_bytes();presentation=parse_presentation(html.decode('utf-8'),slug)
            if not any(presentation.get(k) for k in ('image_url','summary_excerpt')):continue
            records[str(p.id)]={'id':p.id,'name':p.name,'brand':p.brand,'source_url':url,
                **presentation,'source_kind':'community_product_page',
                'recorded_at':source.get('collected_at'),
                'source_html_sha256':hashlib.sha256(html).hexdigest()}
        except (ValueError,TypeError,KeyError,UnicodeError):continue
    output.write_text(json.dumps({'version':'product-presentations-v1','records':records},ensure_ascii=False,separators=(',',':'))+'\n')
    print({'records':len(records),'images':sum(bool(r['image_url']) for r in records.values()),'source_excerpts':sum(bool(r['summary_excerpt']) for r in records.values()),'output_bytes':output.stat().st_size})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-root',type=Path,default=Path('data/raw/incidecoder'))
    parser.add_argument('--output',type=Path,default=Path('data/seed/product_presentations.json'))
    args=parser.parse_args();build(args.raw_root,args.output)
