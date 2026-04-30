PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS agent_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at TEXT NOT NULL,
  tool TEXT NOT NULL,
  event TEXT NOT NULL,
  source TEXT NOT NULL,
  session_id TEXT,
  turn_id TEXT,
  cwd TEXT,
  transcript_path TEXT,
  model TEXT,
  permission_mode TEXT,
  workspace_title TEXT,
  normalized_title TEXT,
  workspace_id TEXT,
  workspace_ref TEXT,
  workspace_index INTEGER,
  surface_id TEXT,
  surface_ref TEXT,
  tab_id TEXT,
  pane_id TEXT,
  process_title TEXT,
  tty TEXT,
  payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_events_session
  ON agent_events(tool, session_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_events_title
  ON agent_events(normalized_title, observed_at DESC);

CREATE TABLE IF NOT EXISTS session_bindings (
  tool TEXT NOT NULL,
  session_id TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  last_event TEXT NOT NULL,
  last_source TEXT NOT NULL,
  cwd TEXT,
  transcript_path TEXT,
  model TEXT,
  permission_mode TEXT,
  workspace_title TEXT,
  normalized_title TEXT,
  workspace_id TEXT,
  workspace_ref TEXT,
  workspace_index INTEGER,
  surface_id TEXT,
  surface_ref TEXT,
  tab_id TEXT,
  pane_id TEXT,
  process_title TEXT,
  tty TEXT,
  payload_json TEXT,
  PRIMARY KEY (tool, session_id)
);

CREATE INDEX IF NOT EXISTS idx_session_bindings_title
  ON session_bindings(normalized_title, last_seen DESC);

CREATE INDEX IF NOT EXISTS idx_session_bindings_workspace
  ON session_bindings(workspace_id, surface_id, last_seen DESC);

CREATE TABLE IF NOT EXISTS observed_workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at TEXT NOT NULL,
  source TEXT NOT NULL,
  window_id TEXT,
  window_ref TEXT,
  workspace_id TEXT,
  workspace_ref TEXT,
  workspace_index INTEGER,
  workspace_title TEXT,
  normalized_title TEXT,
  current_directory TEXT,
  process_title TEXT,
  selected INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  pane_id TEXT,
  pane_ref TEXT,
  surface_id TEXT,
  surface_ref TEXT,
  surface_index INTEGER,
  surface_title TEXT,
  tty TEXT,
  snapshot_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_observed_workspaces_title
  ON observed_workspaces(normalized_title, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_observed_workspaces_ids
  ON observed_workspaces(workspace_id, surface_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS restore_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at TEXT NOT NULL,
  action TEXT NOT NULL,
  status TEXT NOT NULL,
  workspace_title TEXT,
  normalized_title TEXT,
  workspace_id TEXT,
  surface_id TEXT,
  selected_tool TEXT,
  selected_session_id TEXT,
  score INTEGER,
  command TEXT,
  details_json TEXT
);

