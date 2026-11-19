"""Copy a legacy SQLite RAG index with SQLite backup; refuse to overwrite any target."""
import argparse
import sqlite3
from pathlib import Path


def restore(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.exists():
        raise ValueError('目标已存在，拒绝覆盖；请指定新路径。')
    with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as src:
        count = src.execute('SELECT COUNT(*) FROM rag_chunks').fetchone()[0]
        if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('源数据库完整性校验失败。')
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create protects against a concurrent restore overwriting a DB.
        with target.open('xb'):
            pass
        with sqlite3.connect(target) as dst:
            src.backup(dst)
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--target', required=True, type=Path)
    args = parser.parse_args()
    print('恢复片段数：', restore(args.source, args.target))
