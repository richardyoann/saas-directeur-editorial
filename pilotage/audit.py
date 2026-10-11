"""Versioned domain mutations + audit + outbox in one caller-owned transaction."""
import hashlib
import json
from uuid import UUID, uuid4
from psycopg.types.json import Jsonb

KINDS={'prompt','treatment','scenario','scene','result'}

def mutate(conn, *, tenant_id, actor_id, kind, entity_id, operation, expected_version, content, source_key, correlation_id):
    tenant_id,actor_id,entity_id,source_key,correlation_id=map(UUID,map(str,(tenant_id,actor_id,entity_id,source_key,correlation_id)))
    if kind not in KINDS or operation not in {'created','updated','deleted'}:
        raise ValueError('invalid mutation')
    if not isinstance(content,dict) or type(expected_version) is not int or expected_version<0:
        raise ValueError('invalid content or version')
    if operation=='deleted' and content:
        raise ValueError('delete payload must be empty')
    # Hash is stored locally only, never sent to Slack. No free text enters audit.
    request_hash=hashlib.sha256(json.dumps([str(tenant_id),str(actor_id),kind,str(entity_id),operation,expected_version,content,str(correlation_id)],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    # Same source key serialized before replay check; entity lock serializes versions.
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(source_key),))
    old=conn.execute('SELECT event_id,request_hash FROM po_audit WHERE source_key=%s',(source_key,)).fetchone()
    if old:
        if old[1]!=request_hash:raise ValueError('idempotency conflict')
        return str(old[0])
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))',(str(tenant_id)+kind+str(entity_id),))
    row=conn.execute('SELECT version,deleted FROM po_entity WHERE tenant_id=%s AND kind=%s AND entity_id=%s FOR UPDATE',(tenant_id,kind,entity_id)).fetchone()
    if operation=='created':
        if row or expected_version!=0:raise ValueError('creation conflict')
        version=1
        conn.execute('INSERT INTO po_entity VALUES(%s,%s,%s,%s,%s,false)',(tenant_id,kind,entity_id,version,Jsonb(content)))
    else:
        if not row or row[1] or row[0]!=expected_version:raise ValueError('version conflict or missing entity')
        version=row[0]+1
        conn.execute('UPDATE po_entity SET version=%s,content=%s,deleted=%s WHERE tenant_id=%s AND kind=%s AND entity_id=%s',(version,Jsonb({} if operation=='deleted' else content),operation=='deleted',tenant_id,kind,entity_id))
    event=uuid4()
    conn.execute('INSERT INTO po_audit(event_id,source_key,correlation_id,tenant_id,actor_id,kind,entity_id,operation,version,request_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(event,source_key,correlation_id,tenant_id,actor_id,kind,entity_id,operation,version,request_hash))
    conn.execute('INSERT INTO po_outbox(event_id) VALUES(%s)',(event,))
    return str(event)
