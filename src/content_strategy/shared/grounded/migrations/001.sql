CREATE TABLE IF NOT EXISTS grounded_meta(edition TEXT PRIMARY KEY, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS grounded_versions(
 namespace TEXT NOT NULL, item_id TEXT NOT NULL, revision INTEGER NOT NULL,
 content_json TEXT NOT NULL, content_hash TEXT NOT NULL, generation TEXT NOT NULL,
 PRIMARY KEY(namespace,item_id,revision));
CREATE TABLE IF NOT EXISTS grounded_events(
 namespace TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL,
 action TEXT NOT NULL, item_id TEXT, revision INTEGER, payload TEXT NOT NULL,
 PRIMARY KEY(namespace,sequence), UNIQUE(namespace,event_id));
CREATE TABLE IF NOT EXISTS grounded_receipts(
 namespace TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 receipt_json TEXT NOT NULL, markdown BLOB NOT NULL, csv BLOB NOT NULL, request_json TEXT NOT NULL,
 PRIMARY KEY(namespace,idempotency_key));
CREATE TRIGGER IF NOT EXISTS grounded_meta_no_update BEFORE UPDATE ON grounded_meta BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_meta_no_delete BEFORE DELETE ON grounded_meta BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_versions_no_update BEFORE UPDATE ON grounded_versions BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_versions_no_delete BEFORE DELETE ON grounded_versions BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_events_no_update BEFORE UPDATE ON grounded_events BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_events_no_delete BEFORE DELETE ON grounded_events BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_receipts_no_update BEFORE UPDATE ON grounded_receipts BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_receipts_no_delete BEFORE DELETE ON grounded_receipts BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_meta_no_replace BEFORE INSERT ON grounded_meta WHEN EXISTS(SELECT 1 FROM grounded_meta WHERE edition=NEW.edition) BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_versions_no_replace BEFORE INSERT ON grounded_versions WHEN EXISTS(SELECT 1 FROM grounded_versions WHERE namespace=NEW.namespace AND item_id=NEW.item_id AND revision=NEW.revision) BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_events_no_replace BEFORE INSERT ON grounded_events WHEN EXISTS(SELECT 1 FROM grounded_events WHERE namespace=NEW.namespace AND (sequence=NEW.sequence OR event_id=NEW.event_id)) BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS grounded_receipts_no_replace BEFORE INSERT ON grounded_receipts WHEN EXISTS(SELECT 1 FROM grounded_receipts WHERE namespace=NEW.namespace AND idempotency_key=NEW.idempotency_key) BEGIN SELECT RAISE(ABORT,'append_only'); END;
