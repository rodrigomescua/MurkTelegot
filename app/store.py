import json
import os
import re
import secrets
from contextlib import contextmanager
import sqlite3
import unicodedata
from datetime import datetime, timezone, timedelta
from collections import Counter
from pathlib import Path


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def matches(text, keywords):
    text = normalize(text)
    return any(re.search(r'(?<!\w)' + re.escape(normalize(word.strip())) + r'(?!\w)', text)
               for word in keywords.split(',') if word.strip())


def ignored_matches(text, word):
    # Underscore is punctuation for this filter; alert matching keeps its existing rules.
    return bool(word and re.search(r'(?<![^\W_])' + re.escape(normalize(word)) + r'(?![^\W_])', normalize(text or '')))


def ignored_pattern(words):
    return re.compile(r'(?<![^\W_])(?:' + '|'.join(map(re.escape, words)) + r')(?![^\W_])') if words else None


def term_phrases(text):
    tokens = list(re.finditer(r'[^\W_]+', text))
    for i, first in enumerate(tokens):
        for size in (1, 2, 3):
            chunk = tokens[i:i + size]
            if len(chunk) != size or any(text[a.end():b.start()] != ' ' for a, b in zip(chunk, chunk[1:])):
                break
            yield text[first.start():chunk[-1].end()].casefold(), first.group(), chunk[-1].group()


def offer_term_groups(rows, ignored):
    pattern = ignored_pattern(ignored)
    key = lambda row: (row['chat_id'], 'album', row['grouped_id']) if row['grouped_id'] is not None else ('message', row['id'])
    grouped = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    for parts in grouped.values():
        if not pattern or not any(pattern.search(normalize(part['body'])) for part in parts):
            yield parts


def offer_body_terms(body):
    body = unicodedata.normalize('NFC', re.sub(r'https?://\S+|www\.\S+', ' ', body, flags=re.IGNORECASE))
    return term_phrases(body)


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
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, keywords TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ignored_keywords (
                    id INTEGER PRIMARY KEY, word TEXT NOT NULL, normalized TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS hidden_suggestions (
                    id INTEGER PRIMARY KEY, word TEXT NOT NULL, normalized TEXT NOT NULL UNIQUE);
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
            db.execute('CREATE INDEX IF NOT EXISTS offers_recent ON offers(date DESC, id DESC)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.create_function('ignored_matches', 2, ignored_matches, deterministic=True)
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

    def add_rule(self, name, keywords, *, return_alerts=False):
        with self.connect() as db:
            rule_id = db.execute('INSERT INTO rules(name, keywords) VALUES(?,?)',
                                 (name, keywords)).lastrowid
            matched = [row['id'] for row in db.execute('SELECT id,body FROM offers')
                       if matches(row['body'], keywords)]
            db.executemany('INSERT INTO hits(offer_id,rule_id) VALUES(?,?)',
                           [(offer_id, rule_id) for offer_id in matched])
            db.executemany('UPDATE offers SET seen=0 WHERE id=?', [(offer_id,) for offer_id in matched])
            if return_alerts:
                if not matched:
                    return 0, []
                offers = [dict(row) for row in db.execute(
                    'SELECT * FROM offers WHERE id IN (' + ','.join('?' for _ in matched) + ') ORDER BY id', matched)]
                notifications, notified_groups = [], set()
                for row in offers:
                    group = ((row['chat_id'], 'album', row['grouped_id']) if row['grouped_id'] is not None
                             else (row['chat_id'], 'message', row['id']))
                    if group in notified_groups:
                        continue
                    notified_groups.add(group)
                    notifications.append({'offer_id': row['id'], 'chat_id': row['chat_id'], 'message_id': row['message_id'],
                                          'grouped_id': row['grouped_id'], 'source': 'backfill', 'chat': row['chat_title'], 'body': row['body'], 'url': row['url'],
                                          'source_json': row['source_json'], 'rules': [name]})
                return len(matched), notifications
            return len(matched)

    def gotify_settings(self):
        settings = {row['key']: row['value'] for row in self.rows("SELECT key,value FROM settings WHERE key IN ('gotify_url','gotify_token','gotify_enabled')")}
        return {'url': settings.get('gotify_url', ''), 'token': settings.get('gotify_token', ''),
                'enabled': settings.get('gotify_enabled') == '1'}

    def media_signing_key(self):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('media_signing_key',?)",
                       (secrets.token_urlsafe(32),))
            return db.execute("SELECT value FROM settings WHERE key='media_signing_key'").fetchone()['value']

    def save_gotify(self, url, token, enabled):
        with self.connect() as db:
            if not token:
                row = db.execute("SELECT value FROM settings WHERE key='gotify_token'").fetchone()
                token = row['value'] if row else ''
            if enabled and (not url or not token):
                raise ValueError('Informe a URL e o token para ativar o Gotify.')
            db.executemany('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           [('gotify_url', url), ('gotify_token', token), ('gotify_enabled', '1' if enabled else '0')])

    def clear_gotify(self):
        with self.connect() as db:
            db.execute("DELETE FROM settings WHERE key IN ('gotify_url','gotify_token','gotify_enabled')")

    def add_ignored(self, word):
        word = word.strip()
        normalized = normalize(word).strip()
        if not normalized:
            raise ValueError('Informe uma palavra ou expressão para ignorar.')
        with self.connect() as db:
            return db.execute('INSERT OR IGNORE INTO ignored_keywords(word,normalized) VALUES(?,?)',
                              (word, normalized)).rowcount == 1

    def frequent_terms(self):
        # Count each phrase once per offer, including an album's separate messages.
        stopwords = {'a', 'as', 'ao', 'aos', 'o', 'os', 'um', 'uma', 'uns', 'umas',
                     'de', 'do', 'da', 'dos', 'das', 'em', 'no', 'na', 'nos', 'nas',
                     'e', 'ou', 'com', 'por', 'para', 'que', 'se', 'pra', 'pro'}
        counts, examples = Counter(), {}
        with self.connect() as db:
            db.execute('BEGIN')
            ignored = [row[0] for row in db.execute('SELECT normalized FROM ignored_keywords')]
            hidden = [row[0] for row in db.execute('SELECT normalized FROM hidden_suggestions')]
            rows = db.execute('SELECT id,chat_id,grouped_id,body FROM offers ORDER BY chat_id,grouped_id,id').fetchall()
        hidden_terms = {normalize(word) for text in hidden for word, _, _ in term_phrases(text)}
        for parts in offer_term_groups(rows, ignored):
            terms = {}
            for part in parts:
                for word, first, last in offer_body_terms(part['body']):
                    normalized = normalize(word)
                    if (len(word) <= 100 and len(normalized) > 1 and
                        normalize(first) not in stopwords and normalize(last) not in stopwords and
                        normalized not in hidden_terms):
                        terms.setdefault(normalized, word)
            counts.update(terms.keys())
            for term, word in terms.items():
                examples.setdefault(term, word)
        return [{'word': examples[term], 'count': count} for term, count in
                sorted(counts.items(), key=lambda item: (-item[1], item[0])) if count >= 2]

    def term_offers(self, word, page=1, per_page=20):
        """Return matching visible offer cards, counting albums once."""
        normalized = normalize(word)
        with self.connect() as db:
            db.execute('BEGIN')
            ignored = [row[0] for row in db.execute('SELECT normalized FROM ignored_keywords')]
            rows = [dict(row) for row in db.execute(
                '''SELECT o.*,
                    (SELECT group_concat(r.name, ', ') FROM hits h JOIN rules r ON r.id=h.rule_id
                     WHERE h.offer_id=o.id) AS rules
                   FROM offers o ORDER BY o.date DESC,o.id DESC''')]
        matching = [parts for parts in offer_term_groups(rows, ignored)
                    if any(normalize(phrase) == normalized
                           for part in parts for phrase, _, _ in offer_body_terms(part['body']))]
        total = len(matching)
        selected = matching[(page - 1) * per_page:page * per_page]
        cards = []
        for parts in selected:
            full_parts = sorted(parts, key=lambda part: part['message_id'])
            representative = full_parts[0]
            cards.append({**representative, 'parts': full_parts,
                'rules': ', '.join(dict.fromkeys(p['rules'] for p in full_parts if p['rules'])),
                'seen': all(p['seen'] for p in full_parts if p['rules'])})
        return cards, total

    def hide_suggestion(self, word):
        word = word.strip()
        normalized = normalize(word).strip()
        if not normalized:
            raise ValueError('Informe um termo para ocultar.')
        with self.connect() as db:
            return db.execute('INSERT OR IGNORE INTO hidden_suggestions(word,normalized) VALUES(?,?)',
                              (word, normalized)).rowcount == 1

    def add_terms_batch(self, action, words):
        if action not in ('ignore', 'hide'):
            raise ValueError('Ação inválida.')
        if not words or len(words) > 50:
            raise ValueError('Selecione entre 1 e 50 termos desta página.')
        items = [(word.strip(), normalize(word.strip()).strip()) for word in words]
        if any(not normalized or len(word) > 100 for word, normalized in items):
            raise ValueError('Os termos devem conter até 100 caracteres e não podem estar vazios.')
        table = 'ignored_keywords' if action == 'ignore' else 'hidden_suggestions'
        with self.connect() as db:
            before = db.total_changes
            db.executemany(f'INSERT OR IGNORE INTO {table}(word,normalized) VALUES(?,?)', items)
            return db.total_changes - before

    def ingest(self, chat_id, message_id, body, date, url, *, source_json=None, report_alert=False):
        grouped = json.loads(source_json).get('grouped_id') if source_json else None
        with self.connect() as db:
            chat = db.execute('SELECT title FROM chats WHERE id=?', (chat_id,)).fetchone()
            if not chat or (not body and not source_json):
                return
            had_alert = False
            if report_alert:
                had_alert = bool(db.execute('''SELECT 1 FROM offers o JOIN hits h ON h.offer_id=o.id
                    WHERE o.chat_id=? AND (o.message_id=? OR (? IS NOT NULL AND o.grouped_id=?)) LIMIT 1''',
                    (chat_id, message_id, str(grouped) if grouped is not None else None,
                     str(grouped) if grouped is not None else None)).fetchone())
            db.execute('''INSERT INTO offers(chat_id,message_id,chat_title,body,date,url,source_json,grouped_id)
                            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(chat_id,message_id)
                           DO UPDATE SET body=excluded.body,url=excluded.url,
                           source_json=excluded.source_json,grouped_id=excluded.grouped_id''',
                        (chat_id, message_id, chat['title'], body or '', date, url, source_json,
                         str(grouped) if grouped is not None else None))
            offer_id = db.execute('SELECT id FROM offers WHERE chat_id=? AND message_id=?',
                                  (chat_id, message_id)).fetchone()['id']
            db.execute('DELETE FROM hits WHERE offer_id=?', (offer_id,))
            matched = []
            for rule in db.execute('SELECT * FROM rules').fetchall():
                if matches(body or '', rule['keywords']):
                    db.execute('INSERT INTO hits VALUES(?,?)', (offer_id, rule['id']))
                    matched.append(rule['name'])
            if report_alert:
                return offer_id, {'offer_id': offer_id, 'chat_id': chat_id, 'message_id': message_id,
                                  'grouped_id': str(grouped) if grouped is not None else None, 'source': 'telegram',
                                  'chat': chat['title'], 'body': body or '', 'url': url, 'source_json': source_json,
                                  'rules': matched} if matched and not had_alert else None
            return offer_id

    def expire_offers(self, now=None):
        now = now or datetime.now(timezone.utc)
        short = (now - timedelta(hours=4)).isoformat()
        long = (now - timedelta(hours=24)).isoformat()
        with self.connect() as db:
            pattern = ignored_pattern([row[0] for row in db.execute('SELECT normalized FROM ignored_keywords')])
            db.create_function('ignored_offer', 1,
                               lambda body: bool(pattern and pattern.search(normalize(body or ''))), deterministic=True)
            db.execute('''WITH
                groups AS MATERIALIZED (
                    SELECT chat_id,coalesce(grouped_id,'message-' || id) AS group_id,
                           max(julianday(date)) AS latest
                    FROM offers GROUP BY chat_id,coalesce(grouped_id,'message-' || id)),
                alerted AS MATERIALIZED (
                    SELECT DISTINCT o.chat_id,coalesce(o.grouped_id,'message-' || o.id) AS group_id
                    FROM offers o JOIN hits h ON h.offer_id=o.id),
                ignored AS MATERIALIZED (
                    SELECT DISTINCT o.chat_id,coalesce(o.grouped_id,'message-' || o.id) AS group_id
                    FROM offers o WHERE ignored_offer(o.body))
                DELETE FROM offers WHERE (chat_id,coalesce(grouped_id,'message-' || id)) IN (
                    SELECT g.chat_id,g.group_id FROM groups g
                    LEFT JOIN alerted a USING(chat_id,group_id)
                    LEFT JOIN ignored i USING(chat_id,group_id)
                    WHERE a.chat_id IS NULL AND g.latest < CASE
                        WHEN i.chat_id IS NOT NULL THEN julianday(?) ELSE julianday(?) END)''',
                (short, long))

    def delete_offer(self, offer_id):
        with self.connect() as db:
            ids = [row[0] for row in db.execute('''SELECT id FROM offers WHERE id=? OR (chat_id,grouped_id) IN
                (SELECT chat_id,grouped_id FROM offers WHERE id=? AND grouped_id IS NOT NULL)''', (offer_id, offer_id))]
            if not ids or not db.execute('SELECT 1 FROM hits WHERE offer_id IN (' + ','.join('?' for _ in ids) + ') LIMIT 1', ids).fetchone():
                return False
            db.executemany('DELETE FROM hits WHERE offer_id=?', [(offer_id,) for offer_id in ids])
            db.execute('''DELETE FROM offers WHERE id=? OR (chat_id,grouped_id) IN
                (SELECT chat_id,grouped_id FROM offers WHERE id=? AND grouped_id IS NOT NULL)''', (offer_id, offer_id))
            return True

    def feed_filter(self, q='', alerts=False):
        clauses, args = [], []
        if alerts:
            clauses.append('EXISTS(SELECT 1 FROM hits WHERE offer_id=o.id)')
        else:
            clauses.append('''NOT EXISTS (SELECT 1 FROM ignored_keywords k WHERE
                ignored_matches(o.body,k.normalized) OR
                (o.grouped_id IS NOT NULL AND EXISTS (SELECT 1 FROM offers m
                    WHERE m.chat_id=o.chat_id AND m.grouped_id=o.grouped_id
                      AND ignored_matches(m.body,k.normalized))))''')
        if q:
            clauses.append("body LIKE ? ESCAPE '\\'")
            args.append('%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
        where = 'WHERE ' + ' AND '.join(clauses) if clauses else ''
        return where, args

    def feed(self, q='', alerts=False, db=None, read=None):
        if db is None:
            with self.connect() as db:
                return self.feed(q, alerts, db, read)
        where, args = self.feed_filter(q, alerts)
        if alerts and read is not None:
            unread_album = '''EXISTS (SELECT 1 FROM offers m WHERE m.seen=0
                AND EXISTS (SELECT 1 FROM hits WHERE offer_id=m.id)
                AND (m.id=o.id OR (o.grouped_id IS NOT NULL AND m.chat_id=o.chat_id
                                  AND m.grouped_id=o.grouped_id)))'''
            where += ' AND ' + ('NOT ' if read else '') + unread_album
        select = '''SELECT o.*, (SELECT group_concat(r.name, ', ') FROM hits h
                    JOIN rules r ON r.id=h.rule_id WHERE h.offer_id=o.id) AS rules FROM offers o '''
        selected = [dict(row) for row in db.execute(select + where + ' ORDER BY date DESC,id DESC LIMIT 100', args)]
        keys = {(r['chat_id'], r['grouped_id']) for r in selected if r['grouped_id']}
        albums = {}
        if keys:
            members = [dict(row) for row in db.execute(select + 'WHERE ' + ' OR '.join('(chat_id=? AND grouped_id=?)' for _ in keys)
                                + ' ORDER BY message_id', [value for key in keys for value in key])]
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

    def new_offers(self, after, q='', alerts=False):
        where, args = self.feed_filter(q, alerts)
        return self.rows('''SELECT count(*) AS n FROM (SELECT 1 FROM offers o ''' + where + '''
            AND o.id > ? AND (o.grouped_id IS NULL OR NOT EXISTS (SELECT 1 FROM offers old
                WHERE old.chat_id=o.chat_id AND old.grouped_id=o.grouped_id AND old.id<=?))
            GROUP BY o.chat_id, CASE WHEN o.grouped_id IS NULL THEN 'm:' || o.id
                                      ELSE 'g:' || o.grouped_id END)''', (*args, after, after))[0]['n']

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
