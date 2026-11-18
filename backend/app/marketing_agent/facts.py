"""Review evidence and conflicts. Candidate text never silently replaces a known fact."""
import json
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import text
from .. import knowledge as kb
from . import data


def matching(products, candidate):
    if candidate.get('id'):
        return [p for p in products if p['id']==candidate['id']]
    same=[p for p in products if p['name']==candidate.get('name')]
    spec=candidate.get('spec','').strip()
    return [p for p in same if p.get('spec','').strip()==spec] if spec else same


def review(payload):
    preview=payload['preview']
    with kb.engine.connect() as c:
        brand=kb.brand_row(kb.owned(c,payload['brand_id'],kb.get_workspace()))
        products=[dict(p) for p in c.execute(text('SELECT * FROM kb_products WHERE brand_id=:id AND archived=0'),{'id':payload['brand_id']}).mappings()]
    conflicts=[];changes=[]
    def compare(entity, old, new, fields):
        for field in fields:
            before,after=old.get(field,''),new.get(field,'')
            if field=='price' and data.price_minor(before)==data.price_minor(after): continue
            if before!=after:
                change={'entity':entity,'field':field,'before':before,'after':after}
                changes.append(change)
                if before:conflicts.append({'id':data.digest({**change,'source_version':payload.get('source_version')})[:24],**change})
    compare('brand',brand if brand['name']!='待完善品牌' else {},preview['brand_candidate'],preview['brand_candidate'].keys())
    for i,candidate in enumerate(preview['product_candidates']):
        matches=matching(products,candidate)
        if len(matches)==1:
            compare(matches[0]['id'],matches[0],candidate,['name','spec','price','selling','category'])
        elif not matches:
            compare('new_product:'+str(i),{},candidate,['name','spec','price','selling','category'])
    sources=[]
    source=preview.get('source_text','')
    for path,value in [('brand.'+k,v) for k,v in preview['brand_candidate'].items()]+[(f'products.{i}.{k}',v) for i,p in enumerate(preview['product_candidates']) for k,v in p.items() if k!='id']:
        if not value: continue
        evidence={'field':path,'value':value,'document_id':payload['document_id'],'version_id':payload['version_id'],'filename':payload.get('filename',''),'basis':'extracted_or_existing_requires_review'}
        if str(value) in source: evidence.update(basis='file_exact_text',quote=str(value))
        for supplement in payload.get('supplements',[]):
            for update in supplement.get('updates',[]):
                if update['path']==path:
                    evidence.update(basis='user_supplement',quote=update['evidence'])
        if any(path in edit.get('fields',[]) for edit in payload.get('manual_edits',[])):
            evidence.update(basis='user_edited');evidence.pop('quote',None)
        sources.append(evidence)
    return {'conflicts':conflicts,'changes':changes,'provenance':sources}


def record(c, brand_id, version_id, payload):
    c.execute(text('INSERT INTO kb_fact_events(id,brand_id,version_id,payload,created) VALUES(:id,:brand,:version,:payload,:created)'),
        {'id':uuid4().hex,'brand':brand_id,'version':version_id,'payload':json.dumps({**payload,'status':'user_confirmed'},ensure_ascii=False),'created':datetime.now(timezone.utc).isoformat()})
