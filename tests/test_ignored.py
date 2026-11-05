import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.store import Store, ignored_matches, matches

_runtime = tempfile.TemporaryDirectory()
os.environ.update(DATA_DIR=_runtime.name, APP_PASSWORD='test-password-with-32-characters',
                  TELEGRAM_API_ID='', TELEGRAM_API_HASH='')
from app import main


class IgnoredWordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
        self.store.execute('INSERT INTO rules VALUES(1,?,?)', ('Notebook', 'notebook'))

    def add_offer(self, message_id, text, grouped=None):
        source = json.dumps({'_': 'Message', 'grouped_id': grouped}) if grouped is not None else None
        self.store.ingest(-100123, message_id, text, '2026-11-04', None, source_json=source)

    def test_whole_words_with_punctuation_case_and_accents(self):
        for text in ('PS5', 'PS5 no início', 'final PS5', '(PS5)', 'PS5!', 'x/ps5,y', 'PS5_pro', '🔥PS5🎮'):
            with self.subTest(text=text):
                self.assertTrue(ignored_matches(text, 'PS5'))
        for text in ('PS55', 'xPS5', 'PS5pro', 'superPS5oferta', 'PS5á'):
            with self.subTest(text=text):
                self.assertFalse(ignored_matches(text, 'ps5'))
        self.assertTrue(ignored_matches('CAFÉ em oferta!', 'café'))
        self.assertFalse(ignored_matches('cafeteira em oferta', 'café'))
        self.assertTrue(ignored_matches('Console (PS5 PRO)!', 'ps5 pro'))
        self.assertFalse(matches('PS5_pro', 'PS5'))

    def test_ignore_applies_to_existing_and_new_offers_but_not_alerts(self):
        self.add_offer(1, 'Notebook e PS5!')
        self.assertEqual(self.store.unread(), 1)
        self.assertTrue(self.store.add_ignored(' PS5 '))
        self.assertFalse(self.store.add_ignored('ps5'))
        self.add_offer(2, 'Notebook com ps5, promoção')
        self.add_offer(3, 'Notebook para PS5pro')
        self.assertEqual([o['message_id'] for o in self.store.feed()], [3])
        self.assertEqual({o['message_id'] for o in self.store.feed(alerts=True)}, {1, 2, 3})
        self.assertEqual(self.store.unread(), 3)
        self.assertEqual(len(self.store.rows('SELECT * FROM hits')), 3)
        self.store.execute('DELETE FROM ignored_keywords')
        self.assertEqual(len(self.store.feed()), 3)
        self.assertEqual(self.store.unread(), 3)

    def test_ignore_album_if_any_part_matches_but_keep_alert_and_other_chat(self):
        self.store.add_ignored('PS5')
        self.add_offer(1, 'Notebook', grouped=55)
        self.add_offer(2, 'Acompanha PS5.', grouped=55)
        self.store.execute('INSERT INTO chats VALUES(-100456,?)', ('Outro',))
        self.store.ingest(-100456, 1, 'Notebook normal', '2026-11-04', None,
                          source_json=json.dumps({'grouped_id': 55}))
        self.assertEqual([o['chat_id'] for o in self.store.feed()], [-100456])
        cards = self.store.feed(alerts=True)
        album = next(o for o in cards if o['chat_id'] == -100123)
        self.assertEqual([p['message_id'] for p in album['parts']], [1, 2])
        self.assertEqual(self.store.unread(), 2)
        self.store.mark_seen(album['id'])
        self.assertEqual(self.store.unread(), 1)

    def test_filter_before_limit_keeps_older_visible_items(self):
        self.store.add_ignored('PS5')
        self.add_offer(1, 'Oferta visível')
        for i in range(2, 112):
            self.add_offer(i, 'PS5 em promoção')
        self.assertEqual([o['message_id'] for o in self.store.feed()], [1])
        self.assertEqual(len(self.store.rows('SELECT * FROM offers')), 111)

    def test_read_sections_keep_album_together_and_filter_before_limit(self):
        self.add_offer(1, 'Notebook parte 1', grouped=55)
        self.add_offer(2, 'Notebook parte 2', grouped=55)
        self.store.execute('UPDATE offers SET seen=1 WHERE message_id=1')
        for i in range(3, 106):
            self.add_offer(i, 'Notebook lido')
            self.store.mark_seen(i)
        unread = self.store.feed(alerts=True, read=False)
        self.assertEqual(len(unread), 1)
        self.assertEqual(len(unread[0]['parts']), 2)
        self.assertFalse(unread[0]['seen'])
        self.assertEqual(len(self.store.feed(alerts=True, read=True)), 100)
        self.store.mark_seen(unread[0]['id'])
        self.assertEqual(self.store.feed(alerts=True, read=False), [])
        self.assertEqual(self.store.unread(), 0)

    def test_new_offers_respect_filters_and_count_albums_once(self):
        self.add_offer(1, 'Notebook antigo', grouped=11)
        marker = self.store.rows('SELECT max(id) AS id FROM offers')[0]['id']
        self.store.add_ignored('PS5')
        self.add_offer(2, 'Notebook parte antiga', grouped=11)
        self.add_offer(3, 'Notebook novo', grouped=12)
        self.add_offer(4, 'Outra parte', grouped=12)
        self.add_offer(5, 'Notebook PS5')
        self.add_offer(6, 'Oferta diferente')
        self.assertEqual(self.store.new_offers(marker), 2)
        self.assertEqual(self.store.new_offers(marker, 'Notebook'), 1)
        self.assertEqual(self.store.new_offers(marker, alerts=True), 2)
        self.assertEqual(self.store.new_offers(marker, 'Notebook', True), 2)

    def test_recent_index_is_added_to_existing_database_and_used_for_feed(self):
        self.add_offer(1, 'Oferta antiga')
        self.store.execute('DROP INDEX offers_recent')
        reopened = Store(self.store.path)
        self.assertEqual(reopened.rows('SELECT message_id, body FROM offers'),
                         [{'message_id': 1, 'body': 'Oferta antiga'}])
        with reopened.connect() as db:
            reopened._register_ignored_filter(db)
            where, args = reopened.feed_filter()
            plan = [dict(row) for row in db.execute('EXPLAIN QUERY PLAN SELECT o.id FROM offers o ' + where +
                                                    ' ORDER BY date DESC,id DESC LIMIT 100', args)]
        self.assertTrue(any('offers_recent' in row['detail'] for row in plan))
        self.assertEqual(reopened.feed()[0]['message_id'], 1)

    def test_persistence_and_additive_migration_preserve_existing_data(self):
        self.add_offer(1, 'Notebook PS5')
        self.store.execute('DROP TABLE ignored_keywords')
        reopened = Store(self.store.path)
        self.assertEqual(len(reopened.rows('SELECT * FROM offers')), 1)
        self.assertEqual(len(reopened.rows('SELECT * FROM hits')), 1)
        self.assertTrue(reopened.add_ignored('Café'))
        self.assertFalse(reopened.add_ignored('cafe'))
        with self.assertRaises(ValueError):
            reopened.add_ignored(' \u0301 ')
        self.assertEqual(Store(self.store.path).rows('SELECT word FROM ignored_keywords'), [{'word': 'Café'}])


class IgnoredWordsWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
        self.store.execute('INSERT INTO rules VALUES(1,?,?)', ('Notebook', 'notebook'))
        self.store.ingest(-100123, 1, 'Notebook e PS5!', '2026-11-04', None)
        self.patch = patch.object(main, 'store', self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(main.app)
        self.auth = {'panel_session': 'test-session'}
        main.sessions['test-session'] = __import__('time').monotonic() + 60

    def test_poll_requires_auth_and_reports_matching_new_offers(self):
        self.assertEqual(self.client.get('/offers/new?after=1', headers={'Accept': 'application/json'}).status_code, 401)
        self.store.ingest(-100123, 2, 'Notebook', '2026-11-04', None)
        self.assertEqual(self.client.get('/offers/new?after=1', cookies=self.auth).json(), {'count': 1})
        self.assertEqual(self.client.get('/offers/new?after=-1', cookies=self.auth).status_code, 400)

    def test_collapsed_menu_auth_csrf_add_delete_and_alert_view(self):
        page = self.client.get('/', cookies=self.auth)
        self.assertNotIn('id="ignored-settings"', page.text)
        self.assertIn('id="ignored-settings"', self.client.get('/ignored', cookies=self.auth).text)
        self.assertIn('Palavras ignoradas', page.text)
        self.assertEqual(self.client.post('/ignored', data={'word': 'PS5'}, follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/ignored', cookies=self.auth, data={'word': 'PS5'}).status_code, 403)
        data = {'word': 'PS5', 'csrf': main.csrf_token, 'q': 'Notebook', 'alerts': 'false'}
        response = self.client.post('/ignored', cookies=self.auth, data=data, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['location'].startswith('/ignored?'))
        self.assertNotIn('class="offer-card"', self.client.get('/', cookies=self.auth).text)
        alerts = self.client.get('/?alerts=true', cookies=self.auth)
        self.assertIn('Notebook e PS5!', alerts.text)
        self.assertIn('Novo alerta', alerts.text)
        duplicate = self.client.post('/ignored', cookies=self.auth, data={**data, 'word': 'ps5'}, headers={'Accept': 'application/json'})
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('já está no filtro', duplicate.json()['message'])
        response = self.client.post('/ignored/1/delete', cookies=self.auth,
                                    data={'csrf': main.csrf_token, 'alerts': 'true', 'q': 'Notebook'},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['location'].startswith('/ignored?'))
        self.assertIn('Notebook e PS5!', self.client.get('/', cookies=self.auth).text)
        self.assertEqual(self.store.unread(), 1)

    def test_invalid_and_html_words_are_handled_safely(self):
        data = {'csrf': main.csrf_token, 'word': '   '}
        response = self.client.post('/ignored', cookies=self.auth, data=data, headers={'Accept': 'application/json'})
        self.assertIn('Informe uma palavra', response.json()['message'])
        self.assertEqual(self.store.rows('SELECT * FROM ignored_keywords'), [])
        response = self.client.post('/ignored', cookies=self.auth,
                                    data={'csrf': main.csrf_token, 'word': '<script>alert(1)</script>'}, follow_redirects=False)
        response = self.client.get('/ignored', cookies=self.auth)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', response.text)
        self.assertNotIn('<script>alert(1)</script>', response.text)
