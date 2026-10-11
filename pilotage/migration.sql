-- REVIEW ONLY: apply solely to an explicitly approved database.
BEGIN;
CREATE TABLE IF NOT EXISTS po_entity (
 tenant_id uuid NOT NULL, kind text NOT NULL CHECK(kind IN ('prompt','treatment','scenario','scene','result')),
 entity_id uuid NOT NULL, version integer NOT NULL CHECK(version>0),
 content jsonb NOT NULL, deleted boolean NOT NULL DEFAULT false,
 PRIMARY KEY(tenant_id,kind,entity_id)
);
CREATE TABLE IF NOT EXISTS po_audit (
 event_id uuid PRIMARY KEY, source_key uuid NOT NULL UNIQUE, correlation_id uuid NOT NULL,
 tenant_id uuid NOT NULL, actor_id uuid NOT NULL, kind text NOT NULL,
 entity_id uuid NOT NULL, operation text NOT NULL CHECK(operation IN ('created','updated','deleted')),
 version integer NOT NULL, request_hash text NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS po_batch (
 batch_id uuid PRIMARY KEY, state text NOT NULL DEFAULT 'pending'
 CHECK(state IN ('pending','sending','sent','uncertain','dead')),
 attempts integer NOT NULL DEFAULT 0, due_at timestamptz NOT NULL DEFAULT now(),
 claimed_at timestamptz, slack_ts text, error_code text
);
CREATE TABLE IF NOT EXISTS po_outbox (
 event_id uuid PRIMARY KEY REFERENCES po_audit(event_id),
 batch_id uuid REFERENCES po_batch(batch_id), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION po_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'append-only audit'; END $$;
CREATE OR REPLACE TRIGGER po_audit_no_mutation BEFORE UPDATE OR DELETE ON po_audit
 FOR EACH ROW EXECUTE FUNCTION po_audit_immutable();
COMMIT;
