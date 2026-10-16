PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS support_tickets (
  id TEXT PRIMARY KEY, owner_key TEXT NOT NULL, email TEXT NOT NULL,
  category TEXT NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS support_owner ON support_tickets(owner_key, created_at);
CREATE TABLE IF NOT EXISTS support_replies (
  id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
  author TEXT NOT NULL, message TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS support_reply_ticket ON support_replies(ticket_id, created_at);
CREATE TABLE IF NOT EXISTS site_rate_limits (
  key TEXT NOT NULL, bucket INTEGER NOT NULL, used INTEGER NOT NULL,
  PRIMARY KEY(key, bucket)
);
