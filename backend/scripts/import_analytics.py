"""Import a product/order/cost bundle for the operating dashboard.

Usage (from repository root):
    python backend/scripts/import_analytics.py
    python backend/scripts/import_analytics.py --source "合成数据+人工答案+商品图片+csv+json"
    python backend/scripts/import_analytics.py --runtime .local-data/agent

The local launcher stores runtime data in ``.local-data/agent`` by default, so
the default destination matches ``run_agent_local.py``. The import replaces the
previous dashboard snapshot; source CSV files stay unchanged.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
SOURCE_DEFAULT = ROOT / '合成数据+人工答案+商品图片+csv+json'
RUNTIME_DEFAULT = ROOT / '.local-data' / 'agent'


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='导入经营看板订单/成本/商品数据')
    parser.add_argument('--source', type=Path, default=SOURCE_DEFAULT, help='包含 products.csv、orders.csv、costs.csv 的目录')
    parser.add_argument('--runtime', type=Path, default=RUNTIME_DEFAULT, help='本地运行数据目录，与 run_agent_local.py --runtime 一致')
    parser.add_argument('--database', default='', help='直接指定 analytics 数据库 URL，优先于 --runtime')
    args = parser.parse_args()

    runtime = args.runtime.expanduser().resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    if args.database:
        os.environ['ANALYTICS_DATABASE_URL'] = args.database
    else:
        os.environ['APP_DATA_DIR'] = str(runtime)
        os.environ['ANALYTICS_DATABASE_URL'] = f"sqlite:///{(runtime / 'analytics.db').as_posix()}"
    os.environ.setdefault('APP_SKIP_DOTENV', 'true')
    os.environ.setdefault('USE_MOCK', 'true')
    sys.path.insert(0, str(BACKEND))

    from app import analytics
    try:
        result = analytics.import_dataset(args.source)
    except Exception as exc:
        raise SystemExit(f'导入失败：{exc}') from None
    print(f"已导入 {result['brand']} / {result['dataset_version']}")
    print(f"商品 {result['products']} 款，成本 {result['costs']} 条，活动 {result['campaigns']} 个")
    print(f"订单行：历史 {result['history_orders']}，活动回传 {result['feedback_orders']}")
    print(f"数据目录：{runtime}")
    print('启动服务后打开 #/analytics 查看经营看板。')


if __name__ == '__main__':
    main()
