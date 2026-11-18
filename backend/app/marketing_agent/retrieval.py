"""Reuse the existing two indexes; separate authoritative facts from writing references."""
import logging
from .. import rag

logger = logging.getLogger(__name__)


def marketing_examples(brief, product):
    if not rag.DB_PATH.exists():
        return {'status': 'not_indexed', 'items': []}
    try:
        rows = rag.search_marketing(product['name']+' '+brief.get('goal', ''), top_k=3, platform=brief.get('platform'))
        return {'status': 'ok' if rows else 'no_match', 'items': [
            {'document_id': r['document_id'], 'knowledge_type': 'marketing_reference',
             'authority': 'style_only', 'brand': r.get('brand', ''), 'platform': r.get('platform', ''),
             'source_url': r.get('source_url', ''), 'text': r['text'], 'score': r['score']}
            for r in rows]}
    except Exception:
        logger.warning('营销案例检索失败；不影响已确认事实写作', exc_info=True)
        return {'status': 'unavailable', 'items': []}
