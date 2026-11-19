"""Start the isolated clean-data workspace on loopback, without browser authentication."""
import argparse
import os
import sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8018)
    args=parser.parse_args()
    runtime=args.runtime.resolve()
    data=runtime/'data'
    if not (runtime/'import-summary.json').is_file() or not (data/'brand-knowledge.db').is_file():
        raise SystemExit('请先完成干净数据工作空间的准备。')
    os.environ.update(APP_ENV='development',WORKSPACE_LOCAL_ONLY='true',APP_DATA_DIR=str(data),
                      BRAND_DATABASE_URL='sqlite:///'+(data/'brand-knowledge.db').as_posix(),
                      BRAND_STORAGE_DIR=str(data/'brand-files'),
                      SEED_DEMO_DATA='false',APP_ACCESS_KEY='',
                      QUOTA_PER_USER='100',QUOTA_TOTAL='1000')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from app.main import app
    from app import config, knowledge
    # A backend/.env may override shell variables. Fail closed rather than open wrong data.
    if (config.DATA_DIR != data or knowledge.STORAGE != (data/'brand-files').resolve()
            or knowledge.DATABASE_URL != 'sqlite:///'+(data/'brand-knowledge.db').as_posix()
            or os.getenv('WORKSPACE_LOCAL_ONLY')!='true'
            or config.APP_ACCESS_KEY):
        raise SystemExit('backend/.env 覆盖了本地工作空间配置，请先移除冲突项。')
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port,proxy_headers=False)


if __name__=='__main__':
    main()
