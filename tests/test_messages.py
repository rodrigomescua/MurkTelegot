import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from telethon import types

from app.messages import media_info, present, rich_text, safe_url
from app.store import Store
from app.telegram import Telegram


_runtime = tempfile.TemporaryDirectory()
os.environ.update(DATA_DIR=_runtime.name, APP_PASSWORD='test-password-with-32-characters',
                  TELEGRAM_API_ID='', TELEGRAM_API_HASH='')

def message(message_id=1, text='Oferta de café', *, photo=True, grouped=None, entities=None):
    media = types.MessageMediaPhoto(photo=types.Photo(id=100 + message_id, access_hash=0,
        file_reference=b'private-reference', date=datetime.now(timezone.utc), sizes=[], dc_id=2)) if photo else None
    return types.Message(id=message_id, peer_id=types.PeerChannel(123), date=datetime.now(timezone.utc),
                         message=text, entities=entities, media=media, grouped_id=grouped)


def store_message(store, msg):
    return store.ingest(-100123, msg.id, msg.raw_text, msg.date.isoformat(),
                        f'https://t.me/c/123/{msg.id}', source_json=msg.to_json())


class RichTextTests(unittest.TestCase):
    def test_nested_utf16_entities_escape_and_line_breaks(self):
        text = '😀 Café\n<strong>literal</strong>'
        result = str(rich_text(text, [
            {'_': 'MessageEntityBold', 'offset': 3, 'length': 4},
            {'_': 'MessageEntityItalic', 'offset': 3, 'length': 4}]))
        self.assertIn('😀 <strong><em>Café</em></strong>\n', result)
        self.assertIn('&lt;strong&gt;literal&lt;/strong&gt;', result)

    def test_links_escape_attributes_and_reject_executable_schemes(self):
        for url in ('javascript:alert(1)', 'data:text/html,evil', 'file:///etc/passwd', 'https://x\n.bad', '//example.com'):
            self.assertIsNone(safe_url(url))
            self.assertNotIn('<a ', str(rich_text('clique', [{'_': 'MessageEntityTextUrl', 'offset': 0, 'length': 6, 'url': url}])))
        safe = str(rich_text('clique', [{'_': 'MessageEntityTextUrl', 'offset': 0, 'length': 6,
                                       'url': 'https://example.com/?q="onclick=evil'}]))
        self.assertIn('&quot;', safe)
        self.assertIn('rel="noopener noreferrer"', safe)
        self.assertNotIn('href="https://example.com/?q="', safe)

    def test_code_quote_spoiler_and_crossing_spans_are_balanced(self):
        result = str(rich_text('abcdef', [
            {'_': 'MessageEntityBold', 'offset': 0, 'length': 4},
            {'_': 'MessageEntityItalic', 'offset': 2, 'length': 4}]))
        self.assertEqual(result, '<strong>ab<em>cd</em></strong><em>ef</em>')
        for kind, tag in [('MessageEntityPre', '<pre><code>'), ('MessageEntityBlockquote', '<blockquote>'),
                          ('MessageEntitySpoiler', '<span class="spoiler"')]:
            self.assertIn(tag, str(rich_text('teste', [{'_': kind, 'offset': 0, 'length': 5}])))

    def test_metadata_links_buttons_poll_contact_and_unknown_are_safe(self):
        source = {'media': {'_': 'MessageMediaPoll', 'poll': {'question': {'text': 'Escolha'},
            'answers': [{'text': 'A', 'option': 'YQ=='}]}, 'results': {'total_voters': 2, 'results': [{'option': 'YQ==', 'voters': 2}]}},
            'reply_markup': {'rows': [{'buttons': [{'_': 'KeyboardButtonUrl', 'text': 'Malicioso', 'url': 'javascript:bad'},
                {'_': 'KeyboardButtonCallback', 'text': 'Comprar'}]}]}}
        view = present({'id': 1, 'chat_id': -100123, 'body': 'Texto', 'source_json': json.dumps(source)})
        self.assertEqual(view['poll']['answers'][0]['votes'], 2)
        self.assertTrue(all(b['url'] is None for b in view['buttons'][0]))
        view = present({'chat_id': -100123, 'body': 'Texto', 'source_json': json.dumps({'media': {'_': 'MessageMediaDice'}})})
        self.assertIn('Dice', view['unsupported'])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
        self.store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Café', 'café'))

    def test_image_without_caption_and_original_metadata_survive_restart(self):
        msg = message(text='', entities=[])
        store_message(self.store, msg)
        row = Store(self.store.path).rows('SELECT * FROM offers')[0]
        self.assertEqual(row['body'], '')
        self.assertEqual(json.loads(row['source_json'])['media']['photo']['id'], 101)
        self.assertEqual(self.store.rows('SELECT * FROM hits'), [])

    def test_album_filters_expand_all_parts_and_read_marks_whole_album(self):
        store_message(self.store, message(1, 'Café', grouped=987))
        store_message(self.store, message(2, '', grouped=987))
        store_message(self.store, message(3, 'Outra legenda', grouped=987))
        cards = self.store.feed('Café', True)
        self.assertEqual(len(cards), 1)
        self.assertEqual([p['message_id'] for p in cards[0]['parts']], [1, 2, 3])
        self.assertEqual(self.store.unread(), 1)
        self.store.mark_seen(cards[0]['id'])
        self.assertEqual(self.store.unread(), 0)
        self.assertEqual(self.store.feed(), [])
        self.assertTrue(all(row['seen'] for row in self.store.rows(
            'SELECT seen FROM offers WHERE grouped_id=?', ('987',))))

    def test_edit_updates_media_entities_and_matches_without_duplicate(self):
        store_message(self.store, message(1))
        edited = message(1, 'Outro produto', photo=False, entities=[types.MessageEntityBold(0,5)])
        store_message(self.store, edited)
        rows = self.store.rows('SELECT * FROM offers')
        self.assertEqual(len(rows), 1)
        self.assertIsNone(json.loads(rows[0]['source_json'])['media'])
        self.assertIn('<strong>Outro</strong>', str(present(rows[0])['html']))
        self.assertEqual(self.store.rows('SELECT * FROM hits'), [])

    def test_album_id_collision_across_chats_never_merges_or_marks_other_chat(self):
        self.store.execute('INSERT INTO chats VALUES(-100456,?)', ('Outro',))
        store_message(self.store, message(1, 'Café', grouped=9))
        other = message(1, 'Café outro', grouped=9)
        self.store.ingest(-100456, 1, other.raw_text, other.date.isoformat(), None, source_json=other.to_json())
        self.assertEqual(len(self.store.feed()), 2)
        self.store.mark_seen(1)
        self.assertEqual(self.store.unread(), 1)

    def test_legacy_database_is_backed_up_migrated_idempotently_and_readable(self):
        path = Path(self.tmp.name) / 'legacy.db'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE offers(id INTEGER PRIMARY KEY,chat_id INTEGER,message_id INTEGER,
            chat_title TEXT,body TEXT,url TEXT,date TEXT,seen INTEGER DEFAULT 0,UNIQUE(chat_id,message_id));
            INSERT INTO offers VALUES(7,-100123,42,'Grupo','Oferta antiga',NULL,'2026-11-04',1);
            CREATE TABLE chats(id INTEGER PRIMARY KEY,title TEXT);
            INSERT INTO chats VALUES(-100123,'Grupo');
            CREATE TABLE rules(id INTEGER PRIMARY KEY,name TEXT,keywords TEXT);
            INSERT INTO rules VALUES(3,'Antiga','antiga');
            CREATE TABLE ignored_keywords(id INTEGER PRIMARY KEY,word TEXT NOT NULL,normalized TEXT NOT NULL UNIQUE);
            INSERT INTO ignored_keywords VALUES(4,'Ignorada','ignorada');
            CREATE TABLE hits(offer_id INTEGER,rule_id INTEGER,PRIMARY KEY(offer_id,rule_id));
            INSERT INTO hits VALUES(7,3);''')
        db.close()
        migrated = Store(path)
        backup = Path(str(path) + '.before-rich-messages.db')
        self.assertTrue(backup.exists())
        snapshot = sqlite3.connect(backup)
        try:
            self.assertEqual(snapshot.execute('SELECT body FROM offers').fetchone()[0], 'Oferta antiga')
            self.assertNotIn('source_json', {r[1] for r in snapshot.execute('PRAGMA table_info(offers)')})
        finally:
            snapshot.close()
        created_at_backup = sqlite3.connect(Path(str(path) + '.before-rule-created-at.db')
                                            if Path(str(path) + '.before-rule-created-at.db').exists()
                                            else backup)
        try:
            self.assertNotIn('created_at', {r[1] for r in created_at_backup.execute('PRAGMA table_info(rules)')})
            self.assertNotIn('created_at', {r[1] for r in created_at_backup.execute('PRAGMA table_info(ignored_keywords)')})
            trigger_names = {r[0] for r in created_at_backup.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")}
            self.assertNotIn('rules_created', trigger_names)
            self.assertNotIn('ignored_created', trigger_names)
            created_at_backup.execute("INSERT INTO rules VALUES(5,'Restaurada','restaurada')")
            created_at_backup.execute("INSERT INTO ignored_keywords VALUES(6,'Restaurada','restaurada')")
        finally:
            created_at_backup.close()
        row = migrated.rows('SELECT * FROM offers')[0]
        self.assertEqual((row['id'], row['body'], row['seen']), (7, 'Oferta antiga', 1))
        self.assertIsNone(row['source_json'])
        self.assertEqual(migrated.rows('SELECT * FROM hits'), [{'offer_id': 7, 'rule_id': 3}])
        self.assertEqual(migrated.rows('SELECT name FROM rules'), [{'name': 'antiga'}])
        self.assertIn('Oferta antiga', str(present(row)['html']))
        original_backup = backup.read_bytes()
        Store(path)
        self.assertEqual(original_backup, backup.read_bytes())
        migrated.execute('INSERT INTO offers(chat_id,message_id,chat_title,body,date) VALUES(?,?,?,?,?)',(-100123,43,'Grupo','Old writer','2026'))
        self.assertEqual(len(migrated.rows('SELECT * FROM offers')), 2)


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root/'offers.db')
        self.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
        self.telegram = Telegram(self.store, self.root, None, None)
        self.telegram.client = AsyncMock()
        self.telegram.client.is_connected = Mock(return_value=True)
        self.telegram.client.is_user_authorized.return_value = True
        self.msg = message()
        store_message(self.store, self.msg)
        self.offer = self.store.rows('SELECT * FROM offers')[0]
        self.telegram.client.get_messages.return_value = self.msg

    async def test_cache_atomic_download_and_offline_reuse(self):
        async def download(msg, *, file, **kwargs):
            file.write(b'fake-photo')
            return file
        self.telegram.client.download_media.side_effect = download
        path = await self.telegram.download(self.offer)
        self.assertEqual(path.read_bytes(), b'fake-photo')
        self.telegram.client.is_user_authorized.return_value = False
        self.assertEqual(await self.telegram.download(self.offer), path)
        self.telegram.client.download_media.assert_awaited_once()
        self.assertEqual(list(self.telegram.media_dir.glob('.download-*')), [])

    async def test_media_cache_cleanup_keeps_logically_deleted_and_removes_purged_files(self):
        async def download(msg, *, file, **kwargs):
            file.write(b'fake-photo')
            return file
        self.telegram.client.download_media.side_effect = download
        cached = await self.telegram.download(self.offer)
        orphan = self.telegram.media_dir / ('0' * 64)
        orphan.write_bytes(b'orphan')
        temporary = self.telegram.media_dir / '.download-active'
        temporary.write_bytes(b'in progress')

        self.assertEqual(self.telegram.cleanup_media_cache(), 1)
        self.assertTrue(cached.exists())
        self.assertTrue(temporary.exists())
        self.store.delete_offer(self.offer['id'])
        self.assertEqual(self.telegram.cleanup_media_cache(), 0)
        self.assertTrue(cached.exists())

        expired = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.store.execute('UPDATE offers SET deleted_at=? WHERE id=?', (expired, self.offer['id']))
        self.store.expire_offers(datetime.now(timezone.utc))
        self.assertEqual(self.telegram.cleanup_media_cache(), 1)
        self.assertFalse(cached.exists())
        self.assertTrue(temporary.exists())

    async def test_failed_download_removes_partial_file_and_retry_succeeds(self):
        async def broken(msg, *, file, **kwargs):
            file.write(b'partial')
            raise OSError('simulated failure')
        self.telegram.client.download_media.side_effect = broken
        with self.assertRaises(OSError):
            await self.telegram.download(self.offer)
        self.assertEqual(list(self.telegram.media_dir.iterdir()), [])
        async def success(msg, *, file, **kwargs):
            file.write(b'complete')
            return file
        self.telegram.client.download_media.side_effect = success
        self.assertEqual((await self.telegram.download(self.offer)).read_bytes(), b'complete')

    async def test_changed_media_and_temporary_media_are_not_downloaded(self):
        self.telegram.client.get_messages.return_value = message(2)
        with self.assertRaisesRegex(ValueError, 'mudou'):
            await self.telegram.download(self.offer)
        ephemeral = message()
        ephemeral.media.ttl_seconds = 10
        row = {**self.offer, 'source_json': ephemeral.to_json()}
        with self.assertRaises(ValueError):
            await self.telegram.download(row)
        self.telegram.client.download_media.assert_not_awaited()

    async def test_disk_reserve_aborts_and_cleans_partial_download(self):
        async def download(msg, *, file, progress_callback, **kwargs):
            file.write(b'partial')
            progress_callback(7, 100)
        self.telegram.client.download_media.side_effect = download
        with patch('app.telegram.shutil.disk_usage', side_effect=[SimpleNamespace(free=1024**3), SimpleNamespace(free=1)]):
            with self.assertRaises(OSError):
                await self.telegram.download(self.offer)
        self.assertEqual(list(self.telegram.media_dir.iterdir()), [])

    async def test_refresh_legacy_album_only_collects_matching_group(self):
        one, two, unrelated = message(1, grouped=77), message(2, '', grouped=77), message(3, 'Não coletar', grouped=88)
        self.telegram.client.get_messages.side_effect = [one, [one, two, unrelated]]
        await self.telegram.refresh(self.offer)
        self.assertEqual([r['message_id'] for r in self.store.rows('SELECT * FROM offers ORDER BY message_id')], [1,2])
        self.assertEqual(len(self.store.feed()[0]['parts']), 2)


class MediaWebTests(unittest.TestCase):
    def setUp(self):
        from app import main
        self.main = main
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root/'offers.db')
        self.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
        store_message(self.store, message(1, '😀 Oferta', entities=[types.MessageEntityBold(3,6)]))
        self.patch = patch.object(main, 'store', self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(main.app)
        self.auth = {'panel_session': 'test-session'}
        main.sessions['test-session'] = __import__('time').monotonic() + 60

    def test_rich_caption_private_photo_and_legacy_recovery_action(self):
        page = self.client.get('/', cookies=self.auth)
        self.assertIn('<strong>Oferta</strong>', page.text)
        self.assertIn('src="/offers/1/media"', page.text)
        self.assertEqual(self.client.get('/offers/1/media', follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get('/offers/999/media', cookies=self.auth).status_code, 404)
        self.assertEqual(self.client.post('/offers/1/refresh', cookies=self.auth).status_code, 403)
        image = self.root/'image'
        image.write_bytes(b'jpeg-data')
        with patch.object(self.main.telegram, 'download', AsyncMock(return_value=image)):
            response = self.client.get('/offers/1/media', cookies=self.auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['content-type'], 'image/jpeg')
            self.assertEqual(response.content, b'jpeg-data')
            partial = self.client.get('/offers/1/media', cookies=self.auth, headers={'Range': 'bytes=0-3'})
            self.assertEqual(partial.status_code, 206)
            self.assertEqual(partial.content, b'jpeg')
        with patch.object(self.main.telegram, 'download', AsyncMock(side_effect=ValueError('Mídia indisponível'))):
            self.assertEqual(self.client.get('/offers/1/media', cookies=self.auth).status_code, 409)
        with patch.object(self.main.telegram, 'refresh', AsyncMock()):
            response = self.client.post('/offers/1/refresh', cookies=self.auth, follow_redirects=False,
                data={'csrf': self.main.csrf_token, 'q': 'Oferta', 'alerts': 'true'})
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.headers['location'].startswith('/alerts?'))
            self.assertTrue(response.headers['location'].endswith('#message-1'))

    def test_untrusted_document_types_download_as_attachment_and_paths_are_not_used(self):
        source = json.loads(message(photo=False).to_json())
        source['media'] = {'_': 'MessageMediaDocument', 'document': {'_': 'Document', 'id': 4, 'size': 9,
            'mime_type': 'image/svg+xml', 'attributes': [{'_': 'DocumentAttributeFilename', 'file_name': '../../evil.svg'}]}}
        self.store.execute('UPDATE offers SET source_json=? WHERE id=1', (json.dumps(source),))
        self.assertNotIn('/', media_info(source)['name'])
        file = self.root/'document'
        file.write_bytes(b'<svg onload="evil()"/>')
        with patch.object(self.main.telegram, 'download', AsyncMock(return_value=file)):
            response = self.client.get('/offers/1/media', cookies=self.auth)
            self.assertEqual(response.headers['content-type'], 'application/octet-stream')
            self.assertTrue(response.headers['content-disposition'].startswith('attachment'))
