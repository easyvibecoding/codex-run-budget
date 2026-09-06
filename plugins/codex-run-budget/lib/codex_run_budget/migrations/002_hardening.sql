CREATE TABLE IF NOT EXISTS source_health (
    run_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (run_id, epoch, source_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_slots (
    run_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    tool_use_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','started','released','expired')),
    agent_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (run_id, epoch, tool_use_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS agent_slots_pending_idx
    ON agent_slots(run_id, epoch, status, created_at);

CREATE TABLE IF NOT EXISTS tool_results (
    run_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    tool_use_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    at REAL NOT NULL,
    PRIMARY KEY (run_id, epoch, tool_use_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS tool_results_fingerprint_idx
    ON tool_results(run_id, epoch, source_id, input_hash, at);
