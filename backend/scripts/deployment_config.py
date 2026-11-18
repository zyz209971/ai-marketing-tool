"""Shared CLI/container configuration; never log credentials or connection URLs."""
import os
from pathlib import Path
import sys


def configure():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.environment import load_environment
    load_environment()
    os.environ['APP_SKIP_DOTENV'] = 'true'
    if os.getenv('AUTH_MODE') != 'session':
        raise ValueError('Deployment requires AUTH_MODE=session')
    if os.getenv('DB_PASSWORD'):
        from sqlalchemy import URL
        from psycopg.conninfo import make_conninfo
        fields = dict(user=os.getenv('DB_USER','brandpilot'),password=os.environ['DB_PASSWORD'],
                      host=os.getenv('DB_HOST','db'),port=os.getenv('DB_PORT','5432'),dbname=os.getenv('DB_NAME','brandpilot'))
        os.environ.setdefault('BRAND_DATABASE_URL', URL.create('postgresql+psycopg',username=fields['user'],
            password=fields['password'],host=fields['host'],port=int(fields['port']),database=fields['dbname']).render_as_string(hide_password=False))
        os.environ.setdefault('AGENT_CHECKPOINT_URL',make_conninfo(**fields))
    if not os.getenv('BRAND_DATABASE_URL','').startswith('postgresql+psycopg://') or not os.getenv('AGENT_CHECKPOINT_URL'):
        raise ValueError('Configure PostgreSQL for both business data and graph checkpoints')
    if not os.getenv('APP_DATA_DIR') or not os.getenv('BRAND_STORAGE_DIR'):
        raise ValueError('Persistent APP_DATA_DIR and BRAND_STORAGE_DIR are required')
    if os.getenv('WORKSPACE_LOCAL_ONLY') != 'false':
        raise ValueError('Container requires WORKSPACE_LOCAL_ONLY=false; authentication remains mandatory')
    if os.getenv('COOKIE_SECURE','true') != 'true' and os.getenv('ALLOW_LOCAL_HTTP') != 'true':
        raise ValueError('Only explicit loopback previews may disable secure cookies')
    if os.getenv('APP_ACCESS_KEY'):
        raise ValueError('Account deployment replaces the legacy APP_ACCESS_KEY; leave it empty')
    return int(os.getenv('PORT','8000'))
