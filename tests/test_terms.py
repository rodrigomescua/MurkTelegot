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
        self.store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Alerta', 'ps5'))

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
        self.assertNotIn('ps5', counts)
        self.assertNotIn('https', counts)
        self.assertNotIn('de', counts)

    def test_sorts_terms_by_frequency_word_count_then_character_count(self):
        for number in (1, 2):
            self.add(number, 'produto novo especial produto novinho')
        self.add(3, 'produto novo especial')
        terms = self.store.frequent_terms()
        positions = {term['word']: index for index, term in enumerate(terms)}
        counts = {term['word']: term['count'] for term in terms}
        self.assertGreater(counts['produto novo especial'], counts['produto novinho'])
        self.assertLess(positions['produto novo especial'], positions['produto novinho'])

    def test_more_words_precede_fewer_words_when_frequency_is_equal(self):
        for number in (1, 2):
            self.add(number, 'produto novo especial produto novinho')
        terms = self.store.frequent_terms()
        positions = {term['word']: index for index, term in enumerate(terms)}
        self.assertLess(positions['produto novo especial'], positions['produto novinho'])
        self.assertLess(positions['produto novinho'], positions['especial'])

    def test_longer_phrase_precedes_shorter_phrase_with_same_frequency_and_word_count(self):
        for number in (1, 2):
            self.add(number, 'casa azul grande casa azul maior')
        terms = self.store.frequent_terms()
        positions = {term['word']: index for index, term in enumerate(terms)}
        self.assertLess(positions['casa azul grande'], positions['casa azul maior'])

    def test_extractions_replace_original_terms_and_empty_names_suppress_them(self):
        plain = self.add(1, 'Cafeteira original')
        unnamed = self.add(2, 'Cafeteira original')
        album_root = self.add(3, 'Cafeteira original', 10)
        self.add(4, 'Cafeteira original', 10)
        for offer_id, name in ((plain, 'Cafeteira extraída'), (unnamed, ''), (album_root, 'Cafeteira extraída')):
            self.store.execute('''INSERT INTO offer_extractions
                (offer_id,product_name,job_id,updated_at) VALUES(?,?,1,'now')''', (offer_id, name))

        terms = {normalize(term['word']): term['count'] for term in self.store.frequent_terms()}
        self.assertEqual(terms[normalize('cafeteira extraída')], 2)
        self.assertNotIn(normalize('cafeteira original'), terms)
        self.assertNotIn('original', terms)
        matching, total = self.store.term_offers('Cafeteira extraída')
        self.assertEqual(total, 2)
        self.assertEqual(sorted(len(card['parts']) for card in matching), [1, 2])
        self.assertEqual(self.store.term_offers('Cafeteira original')[1], 0)

    def test_extracted_terms_count_all_offers_across_pages(self):
        for number in range(1, 106):
            offer_id = self.add(number, 'Texto original diferente')
            self.store.execute('''INSERT INTO offer_extractions
                (offer_id,product_name,job_id,updated_at) VALUES(?,?,1,'now')''',
                               (offer_id, 'Produto extraído'))
        count = next(term['count'] for term in self.store.frequent_terms()
                     if normalize(term['word']) == normalize('produto extraído'))
        first, total = self.store.term_offers('produto extraído', 1, 100)
        second, _ = self.store.term_offers('produto extraído', 2, 100)
        self.assertEqual(count, 105)
        self.assertEqual(total, 105)
        self.assertEqual((len(first), len(second)), (100, 5))
        self.assertEqual(self.store.term_offers('texto original')[1], 0)

    def test_numeric_and_short_terms_are_filtered_with_configurable_minimum(self):
        for number in (1, 2):
            self.add(number, '123 1234 tiny small medium larger')
        terms = {normalize(term['word']) for term in self.store.frequent_terms()}
        self.assertNotIn('123', terms)
        self.assertNotIn('1234', terms)
        self.assertIn('small', terms)
        self.store.save_frequent_terms_min_chars(6)
        terms = {normalize(term['word']) for term in self.store.frequent_terms()}
        self.assertNotIn('small', terms)
        self.assertIn('medium', terms)
        with self.assertRaises(ValueError):
            self.store.add_ignored('small')
        with self.assertRaises(ValueError):
            self.store.hide_suggestion('1234')
        with self.assertRaises(ValueError):
            self.store.save_frequent_terms_min_chars(3)

    def test_startup_removes_invalid_ignored_keywords(self):
        self.store.execute("INSERT INTO ignored_keywords(word,normalized) VALUES('123','123')")
        self.store.execute("INSERT INTO ignored_keywords(word,normalized) VALUES('abc','abc')")
        self.store.execute("INSERT INTO ignored_keywords(word,normalized) VALUES('valid','valid')")
        reopened = Store(self.store.path)
        self.assertEqual(reopened.rows('SELECT word FROM ignored_keywords'), [{'word': 'valid'}])
        self.assertTrue(reopened.add_ignored('abcd'))
        with self.assertRaises(ValueError):
            reopened.add_ignored('12345')

    def test_term_offer_lookup_matches_exact_normalized_phrases_and_pages_albums(self):
        self.add(1, 'Preço baixo! PS5 oferta', 10)
        self.add(2, 'preco baixo PS5 https://exemplo.test/preço/baixo', 10)
        self.add(3, 'PRECO BAIXO PS5')
        self.add(4, 'preço baixote PS5')
        self.add(5, 'preço baixo PS5')
        self.add(6, 'preço baixo PS5')
        first, total = self.store.term_offers('PRECO BAIXO', 1, 2)
        second, _ = self.store.term_offers('preço baixo', 2, 2)
        self.assertEqual(total, 4)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(sum(len(card['parts']) for card in first + second), 5)
        self.assertNotIn(4, [part['message_id'] for card in first + second for part in card['parts']])
        self.store.add_ignored('preço baixo')
        self.assertEqual(self.store.term_offers('preço baixo')[1], 0)
        self.assertEqual(self.store.unread(), 5)

    def test_term_lookup_matches_frequency_for_decomposed_unicode_and_over_100_offers(self):
        for number in range(1, 105):
            self.add(number, 'Cafe\u0301 especial PS5')
        self.add(105, 'PS5 item inicial', 200)
        self.add(106, 'CAFÉ especial PS5', 200)
        frequency = next(term['count'] for term in self.store.frequent_terms()
                         if normalize(term['word']) == normalize('café especial'))
        album_page, total = self.store.term_offers('cafe\u0301 especial', 1)
        last_page, _ = self.store.term_offers('café especial', 6)
        self.assertEqual(frequency, 105)
        self.assertEqual(total, frequency)
        self.assertEqual(len(last_page), 5)
        self.assertEqual(len(album_page[0]['parts']), 2)

    def test_logically_deleted_offers_and_albums_are_excluded_from_terms(self):
        self.add(1, 'Cafeteira elétrica')
        self.add(2, 'Cafeteira elétrica')
        self.add(3, 'Cafeteira elétrica')
        self.add(4, 'Cafeteira elétrica', 40)
        self.add(5, 'Cafeteira elétrica', 40)

        count = lambda: next(term['count'] for term in self.store.frequent_terms()
                             if normalize(term['word']) == normalize('cafeteira elétrica'))
        self.assertEqual(count(), 4)
        self.assertEqual(self.store.term_offers('cafeteira elétrica')[1], 4)

        self.store.delete_offer(self.store.rows('SELECT id FROM offers WHERE message_id=1')[0]['id'])
        self.assertEqual(count(), 3)
        self.assertEqual(self.store.term_offers('cafeteira elétrica')[1], 3)

        album_id = self.store.rows('SELECT id FROM offers WHERE message_id=4')[0]['id']
        self.store.delete_offer(album_id)
        self.assertEqual(count(), 2)
        cards, total = self.store.term_offers('cafeteira elétrica')
        self.assertEqual(total, 2)
        visible_ids = {part['message_id'] for card in cards for part in card['parts']}
        self.assertEqual(visible_ids, {2, 3})

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
        reopened.add_ignored('promoção')
        self.assertNotIn('promoção', [term['word'] for term in reopened.frequent_terms()])
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
            self.assertIn('name="auto_delete" value="true"', page.text)
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
            result = client.post('/terms/ignore', cookies=cookies,
                                 data={'csrf': main.csrf_token, 'word': 'promoção', 'auto_delete': 'true'},
                                 follow_redirects=False)
            self.assertEqual(result.status_code, 303)
            self.assertTrue(result.headers['location'].startswith('/terms?'))
            self.assertEqual(self.store.rows('SELECT * FROM offers'), [])
            self.assertEqual(self.store.rows('SELECT * FROM hits'), [])
            self.assertEqual(self.store.unread(), 0)

    def test_frequencies_exclude_ignored_offers_and_whole_albums(self):
        self.add(1, 'Cafeteira PS5 Slim!')
        self.add(2, 'Cafeteira (ps5 slim)')
        self.add(3, 'Cafeteira de viagem', 42)
        self.add(4, 'Oferta PS5 Slim', 42)
        self.add(5, 'Cafeteira doméstica')
        self.add(6, 'Cafeteira doméstica')
        self.add(7, 'Cafeteira PS5pro')
        self.assertEqual(next(t['count'] for t in self.store.frequent_terms() if t['word'] == 'cafeteira'), 6)
        self.store.add_ignored('PS5 Slim')
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
        self.assertEqual(self.store.add_terms_batch('ignore', ['ps5 promoção', 'outro']), 2)
        self.assertEqual(self.store.feed(), [])
        self.assertEqual(self.store.unread(), 2)
        with self.assertRaises(ValueError):
            self.store.add_terms_batch('ignore', ['x'] * 51)
        with self.assertRaises(ValueError):
            self.store.add_terms_batch('wrong', ['x'])
        self.assertEqual(len(self.store.rows('SELECT * FROM ignored_keywords')), 2)

    def test_batch_ignore_can_enable_auto_delete_and_remove_existing_offers(self):
        self.add(1, 'Notebook promoção preço baixo')
        self.add(2, 'Oferta sem os termos')

        self.assertEqual(self.store.add_terms_batch('ignore', ['promoção', 'preço baixo'], auto_delete=True), 2)

        self.assertEqual(self.store.rows('SELECT message_id FROM offers'), [{'message_id': 2}])
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords ORDER BY id'),
                         [{'auto_delete': 1}, {'auto_delete': 1}])

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
            saved = client.post('/terms/batch', cookies=cookies, headers=headers, data={'csrf': main.csrf_token, 'action': 'hide', 'words': ['PS5 Slim', 'promoção']})
            self.assertEqual(saved.status_code, 200)
            self.assertIn('2 termos adicionados', saved.json()['message'])
            self.assertEqual(len(self.store.rows('SELECT * FROM hidden_suggestions')), 2)
            fallback = client.post('/terms/batch', cookies=cookies, follow_redirects=False,
                data={'csrf': main.csrf_token, 'action': 'ignore', 'words': ['PS5 Slim', 'promoção'], 'page': '2'})
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

    def test_term_offers_route_auth_and_validation(self):
        self.add(1, 'Promoção bonita')
        with patch.object(main, 'store', self.store):
            client = TestClient(main.app)
            self.assertEqual(client.get('/terms/offers?word=promo%C3%A7%C3%A3o', follow_redirects=False).status_code, 303)
            token = 'test-term-offers-session'
            main.sessions[token] = time.monotonic() + 60
            self.addCleanup(main.sessions.pop, token, None)
            cookies = {'panel_session': token}
            self.assertEqual(client.get('/terms/offers?word=x&page=0', cookies=cookies).status_code, 400)
            self.assertEqual(client.get('/terms/offers?word=', cookies=cookies).status_code, 400)
            response = client.get('/terms/offers?word=promo%C3%A7%C3%A3o', cookies=cookies)
            self.assertEqual(response.status_code, 200)

    def test_minimum_setting_requires_csrf_and_rejects_values_below_four(self):
        with patch.object(main, 'store', self.store):
            client = TestClient(main.app)
            token = 'test-minimum-setting-session'
            main.sessions[token] = time.monotonic() + 60
            self.addCleanup(main.sessions.pop, token, None)
            cookies = {'panel_session': token}
            self.assertEqual(client.get('/settings', cookies=cookies).status_code, 200)
            self.assertEqual(client.post('/settings/frequent-terms', cookies=cookies,
                data={'min_chars': '6'}).status_code, 403)
            response = client.post('/settings/frequent-terms', cookies=cookies,
                data={'csrf': main.csrf_token, 'min_chars': '6'}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(self.store.frequent_terms_min_chars(), 6)
            response = client.post('/settings/frequent-terms', cookies=cookies,
                data={'csrf': main.csrf_token, 'min_chars': '3'}, follow_redirects=False)
            self.assertIn('test_error=', response.headers['location'])
            self.assertEqual(self.store.frequent_terms_min_chars(), 6)


if __name__ == '__main__':
    unittest.main()
