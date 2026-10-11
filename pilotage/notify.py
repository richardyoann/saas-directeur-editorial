"""One metadata-only digest per bounded run, minimum 60s aggregation window."""
import os
from collections import Counter
from datetime import timedelta
from uuid import uuid4
import httpx
import psycopg

CHANNEL='C0C883XR3DF'
WORKSPACE='T0C7ZUAM4DR'

def payload(batch_id, events):
    counts=Counter((kind,op) for kind,op in events)
    if any(k not in {'prompt','treatment','scenario','scene','result'} or op not in {'created','updated','deleted'} for k,op in counts):
        raise ValueError('unsupported metadata')
    return dict(channel=CHANNEL,client_msg_id=str(batch_id),text='SaaS audit | lot='+str(batch_id)+' | '+', '.join(f'{k}.{op}={n}' for (k,op),n in sorted(counts.items())),unfurl_links=False,unfurl_media=False)

def classify(response):
    if response.status_code==429:
        try: delay=max(1,min(86400,int(response.headers.get('Retry-After','60'))))
        except ValueError:delay=60
        return 'pending','rate_limit',delay,None
    if response.status_code>=500:return 'uncertain','server_ambiguous',0,None
    if response.status_code!=200:return 'dead','http_rejected',0,None
    try:
        body=response.json()
        if not isinstance(body,dict):raise ValueError()
        if body.get('ok') is True and isinstance(body.get('ts'),str) and body['ts'].replace('.','').isdigit():
            return 'sent',None,0,body['ts']
        if body.get('error')=='ratelimited':return 'pending','rate_limit',60,None
        if body.get('error') in {'internal_error','request_timeout','fatal_error'}:return 'uncertain','ack_ambiguous',0,None
        return 'dead','slack_rejected',0,None
    except (ValueError,TypeError):return 'uncertain','invalid_ack',0,None

def once():
    token=os.environ.get('TRACE_SLACK_BOT_TOKEN')
    if not token:raise RuntimeError('bot configuration missing')
    with httpx.Client(timeout=10,trust_env=False,follow_redirects=False) as client:
        # Connector access is not worker access: verify the token's actual workspace.
        auth=client.post('https://slack.com/api/auth.test',headers={'Authorization':'Bearer '+token})
        if auth.status_code!=200 or auth.json().get('team_id')!=WORKSPACE or auth.json().get('ok') is not True:
            raise RuntimeError('workspace not verified')
        with psycopg.connect(os.environ['PO_DATABASE_URL'],connect_timeout=5) as conn:
            # Serialize digest allocation globally to enforce maximum one new batch/minute.
            conn.execute('SELECT pg_advisory_xact_lock(1411435489)')
            conn.execute("UPDATE po_batch SET state='uncertain',error_code='lease_expired' WHERE state='sending' AND claimed_at<now()-interval '5 minutes'")
            recent=conn.execute("SELECT 1 FROM po_batch WHERE claimed_at>now()-interval '60 seconds' LIMIT 1").fetchone()
            if recent:return False
            row=conn.execute("SELECT batch_id,attempts FROM po_batch WHERE state='pending' AND due_at<=now() ORDER BY due_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if not row:
                events=conn.execute("SELECT event_id FROM po_outbox WHERE batch_id IS NULL AND created_at<now()-interval '60 seconds' ORDER BY created_at LIMIT 100 FOR UPDATE SKIP LOCKED").fetchall()
                if not events:return False
                batch=uuid4()
                conn.execute('INSERT INTO po_batch(batch_id) VALUES(%s)',(batch,))
                conn.execute('UPDATE po_outbox SET batch_id=%s WHERE event_id=ANY(%s)',(batch,[x[0] for x in events]))
                row=(batch,0)
            batch,attempts=row
            events=conn.execute('SELECT a.kind,a.operation FROM po_outbox o JOIN po_audit a USING(event_id) WHERE o.batch_id=%s',(batch,)).fetchall()
            conn.execute("UPDATE po_batch SET state='sending',attempts=attempts+1,claimed_at=now() WHERE batch_id=%s",(batch,))
        try:
            result=classify(client.post('https://slack.com/api/chat.postMessage',headers={'Authorization':'Bearer '+token},json=payload(batch,events)))
        except (httpx.ConnectError,httpx.ConnectTimeout,httpx.PoolTimeout):result=('pending','connect_failed',0,None)
        except httpx.HTTPError:result=('uncertain','transport_ambiguous',0,None)
        state,code,delay,ts=result
        if state=='pending' and attempts>=7:state,code='dead','attempts_exhausted'
        delay=max(delay,min(3600,2**(attempts+1)))
        with psycopg.connect(os.environ['PO_DATABASE_URL'],connect_timeout=5) as conn:
            conn.execute("UPDATE po_batch SET state=%s,error_code=%s,slack_ts=%s,due_at=now()+%s WHERE batch_id=%s AND state='sending'",(state,code,ts,timedelta(seconds=delay),batch))
        return True

if __name__=='__main__':once()
