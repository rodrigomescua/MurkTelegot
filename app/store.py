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
            db.executescript('''
                CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, keywords TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS offers (
                    id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                    chat_title TEXT NOT NULL, body TEXT NOT NULL, url TEXT,
                    date TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(chat_id, message_id));
                CREATE TABLE IF NOT EXISTS hits (
                    offer_id INTEGER NOT NULL REFERENCES offers(id),
                    rule_id INTEGER NOT NULL REFERENCES rules(id),
                    PRIMARY KEY(offer_id, rule_id));
            ''')

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

    def ingest(self, chat_id, message_id, body, date, url):
        with self.connect() as db:
            chat = db.execute('SELECT title FROM chats WHERE id=?', (chat_id,)).fetchone()
            if not chat or not body:
                return
            db.execute('''INSERT INTO offers(chat_id,message_id,chat_title,body,date,url)
                          VALUES(?,?,?,?,?,?) ON CONFLICT(chat_id,message_id)
                          DO UPDATE SET body=excluded.body,url=excluded.url''',
                       (chat_id, message_id, chat['title'], body, date, url))
            offer_id = db.execute('SELECT id FROM offers WHERE chat_id=? AND message_id=?',
                                  (chat_id, message_id)).fetchone()['id']
            db.execute('DELETE FROM hits WHERE offer_id=?', (offer_id,))
            for rule in db.execute('SELECT * FROM rules').fetchall():
                if matches(body, rule['keywords']):
                    db.execute('INSERT INTO hits VALUES(?,?)', (offer_id, rule['id']))
