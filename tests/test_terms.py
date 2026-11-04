import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.store import Store, normalize

_runtime = tempfile.TemporaryDirectory()
os.environ.update(DATA_DIR=_runtime.name, APP_PASSWORD='test-password-with-32-characters')
from app import main


class FrequentTermsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
        self.store.execute('INSERT INTO rules VALUES(1,?,?)', ('Alerta', 'ps5'))

    def add(self, number, body, group=None):
        source = json.dumps({'grouped_id': group}) if group is not None else None
        return self.store.ingest(1, number, body, '2026-11-04', None, source_json=source)

    def test_counts_distinct_offers_and_albums_normalizing_terms(self):
        self.add(1, 'Preço baixo PS5 preço baixo PS5 https://exemplo.com/barato', 10)
        self.add(2, 'PREÇO BAIXO PS5', 10)
        self.add(3, 'preco baixo PS5')
        self.add(4, 'preço baixo')
        counts = {normalize(term['word']): term['count'] for term in self.store.frequent_terms()}
        self.assertEqual(counts['preco baixo'], 3)
        self.assertEqual(counts['preco baixo ps5'], 2)
        self.assertEqual(counts['ps5'], 2)
        self.assertNotIn('https', counts)
        self.assertNotIn('de', counts)

    def test_persistent_hidden_suggestions_do_not_change_offers_or_alerts(self):
        self.add(1, 'PS5 promoção')
        self.add(2, 'ps5 promocao')
        self.assertEqual(self.store.unread(), 2)
        self.assertTrue(self.store.hide_suggestion('PROMOÇÃO'))
        self.assertFalse(self.store.hide_suggestion('promocao'))
        reopened = Store(self.store.path)
        self.assertNotIn('promoção', [term['word'] for term in reopened.frequent_terms()])
        self.assertEqual(len(reopened.feed()), 2)
        self.assertEqual(reopened.unread(), 2)
        reopened.execute('DELETE FROM hidden_suggestions')
        self.assertIn('promoção', [term['word'] for term in reopened.frequent_terms()])
        reopened.add_ignored('PS5')
        self.assertNotIn('ps5', [term['word'] for term in reopened.frequent_terms()])
        self.assertEqual(len(reopened.feed()), 0)
        self.assertEqual(len(reopened.feed(alerts=True)), 2)
        self.assertEqual(reopened.unread(), 2)

    def test_page_actions_auth_csrf_and_restoration(self):
        self.add(1, 'PS5 promoção')
        self.add(2, 'PS5 promoção')
        with patch.object(main, 'store', self.store):
            client = TestClient(main.app)
            token = 'test-terms-session'
            main.sessions[token] = time.monotonic() + 60
            self.addCleanup(main.sessions.pop, token, None)
            cookies = {'panel_session': token}
            self.assertEqual(client.get('/terms', follow_redirects=False).status_code, 303)
            page = client.get('/terms', cookies=cookies)
            self.assertIn('promoção', page.text)
            self.assertIn('2 ofertas/álbuns', page.text)
            self.assertEqual(client.post('/terms/hide', cookies=cookies, data={'word': 'promoção'}).status_code, 403)
            headers = {'Accept': 'application/json'}
            data = {'csrf': main.csrf_token, 'word': 'promoção'}
            self.assertTrue(client.post('/terms/hide', cookies=cookies, data=data, headers=headers).json()['ok'])
            self.assertEqual(len(self.store.feed()), 2)
            self.assertEqual(self.store.unread(), 2)
            hidden_id = self.store.rows('SELECT id FROM hidden_suggestions')[0]['id']
            self.assertTrue(client.post(f'/terms/restore/{hidden_id}', cookies=cookies, data={'csrf': main.csrf_token}, headers=headers).json()['ok'])
            self.assertEqual(self.store.rows('SELECT * FROM hidden_suggestions'), [])
            result = client.post('/terms/ignore', cookies=cookies, data={'csrf': main.csrf_token, 'word': 'PS5'}, follow_redirects=False)
            self.assertEqual(result.status_code, 303)
            self.assertTrue(result.headers['location'].startswith('/terms?'))
            self.assertEqual(self.store.feed(), [])
            self.assertEqual(self.store.unread(), 2)

    def test_old_database_upgrade_is_additive_and_pagination(self):
        self.store.execute('DROP TABLE hidden_suggestions')
        self.add(1, ' '.join(f'produto{i}' for i in range(60)))
        self.add(2, ' '.join(f'produto{i}' for i in range(60)))
        old_rows = self.store.rows('SELECT * FROM offers')
        reopened = Store(self.store.path)
        self.assertEqual(reopened.rows('SELECT * FROM offers'), old_rows)
        reopened.hide_suggestion('produto1')
        with patch.object(main, 'store', reopened):
            client = TestClient(main.app)
            token = 'test-terms-page'
            main.sessions[token] = time.monotonic() + 60
            self.addCleanup(main.sessions.pop, token, None)
            response = client.get('/terms?page=2', cookies={'panel_session': token})
            self.assertIn('Página 2 de ', response.text)
            self.assertIn('Anterior', response.text)


if __name__ == '__main__':
    unittest.main()
