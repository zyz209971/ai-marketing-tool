"""Offline copy into an empty destination. Source data is never modified.

Stop both application servers first. Supply a snapshot, not the working runtime.
Target databases/files must be fresh; partial failures require a new empty target.
"""
import argparse
from collections import defaultdict
from pathlib import Path
import shutil
import sqlite3
from sqlalchemy import inspect, text

TABLES = ('kb_brands','kb_products','kb_documents','kb_versions','kb_chunks','kb_works','kb_revisions','kb_fact_events',
          'kb_memories','kb_drafts','kb_extractions','kb_assets','kb_jobs','kb_index_status',
          'agent_tasks','agent_runs','agent_business_data','agent_attachments','auth_users')
SKIPPED = ('auth_sessions','auth_attempts','kb_write_guard','kb_migration_archive')


def read_snapshot(path):
    connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    connection.row_factory=sqlite3.Row
    try:
        names={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        unknown=names-set(TABLES)-set(SKIPPED)-{'sqlite_sequence'}
        if unknown:
            raise ValueError('Unsupported source tables: '+', '.join(sorted(unknown)))
        rows={name:[dict(r) for r in connection.execute('SELECT * FROM '+name)] for name in TABLES if name in names}
        if any(r['active_run'] for r in rows.get('agent_tasks',[])) or any(r['status'] in ('queued','running') for name in ('agent_runs','kb_jobs') for r in rows.get(name,[])):
            raise ValueError('Finish/recover active runs before taking a snapshot')
        for row in rows.get('agent_tasks',[]):
            row.setdefault('workspace_id','local-preview-workspace')
        return rows
    finally:
        connection.close()


def copy_business(rows, engine):
    schema=inspect(engine)
    for name in rows:
        if name not in TABLES or not schema.has_table(name):
            raise ValueError('Destination schema missing: '+name)
        columns={c['name'] for c in schema.get_columns(name)}
        if any(set(r)-columns for r in rows[name]):
            raise ValueError('Incompatible destination columns: '+name)
    with engine.begin() as connection:
        for name in TABLES:
            if schema.has_table(name) and connection.execute(text('SELECT COUNT(*) FROM '+name)).scalar_one():
                raise ValueError('Destination is not empty: '+name)
        for name, values in rows.items():
            if not values:
                continue
            columns=list(values[0])
            bind=[('CAST(:embedding AS vector)' if name=='kb_chunks' and k=='embedding' and engine.dialect.name=='postgresql' else ':'+k) for k in columns]
            connection.execute(text('INSERT INTO '+name+' ('+','.join(columns)+') VALUES ('+','.join(bind)+')'),values)


def copy_checkpoints(source, target, task_ids):
    # Saver APIs preserve serialization versions and interrupt pending writes.
    if next(target.list(None,limit=1),None):
        raise ValueError('Destination checkpoints are not empty')
    count=0
    for task_id in task_ids:
        snapshots=list(source.list({'configurable':{'thread_id':task_id}}))
        for record in reversed(snapshots):
            parent=record.parent_config or {'configurable':{'thread_id':task_id,'checkpoint_ns':record.config['configurable'].get('checkpoint_ns','')}}
            config=target.put(parent,record.checkpoint,record.metadata,record.checkpoint['channel_versions'])
            writes=defaultdict(list)
            for writer,channel,value in record.pending_writes or []:
                writes[writer].append((channel,value))
            for writer,values in writes.items():
                target.put_writes(config,values,writer)
            count+=1
    return count


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    args=parser.parse_args()
    source=args.snapshot.resolve()
    rows=read_snapshot(source/'brand-knowledge.db')
    from deployment_config import configure
    configure()
    from app import main as application, knowledge as kb
    from app.marketing_agent import store,data
    from app.marketing_agent.runtime import checkpointer
    from langgraph.checkpoint.sqlite import SqliteSaver
    store.init_db();data.init_db()
    with kb.engine.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS kb_index_status (version_id TEXT PRIMARY KEY,status TEXT NOT NULL,model TEXT NOT NULL)'))
    if source==kb.DATA or source in kb.STORAGE.parents or kb.STORAGE==source:
        raise ValueError('Source and target must be separate')
    if any(kb.STORAGE.iterdir()):
        raise ValueError('Destination file storage must be empty')
    checkpoint=source/'agent-checkpoints.db'
    if rows.get('agent_tasks') and not checkpoint.is_file():
        raise ValueError('Tasks require a matching checkpoint snapshot')
    for name,key in (('kb_versions','storage_key'),('kb_assets','storage_key')):
        for row in rows.get(name,[]):
            path=(source/'brand-files'/row[key]).resolve()
            if not path.is_relative_to(source/'brand-files') or not path.is_file():
                raise ValueError('Missing/invalid attachment in snapshot')
    with checkpointer() as target:
        if next(target.list(None,limit=1),None):
            raise ValueError('Destination checkpoints must be empty')
        copy_business(rows,kb.engine)
        if checkpoint.is_file():
            # mode=ro prevents the saver from accidentally writing the source DB.
            connection=sqlite3.connect(checkpoint.as_uri()+'?mode=ro',uri=True,check_same_thread=False)
            try:
                saver=SqliteSaver(connection);saver.is_setup=True
                count=copy_checkpoints(saver,target,[r['id'] for r in rows.get('agent_tasks',[])])
            finally:
                connection.close()
        else:
            count=0
    if (source/'brand-files').exists():
        shutil.copytree(source/'brand-files',kb.STORAGE,dirs_exist_ok=True)
    print(f'Copied {sum(map(len,rows.values()))} business rows and {count} checkpoints; source unchanged. Sessions invalidated.')
    print('Legacy marketing.db and historical migration archives are excluded; import only approved shared examples separately.')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        # Driver errors may embed credentials or stored payloads. Keep the CLI generic.
        raise SystemExit(f'Migration stopped ({type(exc).__name__}). Do not start target; inspect configuration/schema using a fresh target. Source is unchanged.') from None
