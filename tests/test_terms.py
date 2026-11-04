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
            self.assertIn('2 ofertas', page.text)
            self.assertNotIn('álbum', page.text.lower())
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

    def test_frequencies_exclude_ignored_offers_and_whole_albums(self):
        self.add(1, 'Cafeteira PS5!')
        self.add(2, 'Cafeteira (ps5)')
        self.add(3, 'Cafeteira de viagem', 42)
        self.add(4, 'Oferta PS5', 42)
        self.add(5, 'Cafeteira doméstica')
        self.add(6, 'Cafeteira doméstica')
        self.add(7, 'Cafeteira PS5pro')
        self.assertEqual(next(t['count'] for t in self.store.frequent_terms() if t['word'] == 'cafeteira'), 6)
        self.store.add_ignored('PS5')
        terms = {normalize(t['word']): t['count'] for t in self.store.frequent_terms()}
        self.assertEqual(terms['cafeteira'], 3)
        self.assertEqual(len(self.store.feed()), 3)
        self.assertEqual(len(self.store.feed(alerts=True)), 3)
        self.assertEqual(self.store.unread(), 3)
        self.store.execute('DELETE FROM ignored_keywords')
        self.assertEqual(next(t['count'] for t in self.store.frequent_terms() if t['word'] == 'cafeteira'), 6)

    def test_hidden_phrases_hide_contained_whole_terms_and_restore(self):
        self.add(1, 'Preço baixo PS5pro preço baixote')
        self.add(2, 'preco baixo PS5pro preco baixote')
        self.store.hide_suggestion('PREÇO BAIXO')
        terms = {normalize(t['word']) for t in self.store.frequent_terms()}
        self.assertNotIn('preco', terms)
        self.assertNotIn('baixo', terms)
        self.assertNotIn('preco baixo', terms)
        self.assertIn('baixote', terms)
        self.assertIn('ps5pro', terms)
        self.assertIn('preco baixo ps5pro', terms)
        self.store.hide_suggestion('preço excelente')
        self.store.execute('DELETE FROM hidden_suggestions WHERE normalized=?', ('preco baixo',))
        terms = {normalize(t['word']) for t in self.store.frequent_terms()}
        self.assertNotIn('preco', terms)
        self.assertIn('baixo', terms)
        self.assertIn('preco baixo', terms)
        self.store.execute('DELETE FROM hidden_suggestions')
        self.assertIn('preco', {normalize(t['word']) for t in self.store.frequent_terms()})

    def test_batch_actions_are_atomic_and_preserve_alerts(self):
        self.add(1, 'PS5 promoção preço baixo')
        self.add(2, 'PS5 promoção preço baixo')
        with self.assertRaises(ValueError):
            self.store.add_terms_batch('hide', ['promoção', '   '])
        self.assertEqual(self.store.rows('SELECT * FROM hidden_suggestions'), [])
        self.assertEqual(self.store.add_terms_batch('hide', ['promoção', 'PROMOCAO', 'preço baixo']), 2)
        self.assertEqual(len(self.store.feed()), 2)
        self.assertEqual(self.store.unread(), 2)
        self.assertEqual(self.store.add_terms_batch('ignore', ['PS5', 'outro']), 2)
        self.assertEqual(self.store.feed(), [])
        self.assertEqual(self.store.unread(), 2)
        with self.assertRaises(ValueError):
            self.store.add_terms_batch('ignore', ['x'] * 51)
        with self.assertRaises(ValueError):
            self.store.add_terms_batch('wrong', ['x'])
        self.assertEqual(len(self.store.rows('SELECT * FROM ignored_keywords')), 2)

    def test_batch_endpoint_csrf_validation_and_fallback(self):
        with patch.object(main, 'store', self.store):
            client = TestClient(main.app)
            token = 'test-batch-session'
            main.sessions[token] = time.monotonic() + 60
            self.addCleanup(main.sessions.pop, token, None)
            cookies = {'panel_session': token}
            headers = {'Accept': 'application/json'}
            self.assertEqual(client.post('/terms/batch', cookies=cookies, data={'action': 'hide', 'words': ['PS5']}).status_code, 403)
            empty = client.post('/terms/batch', cookies=cookies, headers=headers, data={'csrf': main.csrf_token, 'action': 'hide'})
            self.assertEqual(empty.status_code, 400)
            self.assertIn('Selecione', empty.json()['message'])
            saved = client.post('/terms/batch', cookies=cookies, headers=headers, data={'csrf': main.csrf_token, 'action': 'hide', 'words': ['PS5', 'promoção']})
            self.assertEqual(saved.status_code, 200)
            self.assertIn('2 termos adicionados', saved.json()['message'])
            self.assertEqual(len(self.store.rows('SELECT * FROM hidden_suggestions')), 2)
            fallback = client.post('/terms/batch', cookies=cookies, follow_redirects=False,
                data={'csrf': main.csrf_token, 'action': 'ignore', 'words': ['PS5', 'promoção'], 'page': '2'})
            self.assertEqual(fallback.status_code, 303)
            self.assertIn('page=2', fallback.headers['location'])
            self.assertEqual(len(self.store.rows('SELECT * FROM ignored_keywords')), 2)

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
