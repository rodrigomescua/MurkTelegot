import json
import os
import re
from contextlib import contextmanager
import sqlite3
import unicodedata
from pathlib import Path


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def matches(text, keywords):
    text = normalize(text)
    return any(re.search(r'(?<!\w)' + re.escape(normalize(word.strip())) + r'(?!\w)', text)
               for word in keywords.split(',') if word.strip())


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            columns = {r['name'] for r in db.execute('PRAGMA table_info(offers)')}
            if columns and not {'source_json', 'grouped_id'} <= columns:
                backup = Path(str(path) + '.before-rich-messages.db')
                if not backup.exists():
                    temporary = Path(str(backup) + '.tmp')
                    try:
                        snapshot = sqlite3.connect(temporary)
                        try:
                            db.backup(snapshot)
                        finally:
                            snapshot.close()
                        os.replace(temporary, backup)
                    finally:
                        temporary.unlink(missing_ok=True)
            db.executescript('''
                CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, keywords TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS offers (
                    id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                    chat_title TEXT NOT NULL, body TEXT NOT NULL, url TEXT,
                    date TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0,
                    source_json TEXT, grouped_id TEXT,
                    UNIQUE(chat_id, message_id));
                CREATE TABLE IF NOT EXISTS hits (
                    offer_id INTEGER NOT NULL REFERENCES offers(id),
                    rule_id INTEGER NOT NULL REFERENCES rules(id),
                    PRIMARY KEY(offer_id, rule_id));
            ''')
            if columns:
                db.execute('BEGIN')
                for name in ('source_json', 'grouped_id'):
                    if name not in columns:
                        db.execute(f'ALTER TABLE offers ADD COLUMN {name} TEXT')
            db.execute('CREATE INDEX IF NOT EXISTS offers_album ON offers(chat_id, grouped_id, message_id)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def ingest(self, chat_id, message_id, body, date, url, *, source_json=None):
        grouped = json.loads(source_json).get('grouped_id') if source_json else None
        with self.connect() as db:
            chat = db.execute('SELECT title FROM chats WHERE id=?', (chat_id,)).fetchone()
            if not chat or (not body and not source_json):
                return
            db.execute('''INSERT INTO offers(chat_id,message_id,chat_title,body,date,url,source_json,grouped_id)
                          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(chat_id,message_id)
                          DO UPDATE SET body=excluded.body,url=excluded.url,
                          source_json=excluded.source_json,grouped_id=excluded.grouped_id''',
                       (chat_id, message_id, chat['title'], body or '', date, url, source_json,
                        str(grouped) if grouped is not None else None))
            offer_id = db.execute('SELECT id FROM offers WHERE chat_id=? AND message_id=?',
                                  (chat_id, message_id)).fetchone()['id']
            db.execute('DELETE FROM hits WHERE offer_id=?', (offer_id,))
            for rule in db.execute('SELECT * FROM rules').fetchall():
                if matches(body or '', rule['keywords']):
                    db.execute('INSERT INTO hits VALUES(?,?)', (offer_id, rule['id']))
            return offer_id

    def feed(self, q='', alerts=False):
        clauses, args = [], []
        if alerts:
            clauses.append('EXISTS(SELECT 1 FROM hits WHERE offer_id=o.id)')
        if q:
            clauses.append("body LIKE ? ESCAPE '\\'")
            args.append('%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
        where = 'WHERE ' + ' AND '.join(clauses) if clauses else ''
        select = '''SELECT o.*, (SELECT group_concat(r.name, ', ') FROM hits h
                    JOIN rules r ON r.id=h.rule_id WHERE h.offer_id=o.id) AS rules FROM offers o '''
        selected = self.rows(select + where + ' ORDER BY date DESC,id DESC LIMIT 100', args)
        keys = {(r['chat_id'], r['grouped_id']) for r in selected if r['grouped_id']}
        albums = {}
        if keys:
            members = self.rows(select + 'WHERE ' + ' OR '.join('(chat_id=? AND grouped_id=?)' for _ in keys)
                                + ' ORDER BY message_id', [value for key in keys for value in key])
            for member in members:
                albums.setdefault((member['chat_id'], member['grouped_id']), []).append(member)
        cards, added = [], set()
        for offer in selected:
            key = (offer['chat_id'], offer['grouped_id']) if offer['grouped_id'] else ('message', offer['id'])
            if key in added:
                continue
            added.add(key)
            parts = albums.get(key, [offer])
            cards.append({**parts[0], 'parts': parts,
                          'rules': ', '.join(dict.fromkeys(p['rules'] for p in parts if p['rules'])),
                          'seen': all(p['seen'] for p in parts if p['rules'])})
        return cards

    def unread(self):
        return self.rows('''SELECT count(*) AS n FROM (
            SELECT chat_id,coalesce(grouped_id,'message-' || id) FROM offers
            WHERE seen=0 AND EXISTS(SELECT 1 FROM hits WHERE offer_id=offers.id)
            GROUP BY chat_id,coalesce(grouped_id,'message-' || id))''')[0]['n']

    def mark_seen(self, offer_id):
        with self.connect() as db:
            db.execute('''UPDATE offers SET seen=1 WHERE id=? OR
                (chat_id,grouped_id) IN (SELECT chat_id,grouped_id FROM offers WHERE id=? AND grouped_id IS NOT NULL)''',
                       (offer_id, offer_id))
