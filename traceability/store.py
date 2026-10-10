import os
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from traceability.events import ITEM_ID, KINDS, STATUSES, safe_data


class Conflict(ValueError):
    pass


def connect():
    return psycopg.connect(os.environ['TRACE_DATABASE_URL'], connect_timeout=5, row_factory=dict_row)


def emit(conn, *, source_key, correlation_id, event_type, data, work_item_id=None):
    """Caller owns the transaction; domain mutation, audit, outbox commit together."""
    data = safe_data(event_type, data)
    correlation_id = UUID(str(correlation_id))
    channel = os.environ.get('TRACE_SLACK_CHANNEL', 'C0C883XR3DF')
    if channel != 'C0C883XR3DF':
        raise ValueError('unexpected Slack destination')
    event_id = uuid4()
    row = conn.execute(
        'INSERT INTO trace_audit(event_id,source_key,correlation_id,work_item_id,event_type,data) '
        'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(source_key) DO NOTHING RETURNING event_id',
        (event_id, source_key, correlation_id, work_item_id, event_type, Jsonb(data)),
    ).fetchone()
    if row is None:
        old = conn.execute('SELECT * FROM trace_audit WHERE source_key=%s', (source_key,)).fetchone()
        if old['event_type'] != event_type or old['data'] != data or old['work_item_id'] != work_item_id:
            raise Conflict('idempotency key reused with different data')
        return str(old['event_id'])
    conn.execute('INSERT INTO trace_outbox(event_id,channel_id) VALUES (%s,%s)', (event_id, channel))
    return str(event_id)


def record(**kwargs):
    with connect() as conn:
        return emit(conn, **kwargs)


def create_item(item, correlation_id):
    if not ITEM_ID.fullmatch(item['id']) or item['kind'] not in KINDS or item['status'] not in STATUSES:
        raise ValueError('invalid work item')
    parent_id = item.get('parent_id')
    with connect() as conn:
        # Serializes the immutable hierarchy and concurrent create/replay operations.
        conn.execute("SELECT pg_advisory_xact_lock(17361001)")
        existing = conn.execute('SELECT * FROM trace_work_item WHERE id=%s', (item['id'],)).fetchone()
        if existing:
            if any(existing[k] != item.get(k) for k in ('kind','status','parent_id')):
                raise Conflict('work item already exists with different data')
            row = conn.execute('SELECT event_id FROM trace_audit WHERE source_key=%s', ('item:'+item['id']+':1',)).fetchone()
            return str(row['event_id'])
        if item['kind'] == 'epic':
            if parent_id is not None:
                raise ValueError('epic must be a root')
        else:
            parent = conn.execute('SELECT kind FROM trace_work_item WHERE id=%s', (parent_id,)).fetchone()
            if not parent or KINDS.index(parent['kind']) != KINDS.index(item['kind']) - 1:
                raise ValueError('parent must be the preceding hierarchy level')
        conn.execute('INSERT INTO trace_work_item(id,kind,parent_id,status) VALUES (%s,%s,%s,%s)',
                     (item['id'], item['kind'], parent_id, item['status']))
        return emit(conn, source_key='item:'+item['id']+':1', correlation_id=correlation_id,
                    event_type='work_item.created', work_item_id=item['id'],
                    data={k:item.get(k) for k in ('kind','parent_id','status')} | {'version':1})


def update_item(item_id, status, expected_version, correlation_id):
    with connect() as conn:
        row = conn.execute('SELECT * FROM trace_work_item WHERE id=%s FOR UPDATE', (item_id,)).fetchone()
        if not row or row['version'] != expected_version:
            raise Conflict('missing work item or stale version')
        if status not in STATUSES:
            raise ValueError('invalid status')
        version = expected_version + 1
        conn.execute('UPDATE trace_work_item SET status=%s,version=%s WHERE id=%s', (status,version,item_id))
        return emit(conn, source_key=f'item:{item_id}:{version}', correlation_id=correlation_id,
                    event_type='work_item.updated', work_item_id=item_id,
                    data={'kind':row['kind'],'parent_id':row['parent_id'],'status':status,'version':version})
