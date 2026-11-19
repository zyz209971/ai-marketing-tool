"""Archive generated versions in the same transaction as their conversation."""
import json
from datetime import datetime, timezone
from sqlalchemy import text
from .. import knowledge as kb


def save(c, state):
    brand=state['brief'].get('brand_id')
    if not brand: return  # Synthetic demo works do not enter a real brand.
    changed=False
    for artifact in state.get('artifacts',[]):
        old=c.execute(text('SELECT payload FROM kb_works WHERE id=:id AND brand_id=:brand'),{'id':artifact['id'],'brand':brand}).scalar_one_or_none()
        stamp=json.loads(old)['time'] if old else datetime.now(timezone.utc).isoformat()
        work={'id':artifact['id'],'brand':brand,'time':stamp,'draft':{},'result':artifact,
              'agent_origin':{'task_id':state['task_id'],'artifact_id':artifact['id'],'strategy_id':artifact.get('strategy_id'),
                              'version':artifact['version'],'source_refs':artifact.get('source_refs',[]),'stale':artifact['stale']}}
        serialized=json.dumps(work,ensure_ascii=False)
        if old==serialized:continue
        c.execute(text('INSERT INTO kb_works(id,brand_id,payload) VALUES(:id,:brand,:payload) ON CONFLICT(id) DO UPDATE SET payload=:payload'),{'id':artifact['id'],'brand':brand,'payload':serialized})
        changed=True
    if changed:kb.bump_revision(c,kb.get_workspace())
