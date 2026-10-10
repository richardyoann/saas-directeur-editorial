"""Only structured, bounded metadata reaches audit/Slack. No free-text payloads."""
import hashlib
import json
import re
from uuid import UUID

ITEM_ID = re.compile(r'^[A-Z][A-Z0-9]{1,15}-[0-9]{3,10}$')
KINDS = ('epic', 'story', 'task', 'subtask')
STATUSES = ('todo', 'in_progress', 'done', 'blocked')


def safe_data(event_type, data):
    schemas = {
        'work_item.created': {'kind', 'parent_id', 'status', 'version'},
        'work_item.updated': {'kind', 'parent_id', 'status', 'version'},
        'generation.requested': {'status_code'},
        'generation.completed': {'status_code'},
        'generation.failed': {'status_code'},
        'github.pull_request': {'number', 'action', 'merged', 'work_item_ids'},
    }
    if event_type not in schemas or set(data) - schemas[event_type]:
        raise ValueError('unsupported event fields')
    clean = {}
    for key, value in data.items():
        if key == 'kind' and value in KINDS:
            clean[key] = value
        elif key == 'status' and value in STATUSES:
            clean[key] = value
        elif key == 'parent_id' and (value is None or isinstance(value, str) and ITEM_ID.fullmatch(value)):
            clean[key] = value
        elif key in {'number', 'version', 'status_code'} and type(value) is int and 0 <= value <= 2147483647:
            clean[key] = value
        elif key == 'merged' and type(value) is bool:
            clean[key] = value
        elif key == 'action' and value in {'opened','closed','reopened','synchronize','edited','ready_for_review','converted_to_draft'}:
            clean[key] = value
        elif key == 'work_item_ids' and isinstance(value, list) and len(value) <= 50 and all(isinstance(v, str) and ITEM_ID.fullmatch(v) for v in value):
            clean[key] = sorted(set(value))
        else:
            raise ValueError('invalid event metadata')
    return clean


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def slack_payload(row):
    event_id = str(UUID(str(row['event_id'])))
    data = safe_data(row['event_type'], row['data'])
    item = row['work_item_id'] or 'business'
    if item != 'business' and not ITEM_ID.fullmatch(item):
        raise ValueError('invalid work item')
    return {
        'channel': row['channel_id'], 'client_msg_id': event_id,
        'text': f"{row['event_type']} | {item} | event={event_id} | correlation={UUID(str(row['correlation_id']))} | {json.dumps(data, sort_keys=True)}",
        'metadata': {'event_type': 'editorial_trace', 'event_payload': {'event_id': event_id}},
        'unfurl_links': False, 'unfurl_media': False,
    }
