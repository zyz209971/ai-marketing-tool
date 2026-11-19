"""Local runtime: auto mode uses configured credentials; keys stay in the backend."""
import argparse
import os
from pathlib import Path
import sys


def configure_runtime(runtime):
    # Local previews may reuse model credentials, never deployment databases.
    os.environ.update(APP_DATA_DIR=str(runtime), BRAND_DATABASE_URL='sqlite:///'+(runtime/'brand-knowledge.db').as_posix(),
                      AGENT_CHECKPOINT_URL='', BRAND_STORAGE_DIR=str(runtime/'brand-files'),
                      WORKSPACE_LOCAL_ONLY='true', SEED_DEMO_DATA='false')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8021)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--live', action='store_true')
    modes.add_argument('--offline', action='store_true')
    parser.add_argument('--env-file', help='已有私有配置文件路径，不复制密钥到仓库')
    parser.add_argument('--check', action='store_true', help='只检查配置是否齐全，不发起模型请求')
    parser.add_argument('--runtime', type=Path, default=Path(__file__).resolve().parents[2]/'.local-data'/'agent')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.environment import load_environment
    loaded = load_environment(explicit_file=args.env_file)
    os.environ['APP_SKIP_DOTENV'] = 'true'
    configure_runtime(runtime)
    if args.live or args.offline:
        os.environ['USE_MOCK'] = 'false' if args.live else 'true'
    from app.config import AGENT_USE_MOCK, AGENT_API_KEY, AGENT_BASE_URL, AGENT_MODEL, USE_MOCK
    if args.check:
        from urllib.parse import urlsplit
        print('配置来源：'+('、'.join(loaded) if loaded else '进程环境变量（未发现私有配置文件）'))
        print('Agent 密钥：'+('已配置' if AGENT_API_KEY else '未配置'))
        print('服务域名：'+str(urlsplit(AGENT_BASE_URL).hostname))
        print('Agent 模型：'+AGENT_MODEL)
        print('运行模式：'+('离线演示' if AGENT_USE_MOCK else '模型决策'))
        print('文案模式：'+('离线演示' if USE_MOCK else '模型生成'))
        return
    if args.live and AGENT_USE_MOCK:
        raise SystemExit('实时模式缺少密钥。请配置 backend/.env.local，或使用 --env-file 指定已有私有配置。')
    from app.main import app
    import uvicorn
    print(f'营销助手：http://127.0.0.1:{args.port}/ | 模式：'+('离线规则演示，不调用模型' if AGENT_USE_MOCK else '模型决策；经营数据来源以所选品牌为准'))
    uvicorn.run(app, host='127.0.0.1', port=args.port, proxy_headers=False)


if __name__ == '__main__':
    main()
