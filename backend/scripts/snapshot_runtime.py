"""Take a stopped local-runtime snapshot; never delete or replace existing backups."""
import argparse
from pathlib import Path
import shutil
import sqlite3
from migrate_runtime import read_snapshot


def snapshot(source, destination):
    source,destination=source.resolve(),destination.resolve()
    if source==destination or source in destination.parents or destination in source.parents:
        raise ValueError('Snapshot must be outside the source runtime')
    read_snapshot(source/'brand-knowledge.db')  # Reject unsettled jobs and unknown schemas.
    destination.mkdir(parents=True,exist_ok=False)
    for name in ('brand-knowledge.db','agent-checkpoints.db','marketing.db'):
        path=source/name
        if path.is_file():
            connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
            target=sqlite3.connect(destination/name)
            try: connection.backup(target)
            finally: target.close();connection.close()
    if (source/'brand-files').exists():
        shutil.copytree(source/'brand-files',destination/'brand-files')
    (destination/'snapshot.txt').write_text('Stopped-server snapshot. Restore business DB, checkpoints and files as one set. Contains private data.\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    snapshot(args.runtime,args.destination)
    print('Snapshot created; source unchanged.')
