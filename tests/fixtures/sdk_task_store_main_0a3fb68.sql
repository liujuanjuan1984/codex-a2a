-- Synthetic task snapshot generated from main 0a3fb68 with a2a-sdk 1.1.5.
BEGIN TRANSACTION;
CREATE TABLE tasks (
	id VARCHAR(36) NOT NULL,
	context_id VARCHAR(36) NOT NULL,
	kind VARCHAR(16) NOT NULL,
	owner VARCHAR(255),
	last_updated DATETIME,
	status JSON NOT NULL,
	artifacts JSON,
	history JSON,
	protocol_version VARCHAR(16),
	metadata JSON,
	PRIMARY KEY (id)
);
INSERT INTO "tasks" VALUES('task','context','task','',NULL,'{"state": "TASK_STATE_COMPLETED"}','[]','[{"messageId": "existing", "role": "ROLE_USER"}]','1.0','null');
CREATE INDEX ix_tasks_id ON tasks (id);
CREATE INDEX idx_tasks_owner_last_updated ON tasks (owner, last_updated);
COMMIT;
