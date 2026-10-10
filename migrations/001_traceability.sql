-- REVIEW ONLY. Apply explicitly to a dedicated test database first.
BEGIN;
CREATE TABLE trace_work_item (
    id text PRIMARY KEY CHECK (id ~ '^[A-Z][A-Z0-9]{1,15}-[0-9]{3,10}$'),
    kind text NOT NULL CHECK (kind IN ('epic','story','task','subtask')),
    parent_id text REFERENCES trace_work_item(id),
    status text NOT NULL CHECK (status IN ('todo','in_progress','done','blocked')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK ((kind = 'epic') = (parent_id IS NULL))
);
CREATE TABLE trace_audit (
    event_id uuid PRIMARY KEY,
    source_key text NOT NULL UNIQUE,
    correlation_id uuid NOT NULL,
    work_item_id text REFERENCES trace_work_item(id),
    event_type text NOT NULL,
    data jsonb NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX trace_audit_correlation ON trace_audit(correlation_id, occurred_at);
CREATE TABLE trace_outbox (
    event_id uuid PRIMARY KEY REFERENCES trace_audit(event_id),
    channel_id text NOT NULL,
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','sending','sent','uncertain','dead')),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    claimed_at timestamptz,
    slack_ts text,
    error_code text,
    sent_at timestamptz
);
CREATE INDEX trace_outbox_due ON trace_outbox(next_attempt_at) WHERE state = 'pending';
CREATE FUNCTION trace_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'trace_audit is append-only';
END $$;
CREATE TRIGGER trace_audit_no_mutation BEFORE UPDATE OR DELETE ON trace_audit
    FOR EACH ROW EXECUTE FUNCTION trace_audit_immutable();
COMMIT;
