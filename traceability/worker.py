"""Bounded retries; ambiguous deliveries require reconciliation, never blind resend."""
import os
from datetime import timedelta

import httpx

from traceability.events import slack_payload
from traceability.store import connect

MAX_ATTEMPTS = 8


def outcome(response):
    if response.status_code == 429:
        try:
            delay = max(1, min(86400, int(response.headers.get('Retry-After', '60'))))
        except ValueError:
            delay = 60
        return 'pending', 'rate_limited', delay, None
    # Slack may have accepted before a gateway returned 5xx: reconcile first.
    if response.status_code >= 500:
        return 'uncertain', 'http_5xx', 0, None
    if response.status_code != 200:
        return 'dead', 'http_rejected', 0, None
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError()
        if body.get('ok') is True:
            ts = body.get('ts')
            if not isinstance(ts, str) or not ts.replace('.', '').isdigit():
                raise ValueError()
            return 'sent', None, 0, ts
        error = body.get('error')
        if error in {'ratelimited'}:
            return 'pending', 'rate_limited', 60, None
        if error in {'internal_error', 'fatal_error', 'request_timeout'}:
            return 'uncertain', 'slack_ambiguous', 0, None
        return 'dead', 'slack_rejected', 0, None
    except (ValueError, TypeError):
        return 'uncertain', 'invalid_response', 0, None


def deliver(client, row, token):
    try:
        return outcome(client.post('https://slack.com/api/chat.postMessage',
                                   headers={'Authorization':'Bearer '+token}, json=slack_payload(row)))
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        return 'pending', 'connect_failed', 0, None
    except httpx.HTTPError:
        return 'uncertain', 'transport_ambiguous', 0, None


def run_once():
    token = os.environ.get('TRACE_SLACK_BOT_TOKEN')
    if not token:
        raise RuntimeError('TRACE_SLACK_BOT_TOKEN required')
    with connect() as conn:
        # A crash after claim is conservatively uncertain, even before actual HTTP.
        conn.execute("UPDATE trace_outbox SET state='uncertain',error_code='lease_expired' "
                     "WHERE state='sending' AND claimed_at < now() - interval '5 minutes'")
        row = conn.execute(
            "SELECT o.*,a.correlation_id,a.event_type,a.work_item_id,a.data FROM trace_outbox o "
            "JOIN trace_audit a USING(event_id) WHERE o.state='pending' AND o.next_attempt_at <= now() "
            "ORDER BY o.next_attempt_at,o.event_id FOR UPDATE OF o SKIP LOCKED LIMIT 1"
        ).fetchone()
        if not row:
            return False
        conn.execute("UPDATE trace_outbox SET state='sending',claimed_at=now(),attempts=attempts+1 WHERE event_id=%s", (row['event_id'],))
    # Claim committed before HTTP; no other worker may send this event.
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), trust_env=False, follow_redirects=False) as client:
            state, error, delay, ts = deliver(client, row, token)
    except (ValueError, TypeError):
        state, error, delay, ts = 'dead', 'invalid_metadata', 0, None
    attempts = row['attempts'] + 1
    if state == 'pending' and attempts >= MAX_ATTEMPTS:
        state, error = 'dead', 'attempts_exhausted'
    delay = max(delay, min(3600, 2 ** attempts))
    with connect() as conn:
        conn.execute("UPDATE trace_outbox SET state=%s,error_code=%s,slack_ts=%s,"
                     "next_attempt_at=now()+%s,sent_at=CASE WHEN %s='sent' THEN now() ELSE NULL END "
                     "WHERE event_id=%s AND state='sending'",
                     (state,error,ts,timedelta(seconds=delay),state,row['event_id']))
    return True


if __name__ == '__main__':
    # Cron/process supervisor may invoke this bounded worker; no infinite daemon.
    for _ in range(100):
        if not run_once():
            break
