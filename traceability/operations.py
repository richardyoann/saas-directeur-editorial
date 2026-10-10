"""Read delivery status and reconcile ambiguous sends using Slack evidence."""
import argparse
import os
import re
from uuid import UUID

import httpx

from traceability.store import connect


def reconcile(event_id, ts):
    event_id = str(UUID(event_id))
    if not re.fullmatch(r'[0-9]+\.[0-9]+',ts):
        raise ValueError('invalid Slack timestamp')
    token = os.environ['TRACE_SLACK_BOT_TOKEN']
    with connect() as conn:
        row = conn.execute('SELECT channel_id,state FROM trace_outbox WHERE event_id=%s',(event_id,)).fetchone()
    if not row or row['state'] != 'uncertain':
        raise ValueError('event is not uncertain')
    with httpx.Client(timeout=20,trust_env=False,follow_redirects=False) as client:
        response = client.get('https://slack.com/api/conversations.history',
            headers={'Authorization':'Bearer '+token},
            params={'channel':row['channel_id'],'oldest':ts,'latest':ts,'inclusive':'true','limit':1,'include_all_metadata':'true'})
        response.raise_for_status()
        body = response.json()
    messages = body.get('messages',[]) if body.get('ok') is True else []
    if len(messages) != 1 or messages[0].get('ts') != ts or messages[0].get('metadata',{}).get('event_payload',{}).get('event_id') != event_id:
        raise ValueError('Slack evidence did not match; no state changed')
    with connect() as conn:
        conn.execute("UPDATE trace_outbox SET state='sent',slack_ts=%s,sent_at=now(),error_code=NULL WHERE event_id=%s AND state='uncertain'",(ts,event_id))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    confirmed = sub.add_parser('confirm-sent')
    confirmed.add_argument('event_id')
    confirmed.add_argument('slack_ts')
    retry = sub.add_parser('retry')
    retry.add_argument('event_id')
    retry.add_argument('--acknowledge-duplicate-risk',action='store_true')
    args = parser.parse_args()
    if args.command == 'status':
        with connect() as conn:
            for row in conn.execute('SELECT state,count(*) AS n FROM trace_outbox GROUP BY state ORDER BY state'):
                print(row['state'],row['n'])
    elif args.command == 'confirm-sent':
        reconcile(args.event_id,args.slack_ts)
        print('Slack evidence confirmed')
    elif not args.acknowledge_duplicate_risk:
        parser.error('Inspect Slack first; explicit duplicate-risk acknowledgement required')
    else:
        with connect() as conn:
            conn.execute("UPDATE trace_outbox SET state='pending',attempts=0,next_attempt_at=now(),error_code=NULL "
                         "WHERE event_id=%s AND state IN ('uncertain','dead')",(UUID(args.event_id),))
        print('Explicit retry scheduled')


if __name__ == '__main__':
    main()
