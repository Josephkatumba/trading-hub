-- Initial commercial schema, version 1. Generated from commercial_store.metadata.
BEGIN;
CREATE TABLE schema_migrations (
	version SERIAL NOT NULL,
	PRIMARY KEY (version)
);
CREATE TABLE users (
	id VARCHAR(36) NOT NULL,
	issuer VARCHAR(512) NOT NULL,
	subject VARCHAR(255) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_oidc_identity UNIQUE (issuer, subject)
);
CREATE TABLE entitlements (
	user_id VARCHAR(36) NOT NULL,
	plan VARCHAR(16) NOT NULL,
	expires_at BIGINT NOT NULL,
	PRIMARY KEY (user_id),
	CONSTRAINT valid_plan CHECK (plan IN ('free', 'pro')),
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE TABLE journal_records (
	user_id VARCHAR(36) NOT NULL,
	kind VARCHAR(16) NOT NULL,
	record_id VARCHAR(160) NOT NULL,
	payload JSON NOT NULL,
	version INTEGER NOT NULL,
	updated_at BIGINT NOT NULL,
	PRIMARY KEY (user_id, kind, record_id),
	CONSTRAINT valid_journal_kind CHECK (kind IN ('trade', 'account', 'review')),
	CONSTRAINT positive_version CHECK (version >= 1),
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE TABLE user_sessions (
	token_hash VARCHAR(64) NOT NULL,
	user_id VARCHAR(36) NOT NULL,
	csrf VARCHAR(64) NOT NULL,
	expires_at BIGINT NOT NULL,
	PRIMARY KEY (token_hash),
	FOREIGN KEY(user_id) REFERENCES users (id)
);
INSERT INTO schema_migrations(version) VALUES (1);
COMMIT;
