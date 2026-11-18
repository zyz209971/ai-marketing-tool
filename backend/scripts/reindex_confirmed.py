"""Retry active brand indexes using the same private environment as local Agent."""
import argparse
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', type=Path, required=True)
args = parser.parse_args()
runtime = args.runtime.resolve()
if not (runtime/'brand-knowledge.db').is_file():
    raise SystemExit('没有发现品牌数据库；不会创建空数据库。')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.environment import load_environment
load_environment()
os.environ.update(APP_SKIP_DOTENV='true', APP_DATA_DIR=str(runtime),
                  BRAND_DATABASE_URL='sqlite:///'+(runtime/'brand-knowledge.db').as_posix())
from sqlalchemy import text
from app import knowledge as kb
from app.knowledge_index import reindex_confirmed
with kb.engine.connect() as c:
    ids = c.execute(text("SELECT id FROM kb_versions WHERE status='active'")).scalars().all()
for ident in ids:
    print(ident, reindex_confirmed(ident))
