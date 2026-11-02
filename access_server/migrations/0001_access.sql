CREATE TABLE devices (
  device_id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','revoked')),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  last_seen INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX devices_updated ON devices(updated_at DESC);
CREATE TABLE admin_sessions (
  token_hash TEXT PRIMARY KEY,
  expires_at INTEGER NOT NULL
);
CREATE TABLE rate_limits (
  bucket TEXT PRIMARY KEY,
  count INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
