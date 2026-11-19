"""Reindex reviewed text, never raw drafts. Failed embeddings leave lexical search usable."""
import json
import logging
from sqlalchemy import text
from . import knowledge as kb, rag

logger = logging.getLogger(__name__)


def reindex_confirmed(version_id):
    with kb.engine.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS kb_index_status (version_id TEXT PRIMARY KEY,status TEXT NOT NULL,model TEXT NOT NULL)'))
        rows = c.execute(text("SELECT c.id,c.content FROM kb_chunks c JOIN kb_versions v ON v.id=c.version_id WHERE c.version_id=:id AND v.status='active' ORDER BY c.ordinal"), {'id': version_id}).mappings().all()
    status, vectors = 'lexical_only', []
    if rows and rag._embedding_enabled():
        try:
            vectors = rag._embed_many([r['content'] for r in rows])
            if len(vectors) != len(rows) or any(not v for v in vectors):
                raise ValueError('Embedding count mismatch')
            status = 'ready'
        except Exception:
            status, vectors = 'embedding_failed', []
            logger.warning('确认资料向量更新失败，仍可关键词检索', exc_info=True)
    with kb.engine.begin() as c:
        active = c.execute(text("SELECT id FROM kb_versions WHERE id=:id AND status='active'"), {'id': version_id}).first()
        if not active:
            return 'superseded'
        for row, vector in zip(rows, vectors):
            c.execute(text('UPDATE kb_chunks SET embedding=:embedding,embedding_model=:model WHERE id=:id AND content=:content'),
                      {'embedding': json.dumps(vector), 'model': rag.EMBED_MODEL, 'id': row['id'], 'content': row['content']})
        c.execute(text('INSERT INTO kb_index_status(version_id,status,model) VALUES(:id,:status,:model) ON CONFLICT(version_id) DO UPDATE SET status=:status,model=:model'),
                  {'id': version_id, 'status': status, 'model': rag.EMBED_MODEL if status == 'ready' else ''})
    return status
