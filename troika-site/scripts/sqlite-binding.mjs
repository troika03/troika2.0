import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
export function databaseBinding(filename = ':memory:') {
  const db = new DatabaseSync(filename);
  db.exec('PRAGMA foreign_keys=ON');
  const exists = db.prepare("SELECT name FROM sqlite_master WHERE name='support_tickets'").get();
  if (!exists) db.exec(readFileSync('drizzle/0000_support.sql','utf8').replaceAll('--> statement-breakpoint',''));
  const wrap = (sql, args = []) => ({
    bind: (...values) => wrap(sql, values),
    first: async () => db.prepare(sql).get(...args) || null,
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    run: async () => db.prepare(sql).run(...args),
  });
  return { prepare: sql => wrap(sql), batch: async statements => { db.exec('BEGIN'); try { const result = await Promise.all(statements.map(s => s.run())); db.exec('COMMIT'); return result; } catch(error) { db.exec('ROLLBACK'); throw error; } }, close: () => db.close() };
}
