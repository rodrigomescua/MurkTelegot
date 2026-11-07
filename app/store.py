import hashlib
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


MAX_AI_PARALLELISM = 8


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


def offer_term_texts(parts):
    extracted = [part for part in parts if part['extraction_id'] is not None]
    return ([part['product_name'] or '' for part in extracted] if extracted
            else [part['body'] for part in parts])


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
                    source_json TEXT, grouped_id TEXT, deleted_at TEXT,
                    UNIQUE(chat_id, message_id));
                CREATE TABLE IF NOT EXISTS hits (
                    offer_id INTEGER NOT NULL REFERENCES offers(id),
                    rule_id INTEGER NOT NULL REFERENCES rules(id),
                    PRIMARY KEY(offer_id, rule_id));
                CREATE TABLE IF NOT EXISTS offer_extractions (
                    offer_id INTEGER PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
                    product_name TEXT, original_price TEXT,
                    discounted_price TEXT, coupon_code TEXT, job_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ai_jobs (
                    id INTEGER PRIMARY KEY, status TEXT NOT NULL, replace_existing INTEGER NOT NULL,
                    models_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT, clear_requested INTEGER NOT NULL DEFAULT 0,
                    queue_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ai_job_items (
                    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES ai_jobs(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, offer_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    UNIQUE(job_id, position));
                CREATE TABLE IF NOT EXISTS ai_job_attempts (
                    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES ai_jobs(id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES ai_job_items(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL, model TEXT NOT NULL, outcome TEXT NOT NULL,
                    detail TEXT NOT NULL, duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL);
            ''')
            if columns:
                db.execute('BEGIN')
                for name in ('source_json', 'grouped_id', 'deleted_at'):
                    if name not in columns:
                        db.execute(f'ALTER TABLE offers ADD COLUMN {name} TEXT')
            job_columns = {r['name'] for r in db.execute('PRAGMA table_info(ai_jobs)')}
            if 'clear_requested' not in job_columns:
                backup = Path(str(path) + '.before-ai-job-cleanup.db')
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
                db.execute('ALTER TABLE ai_jobs ADD COLUMN clear_requested INTEGER NOT NULL DEFAULT 0')
            if 'queue_at' not in job_columns:
                backup = Path(str(path) + '.before-ai-job-retry.db')
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
                db.execute('ALTER TABLE ai_jobs ADD COLUMN queue_at TEXT')
                db.execute('UPDATE ai_jobs SET queue_at=created_at WHERE queue_at IS NULL')
            db.execute('''DELETE FROM ignored_keywords
                          WHERE length(normalized) < 4 OR normalized NOT GLOB '*[^0-9]*' ''')
            db.execute('CREATE INDEX IF NOT EXISTS offers_album ON offers(chat_id, grouped_id, message_id)')
            db.execute('CREATE INDEX IF NOT EXISTS offers_recent ON offers(date DESC, id DESC)')
            db.execute('CREATE INDEX IF NOT EXISTS offers_deleted ON offers(deleted_at) WHERE deleted_at IS NOT NULL')

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

    def _register_ignored_filter(self, db):
        pattern = ignored_pattern([row[0] for row in db.execute('SELECT normalized FROM ignored_keywords')])
        db.create_function('ignored_offer', 1,
                           lambda body: bool(pattern and pattern.search(normalize(body or ''))), deterministic=True)

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def ai_settings(self):
        settings = {row['key']: row['value'] for row in self.rows(
            "SELECT key,value FROM settings WHERE key IN ('ai_openai_key','ai_openrouter_key','ai_model_order')")}
        try:
            order = json.loads(settings.get('ai_model_order', '[]'))
        except (TypeError, ValueError):
            order = []
        if not isinstance(order, list):
            order = []
        order = [item for item in order if isinstance(item, dict) and
                 item.get('provider') in ('openai', 'openrouter') and
                 isinstance(item.get('id'), str) and item['id']]
        return {'providers': {
            'openai': {'configured': bool(settings.get('ai_openai_key')), 'models': [i['id'] for i in order if i['provider'] == 'openai']},
            'openrouter': {'configured': bool(settings.get('ai_openrouter_key')), 'models': [i['id'] for i in order if i['provider'] == 'openrouter']},
        }, 'model_order': order}

    def ai_parallelism(self):
        rows = self.rows("SELECT value FROM settings WHERE key='ai_parallelism'")
        try:
            return min(MAX_AI_PARALLELISM, max(1, int(rows[0]['value']))) if rows else 1
        except (TypeError, ValueError):
            return 1

    def save_ai_parallelism(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f'A quantidade de jobs simultâneos deve ser um número entre 1 e {MAX_AI_PARALLELISM}.') from None
        if not 1 <= value <= MAX_AI_PARALLELISM:
            raise ValueError(f'A quantidade de jobs simultâneos deve ser um número entre 1 e {MAX_AI_PARALLELISM}.')
        with self.connect() as db:
            db.execute('''INSERT INTO settings(key,value) VALUES('ai_parallelism',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (str(value),))

    def ai_api_key(self, provider, supplied=''):
        if provider not in ('openai', 'openrouter'):
            raise ValueError('Provedor inválido.')
        supplied = supplied.strip()
        if supplied:
            return supplied
        row = self.rows('SELECT value FROM settings WHERE key=?', (f'ai_{provider}_key',))
        if not row:
            raise ValueError('Informe e salve a chave deste provedor antes de continuar.')
        return row[0]['value']

    def configured_ai_models(self):
        with self.connect() as db:
            settings = {row['key']: row['value'] for row in db.execute(
                "SELECT key,value FROM settings WHERE key IN ('ai_openai_key','ai_openrouter_key','ai_model_order')")}
        try:
            order = json.loads(settings.get('ai_model_order', '[]'))
        except (TypeError, ValueError):
            return []
        if not isinstance(order, list):
            return []
        return [{**item, 'api_key': settings.get(f"ai_{item['provider']}_key", '')}
                for item in order if isinstance(item, dict) and
                item.get('provider') in ('openai', 'openrouter') and
                isinstance(item.get('id'), str) and item['id'] and
                settings.get(f"ai_{item['provider']}_key")]

    def save_ai_settings(self, openai_key, openrouter_key, model_order):
        if len(openai_key) > 4096 or len(openrouter_key) > 4096:
            raise ValueError('A chave de API excede o tamanho permitido.')
        if not isinstance(model_order, list) or len(model_order) > 200:
            raise ValueError('Selecione até 200 modelos para a hierarquia.')
        normalized, seen = [], set()
        for item in model_order:
            if not isinstance(item, dict) or item.get('provider') not in ('openai', 'openrouter'):
                raise ValueError('A ordem de modelos é inválida.')
            model = item.get('id')
            if not isinstance(model, str) or not model.strip() or len(model) > 256:
                raise ValueError('O identificador de um modelo é inválido.')
            key = (item['provider'], model.strip())
            if key not in seen:
                seen.add(key)
                normalized.append({'provider': key[0], 'id': key[1]})
        with self.connect() as db:
            existing_keys = {row['key']: row['value'] for row in db.execute(
                "SELECT key,value FROM settings WHERE key IN ('ai_openai_key','ai_openrouter_key')")}
            for item in normalized:
                supplied = openai_key if item['provider'] == 'openai' else openrouter_key
                if not supplied.strip() and not existing_keys.get(f"ai_{item['provider']}_key"):
                    provider_name = 'OpenAI' if item['provider'] == 'openai' else 'OpenRouter'
                    raise ValueError(f'Informe a chave de API de {provider_name} para usar os modelos selecionados.')
            for provider, supplied in (('openai', openai_key), ('openrouter', openrouter_key)):
                if supplied.strip():
                    db.execute('''INSERT INTO settings(key,value) VALUES(?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                               (f'ai_{provider}_key', supplied.strip()))
            db.execute('''INSERT INTO settings(key,value) VALUES('ai_model_order',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (json.dumps(normalized),))

    def enqueue_ai_job(self, replace_existing=False, *, offer_ids=None, automatic=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            settings = {row['key']: row['value'] for row in db.execute(
                "SELECT key,value FROM settings WHERE key IN ('ai_openai_key','ai_openrouter_key','ai_model_order')")}
            if not settings.get('ai_model_order'):
                if automatic:
                    return None, 0
                raise ValueError('Configure ao menos um provedor e modelo antes de iniciar o processamento.')
            try:
                models = json.loads(settings['ai_model_order'])
            except (KeyError, ValueError):
                if automatic:
                    return None, 0
                raise ValueError('Salve novamente a configuração dos modelos antes de iniciar o processamento.') from None
            if not models or any(not settings.get(f"ai_{item.get('provider')}_key") for item in models):
                if automatic:
                    return None, 0
                raise ValueError('Configure as chaves dos provedores selecionados antes de iniciar o processamento.')
            cards = self.feed('', False, db)
            if offer_ids is not None:
                cards = [card for card in cards if card['id'] in offer_ids]
            if not replace_existing or automatic:
                cards = [card for card in cards if not card.get('extraction')]
            if automatic:
                cards = [card for card in cards if not db.execute('''SELECT 1 FROM ai_job_items i
                    JOIN ai_jobs j ON j.id=i.job_id WHERE i.offer_id=? AND j.status IN ('queued','running','cancelling')
                    AND i.status IN ('queued','processing') LIMIT 1''', (card['id'],)).fetchone()]
            if not cards:
                if automatic:
                    return None, 0
                raise ValueError('Não há ofertas elegíveis para processar na Home padrão.')
            created = datetime.now(timezone.utc).isoformat(timespec='seconds')
            queue_at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            job_id = db.execute('''INSERT INTO ai_jobs(status,replace_existing,models_json,created_at,queue_at)
                VALUES('queued',?,?,?,?)''', (int(bool(replace_existing)), json.dumps(models), created, queue_at)).lastrowid
            db.executemany('''INSERT INTO ai_job_items(job_id,position,offer_id,chat_id,message_id)
                VALUES(?,?,?,?,?)''', [(job_id, index, card['id'], card['chat_id'], card['message_id'])
                                       for index, card in enumerate(cards)])
            return job_id, len(cards)

    def recover_ai_jobs(self):
        with self.connect() as db:
            finished = datetime.now(timezone.utc).isoformat(timespec='seconds')
            db.execute("UPDATE ai_job_items SET status='cancelled' WHERE status IN ('queued','processing') AND job_id IN (SELECT id FROM ai_jobs WHERE status='cancelling')")
            db.execute("UPDATE ai_jobs SET status='cancelled',finished_at=? WHERE status='cancelling'", (finished,))
            db.execute("UPDATE ai_job_items SET status='queued' WHERE status='processing'")
            db.execute("UPDATE ai_jobs SET status='queued',started_at=NULL WHERE status='running'")
            db.execute('DELETE FROM ai_jobs WHERE clear_requested=1')

    def claim_ai_job(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            setting = db.execute("SELECT value FROM settings WHERE key='ai_parallelism'").fetchone()
            try:
                limit = min(8, max(1, int(setting['value']))) if setting else 1
            except (TypeError, ValueError):
                limit = 1
            running = db.execute("SELECT count(*) FROM ai_jobs WHERE status IN ('running','cancelling')").fetchone()[0]
            if running >= limit:
                return None
            job = db.execute("SELECT * FROM ai_jobs WHERE status='queued' ORDER BY queue_at,id LIMIT 1").fetchone()
            if not job:
                return None
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            db.execute("UPDATE ai_jobs SET status='running',started_at=? WHERE id=?", (now, job['id']))
            return {**dict(job), 'status': 'running', 'started_at': now}

    def requeue_failed_ai_item(self, job_id, item_id, max_retries=1):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT status FROM ai_jobs WHERE id=?", (job_id,)).fetchone()
            item = db.execute('SELECT * FROM ai_job_items WHERE id=? AND job_id=?', (item_id, job_id)).fetchone()
            retries = db.execute("SELECT count(*) FROM ai_job_attempts WHERE item_id=? AND outcome='retry'",
                                 (item_id,)).fetchone()[0]
            if not job or job['status'] != 'running' or not item or retries >= max_retries:
                return False
            now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            position = db.execute('SELECT coalesce(max(position),-1)+1 FROM ai_job_items WHERE job_id=?',
                                  (job_id,)).fetchone()[0]
            db.execute("UPDATE ai_job_items SET status='queued',position=? WHERE id=?", (position, item_id))
            db.execute("UPDATE ai_jobs SET status='queued',started_at=NULL,queue_at=? WHERE id=?", (now, job_id))
            db.execute('''INSERT INTO ai_job_attempts(job_id,item_id,provider,model,outcome,detail,duration_ms,created_at)
                VALUES(?,?, 'sistema','-','retry',?,0,?)''',
                       (job_id, item_id, f'Reenvio {retries + 1} de {max_retries} após falha dos modelos.', now))
            return True

    def claim_ai_item(self, job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM ai_jobs WHERE id=? AND status='running'", (job_id,)).fetchone() is None:
                return None
            item = db.execute("SELECT * FROM ai_job_items WHERE job_id=? AND status='queued' ORDER BY position LIMIT 1",
                              (job_id,)).fetchone()
            if not item:
                return None
            db.execute("UPDATE ai_job_items SET status='processing' WHERE id=?", (item['id'],))
            return dict(item)

    def ai_item_content(self, item):
        with self.connect() as db:
            root = db.execute('SELECT * FROM offers WHERE id=?', (item['offer_id'],)).fetchone()
            if not root:
                return None
            if root['grouped_id'] is None:
                parts = [root['body']]
            else:
                parts = [row[0] for row in db.execute(
                    'SELECT body FROM offers WHERE chat_id=? AND grouped_id=? ORDER BY message_id',
                    (root['chat_id'], root['grouped_id']))]
            text = '\n\n'.join(part for part in parts if part.strip())
            return {'offer_id': root['id'], 'text': text,
                    'content_hash': hashlib.sha256(text.encode()).hexdigest(),
                    'label': f"Oferta #{root['message_id']}"}

    def ai_item_has_extraction(self, item):
        return bool(self.rows('SELECT 1 FROM offer_extractions WHERE offer_id=?', (item['offer_id'],)))

    def record_ai_attempt(self, job_id, item_id, provider, model, outcome, detail, duration_ms):
        created = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self.connect() as db:
            db.execute('''INSERT INTO ai_job_attempts
                (job_id,item_id,provider,model,outcome,detail,duration_ms,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',
                       (job_id, item_id, provider, model, outcome, detail[:300], max(0, duration_ms), created))

    def finish_ai_item(self, item_id, status, extraction=None, content_hash=None):
        if status not in ('succeeded', 'failed', 'skipped', 'cancelled'):
            raise ValueError('Estado de extração inválido.')
        with self.connect() as db:
            item = db.execute('''SELECT i.*,j.status AS job_status FROM ai_job_items i
                JOIN ai_jobs j ON j.id=i.job_id WHERE i.id=?''', (item_id,)).fetchone()
            if not item:
                return 'missing'
            if item['job_status'] in ('cancelling', 'cancelled'):
                db.execute("UPDATE ai_job_items SET status='cancelled' WHERE id=?", (item_id,))
                return 'cancelled'
            if status == 'succeeded' and extraction:
                root = db.execute('SELECT * FROM offers WHERE id=?', (item['offer_id'],)).fetchone()
                if not root:
                    db.execute("UPDATE ai_job_items SET status='skipped' WHERE id=?", (item_id,))
                    return 'stale'
                if root['grouped_id'] is None:
                    parts = [root['body']]
                else:
                    parts = [row[0] for row in db.execute(
                        'SELECT body FROM offers WHERE chat_id=? AND grouped_id=? ORDER BY message_id',
                        (root['chat_id'], root['grouped_id']))]
                current_text = '\n\n'.join(part for part in parts if part.strip())
                if content_hash and hashlib.sha256(current_text.encode()).hexdigest() != content_hash:
                    db.execute("UPDATE ai_job_items SET status='skipped' WHERE id=?", (item_id,))
                    return 'stale'
                now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                db.execute('''INSERT INTO offer_extractions
                    (offer_id,product_name,original_price,discounted_price,coupon_code,job_id,updated_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(offer_id) DO UPDATE SET
                    product_name=excluded.product_name,
                    original_price=excluded.original_price,discounted_price=excluded.discounted_price,
                    coupon_code=excluded.coupon_code,job_id=excluded.job_id,updated_at=excluded.updated_at''',
                           (item['offer_id'], *(extraction.get(field) for field in
                            ('product_name', 'original_price', 'discounted_price', 'coupon_code')),
                            item['job_id'], now))
            db.execute('UPDATE ai_job_items SET status=? WHERE id=?', (status, item_id))
            return status

    def ai_job_cancel_requested(self, job_id):
        return bool(self.rows("SELECT 1 FROM ai_jobs WHERE id=? AND status IN ('cancelling','cancelled')",
                              (job_id,)))

    def cancel_ai_job(self, job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT status FROM ai_jobs WHERE id=?', (job_id,)).fetchone()
            if not job:
                return 'missing'
            if job['status'] == 'queued':
                db.execute("UPDATE ai_job_items SET status='cancelled' WHERE job_id=? AND status IN ('queued','processing')",
                           (job_id,))
                db.execute("UPDATE ai_jobs SET status='cancelled',finished_at=? WHERE id=?",
                           (datetime.now(timezone.utc).isoformat(timespec='seconds'), job_id))
                return 'cancelled'
            if job['status'] == 'running':
                db.execute("UPDATE ai_job_items SET status='cancelled' WHERE job_id=? AND status='queued'",
                           (job_id,))
                db.execute("UPDATE ai_jobs SET status='cancelling' WHERE id=?", (job_id,))
                return 'cancelling'
            if job['status'] == 'cancelling':
                return 'cancelling'
            return 'finished'

    def finish_ai_job(self, job_id):
        with self.connect() as db:
            job = db.execute('SELECT status FROM ai_jobs WHERE id=?', (job_id,)).fetchone()
            if not job:
                return
            counts = {row['status']: row['n'] for row in db.execute(
                'SELECT status,count(*) AS n FROM ai_job_items WHERE job_id=? GROUP BY status', (job_id,))}
            if counts.get('queued') or counts.get('processing'):
                return
            status = ('cancelled' if job['status'] == 'cancelling' else
                      'completed_with_errors' if counts.get('failed') else 'completed')
            db.execute('UPDATE ai_jobs SET status=?,finished_at=? WHERE id=?',
                       (status, datetime.now(timezone.utc).isoformat(timespec='seconds'), job_id))
            db.execute('DELETE FROM ai_jobs WHERE id=? AND clear_requested=1', (job_id,))

    def clear_completed_ai_jobs(self):
        with self.connect() as db:
            db.execute("DELETE FROM ai_jobs WHERE status IN ('completed','completed_with_errors','failed','cancelled')")

    def cancel_and_clear_ai_jobs(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = [row['id'] for row in db.execute(
                "SELECT id FROM ai_jobs WHERE status IN ('running','cancelling')")]
            db.execute("UPDATE ai_job_items SET status='cancelled' WHERE job_id IN "
                       "(SELECT id FROM ai_jobs WHERE status='queued') AND status IN ('queued','processing')")
            db.execute("UPDATE ai_jobs SET status='cancelled',finished_at=? WHERE status='queued'",
                       (datetime.now(timezone.utc).isoformat(timespec='seconds'),))
            db.execute("UPDATE ai_job_items SET status='cancelled' WHERE job_id IN "
                       "(SELECT id FROM ai_jobs WHERE status IN ('running','cancelling')) AND status='queued'")
            db.execute("UPDATE ai_jobs SET status='cancelling',clear_requested=1 WHERE status IN ('running','cancelling')")
            db.execute("DELETE FROM ai_jobs WHERE status IN ('completed','completed_with_errors','failed','cancelled')")
            return active

    def ai_jobs(self):
        with self.connect() as db:
            jobs = [dict(row) for row in db.execute('''SELECT j.*,
                count(i.id) AS total,
                sum(CASE WHEN i.status IN ('succeeded','failed','skipped','cancelled') THEN 1 ELSE 0 END) AS processed,
                sum(CASE WHEN i.status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                sum(CASE WHEN i.status='failed' THEN 1 ELSE 0 END) AS failed,
                sum(CASE WHEN i.status='skipped' THEN 1 ELSE 0 END) AS skipped,
                sum(CASE WHEN i.status='cancelled' THEN 1 ELSE 0 END) AS cancelled
                FROM ai_jobs j LEFT JOIN ai_job_items i ON i.job_id=j.id
                GROUP BY j.id ORDER BY j.id DESC''')]
            logs = db.execute('''SELECT a.*,i.message_id FROM ai_job_attempts a
                JOIN ai_job_items i ON i.id=a.item_id ORDER BY a.id DESC''').fetchall()
        by_job = {job['id']: [] for job in jobs}
        for row in logs:
            if row['job_id'] in by_job:
                by_job[row['job_id']].append({**dict(row), 'offer_label': f"Oferta #{row['message_id']}"})
        for job in jobs:
            job['processed'] = job['processed'] or 0
            job['succeeded'] = job['succeeded'] or 0
            job['failed'] = job['failed'] or 0
            job['skipped'] = job['skipped'] or 0
            job['cancelled'] = job['cancelled'] or 0
            job['logs'] = by_job[job['id']]
        active = min((job for job in jobs if job['status'] in ('queued', 'running', 'cancelling')),
                     key=lambda job: (0 if job['status'] == 'running' else
                                      1 if job['status'] == 'cancelling' else 2,
                                      job['queue_at'], job['id']), default=None)
        return jobs, active

    def ai_job_status(self):
        with self.connect() as db:
            row = db.execute('''SELECT j.id,j.status,count(i.id) AS total,
                sum(CASE WHEN i.status IN ('succeeded','failed','skipped','cancelled') THEN 1 ELSE 0 END) AS processed,
                sum(CASE WHEN i.status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                sum(CASE WHEN i.status='failed' THEN 1 ELSE 0 END) AS failed,
                sum(CASE WHEN i.status='skipped' THEN 1 ELSE 0 END) AS skipped,
                sum(CASE WHEN i.status='cancelled' THEN 1 ELSE 0 END) AS cancelled
                FROM ai_jobs j LEFT JOIN ai_job_items i ON i.job_id=j.id
                WHERE j.status IN ('queued','running','cancelling') GROUP BY j.id
                  ORDER BY CASE j.status WHEN 'running' THEN 0 WHEN 'cancelling' THEN 1 ELSE 2 END,
                           j.queue_at,j.id LIMIT 1''').fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ('processed', 'succeeded', 'failed', 'skipped', 'cancelled'):
            result[key] = result[key] or 0
        return result

    def add_rule(self, name, keywords, *, return_alerts=False):
        with self.connect() as db:
            rule_id = db.execute('INSERT INTO rules(name, keywords) VALUES(?,?)',
                                 (name, keywords)).lastrowid
            matched = [row['id'] for row in db.execute('SELECT id,body FROM offers WHERE deleted_at IS NULL')
                       if matches(row['body'], keywords)]
            db.executemany('INSERT INTO hits(offer_id,rule_id) VALUES(?,?)',
                           [(offer_id, rule_id) for offer_id in matched])
            db.executemany('UPDATE offers SET seen=0 WHERE id=?', [(offer_id,) for offer_id in matched])
            if return_alerts:
                if not matched:
                    return 0, []
                offers = [dict(row) for row in db.execute(
                    'SELECT * FROM offers WHERE deleted_at IS NULL AND id IN (' + ','.join('?' for _ in matched) + ') ORDER BY id', matched)]
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
        minimum = self.frequent_terms_min_chars()
        if len(normalized) < minimum or normalized.isdigit():
            raise ValueError(f'Use pelo menos {minimum} caracteres e não informe apenas números.')
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
            minimum = self.frequent_terms_min_chars()
            rows = db.execute('''SELECT o.id,o.chat_id,o.grouped_id,o.body,e.offer_id AS extraction_id,
                    e.product_name FROM offers o LEFT JOIN offer_extractions e ON e.offer_id=o.id
                    WHERE o.deleted_at IS NULL ORDER BY o.chat_id,o.grouped_id,o.id''').fetchall()
        hidden_terms = {normalize(word) for text in hidden for word, _, _ in term_phrases(text)}
        for parts in offer_term_groups(rows, ignored):
            terms = {}
            for text in offer_term_texts(parts):
                for word, first, last in offer_body_terms(text):
                    normalized = normalize(word)
                    if (len(word) <= 100 and len(normalized) >= minimum and
                        not normalized.isdigit() and
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
              '''SELECT o.*,e.offer_id AS extraction_id,e.product_name,
                    (SELECT group_concat(r.name, ', ') FROM hits h JOIN rules r ON r.id=h.rule_id
                       WHERE h.offer_id=o.id) AS rules
                     FROM offers o LEFT JOIN offer_extractions e ON e.offer_id=o.id
                     WHERE o.deleted_at IS NULL ORDER BY o.date DESC,o.id DESC''')]
        matching = [parts for parts in offer_term_groups(rows, ignored)
                    if any(normalize(phrase) == normalized
                             for text in offer_term_texts(parts)
                             for phrase, _, _ in offer_body_terms(text))]
        total = len(matching)
        selected = matching[(page - 1) * per_page:page * per_page]
        cards = []
        for parts in selected:
            full_parts = sorted(parts, key=lambda part: part['message_id'])
            representative = full_parts[0]
            cards.append({**representative, 'parts': full_parts,
                'rules': ', '.join(dict.fromkeys(p['rules'] for p in full_parts if p['rules'])),
                'seen': all(p['seen'] for p in full_parts if p['rules'])})
        if cards:
            with self.connect() as db:
                self._attach_extractions(cards, db)
        return cards, total

    def hide_suggestion(self, word):
        word = word.strip()
        normalized = normalize(word).strip()
        if not self.valid_frequent_term(word, 2):
            raise ValueError('Informe um termo válido para ocultar.')
        with self.connect() as db:
            return db.execute('INSERT OR IGNORE INTO hidden_suggestions(word,normalized) VALUES(?,?)',
                              (word, normalized)).rowcount == 1

    def add_terms_batch(self, action, words):
        if action not in ('ignore', 'hide'):
            raise ValueError('Ação inválida.')
        if not words or len(words) > 50:
            raise ValueError('Selecione entre 1 e 50 termos desta página.')
        items = [(word.strip(), normalize(word.strip()).strip()) for word in words]
        minimum = self.frequent_terms_min_chars() if action == 'ignore' else 2
        if any((not normalize(word).strip() if action == 'ignore' else not self.valid_frequent_term(word, minimum)) or len(word) > 100 for word, _ in items):
            raise ValueError(f'Os termos devem ter pelo menos {minimum} caracteres, não ser apenas numéricos e conter até 100 caracteres.')
        table = 'ignored_keywords' if action == 'ignore' else 'hidden_suggestions'
        with self.connect() as db:
            before = db.total_changes
            db.executemany(f'INSERT OR IGNORE INTO {table}(word,normalized) VALUES(?,?)', items)
            return db.total_changes - before

    @staticmethod
    def valid_frequent_term(word, minimum=4):
        word = word.strip()
        normalized = normalize(word)
        return len(normalized) >= minimum and not word.isdigit() and bool(normalized.strip())

    def frequent_terms_min_chars(self):
        rows = self.rows("SELECT value FROM settings WHERE key='frequent_terms_min_chars'")
        return max(4, int(rows[0]['value'])) if rows else 4

    def save_frequent_terms_min_chars(self, value):
        value = int(value)
        if value < 4 or value > 100:
            raise ValueError('A quantidade mínima deve estar entre 4 e 100 caracteres.')
        with self.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('frequent_terms_min_chars',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(value),))

    def ingest(self, chat_id, message_id, body, date, url, *, source_json=None, report_alert=False):
        grouped = json.loads(source_json).get('grouped_id') if source_json else None
        with self.connect() as db:
            chat = db.execute('SELECT title FROM chats WHERE id=?', (chat_id,)).fetchone()
            if not chat or (not body and not source_json):
                return
            previous = db.execute('SELECT id,body,grouped_id,deleted_at FROM offers WHERE chat_id=? AND message_id=?',
                                  (chat_id, message_id)).fetchone()
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
            current_group = str(grouped) if grouped is not None else None
            deleted_at = previous['deleted_at'] if previous else None
            if current_group is not None:
                deleted_at = deleted_at or db.execute('''SELECT min(deleted_at) FROM offers
                    WHERE chat_id=? AND grouped_id=? AND deleted_at IS NOT NULL''',
                    (chat_id, current_group)).fetchone()[0]
                if deleted_at:
                    db.execute('UPDATE offers SET deleted_at=coalesce(deleted_at,?) WHERE id=?',
                               (deleted_at, offer_id))
            if ((previous and (previous['body'] != (body or '') or previous['grouped_id'] != current_group))
                    or (not previous and current_group is not None)):
                affected = set()
                for group in ((previous['grouped_id'] if previous else None), current_group):
                    root = (db.execute('SELECT id FROM offers WHERE chat_id=? AND grouped_id=? ORDER BY message_id LIMIT 1',
                                       (chat_id, group)).fetchone() if group is not None else None)
                    affected.add(root['id'] if root else offer_id)
                db.executemany('DELETE FROM offer_extractions WHERE offer_id=?', [(item,) for item in affected])
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
                                  'rules': matched} if matched and not had_alert and not deleted_at else None
            return offer_id

    def expire_offers(self, now=None):
        now = now or datetime.now(timezone.utc)
        deleted_before = (now - timedelta(hours=1)).isoformat()
        short = (now - timedelta(hours=4)).isoformat()
        long = (now - timedelta(hours=24)).isoformat()
        with self.connect() as db:
            self._register_ignored_filter(db)
            expired = [row[0] for row in db.execute('SELECT id FROM offers WHERE deleted_at IS NOT NULL AND deleted_at<=?',
                                                    (deleted_before,))]
            if expired:
                db.executemany('DELETE FROM hits WHERE offer_id=?', [(offer_id,) for offer_id in expired])
                db.executemany('DELETE FROM offers WHERE id=?', [(offer_id,) for offer_id in expired])
            db.execute('''WITH
                groups AS MATERIALIZED (
                    SELECT chat_id,coalesce(grouped_id,'message-' || id) AS group_id,
                           max(julianday(date)) AS latest
                    FROM offers WHERE deleted_at IS NULL
                    GROUP BY chat_id,coalesce(grouped_id,'message-' || id)),
                alerted AS MATERIALIZED (
                    SELECT DISTINCT o.chat_id,coalesce(o.grouped_id,'message-' || o.id) AS group_id
                    FROM offers o JOIN hits h ON h.offer_id=o.id),
                ignored AS MATERIALIZED (
                    SELECT DISTINCT o.chat_id,coalesce(o.grouped_id,'message-' || o.id) AS group_id
                    FROM offers o WHERE o.deleted_at IS NULL AND ignored_offer(o.body))
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
            if not ids:
                return False
            deleted_at = datetime.now(timezone.utc).isoformat()
            db.executemany('UPDATE offers SET deleted_at=coalesce(deleted_at,?) WHERE id=?',
                           [(deleted_at, item) for item in ids])
            return True

    def restore_deleted_offer(self, offer_id):
        with self.connect() as db:
            row = db.execute('SELECT chat_id,grouped_id FROM offers WHERE id=? AND deleted_at IS NOT NULL',
                             (offer_id,)).fetchone()
            if not row:
                return False
            if row['grouped_id'] is None:
                db.execute('UPDATE offers SET deleted_at=NULL WHERE id=?', (offer_id,))
            else:
                db.execute('UPDATE offers SET deleted_at=NULL WHERE chat_id=? AND grouped_id=?',
                           (row['chat_id'], row['grouped_id']))
            return True

    def feed_filter(self, q='', alerts=False):
        clauses, args = ['o.deleted_at IS NULL'], []
        if alerts:
            clauses.append('EXISTS(SELECT 1 FROM hits WHERE offer_id=o.id)')
        else:
            clauses.append('''NOT ignored_offer(o.body) AND NOT (o.grouped_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM offers m WHERE m.chat_id=o.chat_id AND m.grouped_id=o.grouped_id
                  AND ignored_offer(m.body)))''')
            alert_group = '''(a.id=o.id OR (o.grouped_id IS NOT NULL AND a.chat_id=o.chat_id
                AND a.grouped_id=o.grouped_id))'''
            clauses.append(f'''(NOT EXISTS (SELECT 1 FROM offers a JOIN hits h ON h.offer_id=a.id
                WHERE {alert_group}) OR EXISTS (SELECT 1 FROM offers a JOIN hits h ON h.offer_id=a.id
                WHERE {alert_group} AND a.seen=0))''')
        if q:
            clauses.append("body LIKE ? ESCAPE '\\'")
            args.append('%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
        where = 'WHERE ' + ' AND '.join(clauses) if clauses else ''
        return where, args

    def feed(self, q='', alerts=False, db=None, read=None):
        if db is None:
            with self.connect() as db:
                return self.feed(q, alerts, db, read)
        if not alerts:
            self._register_ignored_filter(db)
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
                                + ' AND deleted_at IS NULL ORDER BY message_id', [value for key in keys for value in key])]
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
        self._attach_extractions(cards, db)
        return cards

    @staticmethod
    def _attach_extractions(cards, db):
        if not cards:
            return
        ids = [card['id'] for card in cards]
        found = {}
        for row in db.execute('''SELECT * FROM offer_extractions WHERE offer_id IN (''' +
                              ','.join('?' for _ in ids) + ')', ids):
            extraction = {key: row[key] for key in
                          ('product_name', 'original_price', 'discounted_price', 'coupon_code')}
            if any(extraction.values()):
                found[row['offer_id']] = extraction
        for card in cards:
            card['extraction'] = found.get(card['id'])

    def new_offers(self, after, q='', alerts=False):
        with self.connect() as db:
            if not alerts:
                self._register_ignored_filter(db)
            where, args = self.feed_filter(q, alerts)
            return db.execute('''SELECT count(*) AS n FROM (SELECT 1 FROM offers o ''' + where + '''
                AND o.id > ? AND (o.grouped_id IS NULL OR NOT EXISTS (SELECT 1 FROM offers old
                    WHERE old.chat_id=o.chat_id AND old.grouped_id=o.grouped_id AND old.id<=?))
                GROUP BY o.chat_id, CASE WHEN o.grouped_id IS NULL THEN 'm:' || o.id
                                          ELSE 'g:' || o.grouped_id END)''',
                              (*args, after, after)).fetchone()['n']

    def unread(self):
        return self.rows('''SELECT count(*) AS n FROM (
            SELECT chat_id,coalesce(grouped_id,'message-' || id) FROM offers
            WHERE deleted_at IS NULL AND seen=0 AND EXISTS(SELECT 1 FROM hits WHERE offer_id=offers.id)
            GROUP BY chat_id,coalesce(grouped_id,'message-' || id))''')[0]['n']

    def mark_seen(self, offer_id):
        with self.connect() as db:
            db.execute('''UPDATE offers SET seen=1 WHERE id=? OR
                (chat_id,grouped_id) IN (SELECT chat_id,grouped_id FROM offers WHERE id=? AND grouped_id IS NOT NULL)''',
                       (offer_id, offer_id))

    def mark_unseen(self, offer_id):
        with self.connect() as db:
            db.execute('''UPDATE offers SET seen=0 WHERE id=? OR
                (chat_id,grouped_id) IN (SELECT chat_id,grouped_id FROM offers WHERE id=? AND grouped_id IS NOT NULL)''',
                       (offer_id, offer_id))
