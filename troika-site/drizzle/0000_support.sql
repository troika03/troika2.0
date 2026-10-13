CREATE TABLE support_tickets (
  id TEXT PRIMARY KEY NOT NULL,
  owner_key TEXT NOT NULL,
  email TEXT NOT NULL,
  category TEXT NOT NULL,
  subject TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
--> statement-breakpoint
CREATE INDEX support_owner_created ON support_tickets(owner_key, created_at);
--> statement-breakpoint
CREATE TABLE support_replies (
  id TEXT PRIMARY KEY NOT NULL,
  ticket_id TEXT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
  author TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
--> statement-breakpoint
CREATE INDEX support_reply_ticket ON support_replies(ticket_id, created_at);
--> statement-breakpoint
CREATE TABLE site_rate_limits (
  key TEXT NOT NULL,
  bucket INTEGER NOT NULL,
  used INTEGER NOT NULL,
  PRIMARY KEY (key, bucket)
);
