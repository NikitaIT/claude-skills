-- Tables (data comes from CSV files)
CREATE TABLE backlog (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT,
    cause_id INTEGER,
    feature_file TEXT,
    doc TEXT
);

CREATE TABLE sprint (
    id INTEGER PRIMARY KEY,
    goal TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE sprint_backlog (
    pbi_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    feature_file TEXT,
    doc TEXT,
    cause_id INTEGER
);

CREATE TABLE sprint_log (
    pbi_id INTEGER,
    title TEXT,
    sprint_id INTEGER,
    done_at TEXT,
    cause_id INTEGER,
    feature_file TEXT,
    doc TEXT,
    outcome TEXT  -- NULL=done, 'effective', 'ineffective'
);

CREATE TABLE rejected_backlog (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT,
    cause_id INTEGER,
    feature_file TEXT,
    doc TEXT
);

CREATE TABLE agent_log (
    pbi_id INTEGER,
    sprint_id INTEGER,
    agent TEXT,          -- dev-1..dev-5
    duration_ms INTEGER, -- wall clock time
    total_tokens INTEGER,
    tool_uses INTEGER,
    status TEXT           -- done, failed, retried
);

-- Views
CREATE VIEW current_sprint AS
SELECT * FROM sprint WHERE ended_at IS NULL OR ended_at = '';

CREATE VIEW dev_sprint_board AS
SELECT pbi_id, title, feature_file, doc FROM sprint_backlog;

CREATE VIEW po_backlog AS
SELECT id, title, status, cause_id, feature_file, doc FROM backlog ORDER BY id;

CREATE VIEW po_throughput AS
SELECT sprint_id, COUNT(*) AS items_done FROM sprint_log GROUP BY sprint_id;

CREATE VIEW sm_sprint_health AS
SELECT
    s.id AS sprint_id, s.goal, s.started_at,
    (SELECT COUNT(*) FROM sprint_backlog) AS items_in_sprint,
    (SELECT COUNT(*) FROM sprint_log sl WHERE sl.sprint_id = s.id) AS items_done
FROM sprint s
WHERE s.ended_at IS NULL OR s.ended_at = '';

-- SM: agent efficiency per sprint
CREATE VIEW sm_agent_cost AS
SELECT
    sprint_id,
    COUNT(*) AS pbis,
    SUM(duration_ms) / 1000 AS total_seconds,
    SUM(total_tokens) AS total_tokens,
    SUM(tool_uses) AS total_tool_uses,
    AVG(duration_ms) / 1000 AS avg_seconds_per_pbi,
    AVG(total_tokens) AS avg_tokens_per_pbi,
    AVG(tool_uses) AS avg_tools_per_pbi
FROM agent_log
WHERE status = 'done'
GROUP BY sprint_id;

-- SM: capacity utilization per sprint
CREATE VIEW sm_capacity AS
SELECT
    sprint_id,
    COUNT(DISTINCT agent) AS agents_used,
    5 AS agents_available,
    ROUND(COUNT(DISTINCT agent) * 100.0 / 5) AS utilization_pct
FROM agent_log
GROUP BY sprint_id;

-- SM: impediments (failures)
CREATE VIEW sm_impediments AS
SELECT sprint_id, pbi_id, agent, status, duration_ms / 1000 AS seconds
FROM agent_log
WHERE status != 'done';
