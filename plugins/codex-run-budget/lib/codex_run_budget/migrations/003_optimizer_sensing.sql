ALTER TABLE turns ADD COLUMN health_epoch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE turns ADD COLUMN issue_code TEXT;
UPDATE turns SET limited=1, check_sample=0, issue_code='legacy_coverage';
CREATE TABLE observation_meta (
    id INTEGER PRIMARY KEY CHECK(id=1), health_epoch INTEGER NOT NULL
);
INSERT INTO observation_meta VALUES(1,0);
PRAGMA user_version=2;
