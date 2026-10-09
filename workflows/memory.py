"""Append-only local audit memory; never reads environment secret files."""

import fcntl
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


KINDS = frozenset({"interaction", "action", "decision", "evidence", "status", "handoff"})
REDACTED = "[REDACTED]"
_SECRET = re.compile(r"password|passwd|api[_-]?key|authorization|secret|credentials|token", re.I)
_COUNTS = frozenset({"tokens", "token_count", "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens", "max_tokens"})
_ASSIGNMENT = re.compile(
    r"\b([\w-]*(?:password|passwd|api[_-]?key|authorization|secret|credentials|token)[\w-]*)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)", re.I
)


class MemoryIntegrityError(ValueError):
    """The existing journal is incomplete or fails integrity verification."""


def _redact(value):
    if isinstance(value, dict):
        return {key: REDACTED if _SECRET.search(key) and key.lower() not in _COUNTS
                else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(
            r'"([^"\r\n]+)"\s*:\s*"((?:\\.|[^"\\])*)"',
            lambda match: '"' + match[1] + '":"' + REDACTED + '"'
            if _SECRET.search(match[1]) and match[1].lower() not in _COUNTS else match[0],
            value,
        )
        # Header credentials may contain spaces (Basic/Bearer and other schemes).
        # Mask the complete value, not merely the first word after the colon.
        value = re.sub(
            r"\b((?:Proxy-)?Authorization)(\s*[:=]\s*)[^\r\n,;]+",
            lambda match: match[1] + match[2] + REDACTED, value, flags=re.I,
        )
        value = re.sub(r"\bBearer\s+[^\s,;\"']+", "Bearer " + REDACTED, value, flags=re.I)
        value = re.sub(r"(\b[a-z][a-z0-9+.-]*://[^\s/@:]+:)[^\s/@]+(@)",
                       r"\1" + REDACTED + r"\2", value, flags=re.I)
        return _ASSIGNMENT.sub(lambda match: match[0] if match[1].lower() in _COUNTS
                               else match[1] + match[2] + REDACTED, value)
    return value


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _validate_json(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        for item in value.values():
            _validate_json(item)
    elif isinstance(value, list):
        for item in value:
            _validate_json(item)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("Data must contain JSON values")
    _encode(value)


class MemoryStore:
    """Serialize readers/writers with Linux flock and verify before every append.

    SHA256 detects accidental corruption, not malicious rewriting of the full file.
    Redaction is heuristic: callers must not submit unlabelled secrets.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "events.jsonl"

    def _open(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            # The journal is managed by this store; tighten its existing mode too.
            # Existing root directories keep their owner's chosen permissions.
            os.fchmod(descriptor, 0o600)
            return os.fdopen(descriptor, "a+b")
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _read(handle):
        handle.seek(0)
        events = []
        previous = None
        required = {"id", "schema_version", "recorded_at", "task_id", "kind", "actor",
                    "summary", "data", "source", "prev_hash", "hash"}
        for number, line in enumerate(handle, 1):
            try:
                if not line.endswith(b"\n"):
                    raise ValueError("Incomplete event")
                event = json.loads(line)
                if not isinstance(event, dict) or not required.issubset(event):
                    raise ValueError("Invalid event schema")
                unsigned = {key: value for key, value in event.items() if key != "hash"}
                if (event["schema_version"] != 1 or event["kind"] not in KINDS
                        or event["prev_hash"] != previous
                        or event["hash"] != hashlib.sha256(_encode(unsigned)).hexdigest()):
                    raise ValueError("Invalid event chain")
            except (ValueError, TypeError, UnicodeError, KeyError) as error:
                raise MemoryIntegrityError(f"Journal integrity failure at event {number}") from error
            events.append(event)
            previous = event["hash"]
        return events

    def read_events(self, task_id: str | None = None) -> list[dict]:
        with self._open() as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            events = self._read(handle)
        return events if task_id is None else [event for event in events if event["task_id"] == task_id]

    def verify(self) -> int:
        return len(self.read_events())

    def append(self, *, task_id: str, kind: str, actor: str, summary: str,
               data: dict | None = None, source: str = "agent",
               occurred_at: str | None = None) -> dict:
        for name, value in {"task_id": task_id, "kind": kind, "actor": actor,
                            "summary": summary, "source": source}.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if kind not in KINDS:
            raise ValueError("Unsupported event kind")
        if occurred_at is not None:
            if not isinstance(occurred_at, str):
                raise ValueError("occurred_at must be an ISO timestamp")
            parsed = datetime.fromisoformat(occurred_at)
            if parsed.utcoffset() is None:
                raise ValueError("occurred_at must include a timezone")
        if data is not None and not isinstance(data, dict):
            raise ValueError("data must be a JSON object")
        _validate_json(data)
        event = _redact({"id": str(uuid.uuid4()), "schema_version": 1,
                         "recorded_at": datetime.now(timezone.utc).isoformat(),
                         "task_id": task_id, "kind": kind, "actor": actor,
                         "summary": summary, "data": data or {}, "source": source})
        if occurred_at is not None:
            event["occurred_at"] = occurred_at
        with self._open() as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            events = self._read(handle)
            event["prev_hash"] = events[-1]["hash"] if events else None
            event["hash"] = hashlib.sha256(_encode(event)).hexdigest()
            handle.seek(0, 2)
            handle.write(_encode(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event
