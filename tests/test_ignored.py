import json
import os
from pathlib import Path
import sqlite3
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
        self.store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Notebook', 'notebook'))

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

    def test_irrelevant_filters_match_pairwise_reference_for_unicode_boundaries(self):
        terms = [
            ('Casa', 'casa'), ('Casamento', 'casamento'),
            ('foo', 'foo'), ('bar', 'bar'), ('foo_bar', 'foo_bar'),
            ('Café shop', 'cafe shop'), ('cafe shopper', 'cafe shopper'),
            ('ℌouse', 'House'), ('house', 'house'),
            ('A--B', 'a--b'), ('a-b', 'a-b'),
            # Direct SQL below covers a stored value rejected by the current add API.
            ('Combining mark', '\u0301'),
        ]
        self.store.execute('INSERT INTO ignored_keywords(word,normalized) VALUES(?,?)', terms[0])
        with self.store.connect() as db:
            db.executemany('INSERT INTO ignored_keywords(word,normalized) VALUES(?,?)', terms[1:])
        rows = self.store.rows('SELECT id,word,normalized FROM ignored_keywords ORDER BY normalized,id')
        expected = []
        for row in rows:
            covered_by = [other['word'] for other in rows if other['id'] != row['id'] and
                          ignored_matches(row['normalized'], other['normalized'])]
            if covered_by:
                expected.append({**row, 'covered_by': covered_by})

        self.assertEqual(self.store.irrelevant_ignored_words(), expected)

    def test_ignore_applies_to_existing_and_new_offers_but_not_alerts(self):
        self.add_offer(1, 'Notebook e PS5 Slim!')
        self.assertEqual(self.store.unread(), 1)
        self.assertTrue(self.store.add_ignored(' PS5 Slim '))
        self.assertFalse(self.store.add_ignored('ps5 slim'))
        self.add_offer(2, 'Notebook com ps5 slim, promoção')
        self.add_offer(3, 'Notebook para PS5pro item')
        self.assertEqual([o['message_id'] for o in self.store.feed()], [3, 2, 1])
        self.assertEqual({o['message_id'] for o in self.store.feed(alerts=True)}, {1, 2, 3})
        self.assertEqual(self.store.unread(), 3)
        self.assertEqual(len(self.store.rows('SELECT * FROM hits')), 3)
        self.store.execute('DELETE FROM ignored_keywords')
        self.assertEqual(len(self.store.feed()), 3)
        self.assertEqual(self.store.unread(), 3)

    def test_existing_ignored_word_updates_auto_delete_flag(self):
        self.add_offer(1, 'xps5pro oferta')
        self.assertTrue(self.store.add_ignored('xps5pro'))
        self.assertFalse(self.store.add_ignored('xps5pro'))
        self.assertTrue(self.store.add_ignored('XPS5PRO', auto_delete=True))
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords'), [{'auto_delete': 1}])
        self.assertEqual(self.store.rows('SELECT * FROM offers'), [])

        self.assertTrue(self.store.add_ignored('xps5pro', auto_delete=False))
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords'), [{'auto_delete': 0}])
        self.add_offer(2, 'xps5pro continua oculto')
        self.assertEqual([row['message_id'] for row in self.store.feed()], [])

    def test_ignored_timestamp_backfills_new_match_and_preserves_overlapping_rules(self):
        self.add_offer(1, 'Oferta PS5 Slim e Xbox Series')
        self.assertTrue(self.store.add_ignored('PS5 Slim'))
        first = self.store.rows('SELECT ignored_at,ignored_word FROM offers WHERE message_id=1')[0]
        self.assertEqual(first['ignored_word'], 'PS5 Slim')
        self.assertTrue(first['ignored_at'])
        self.store.add_ignored('Xbox Series')
        current = self.store.rows('SELECT ignored_at,ignored_word FROM offers WHERE message_id=1')[0]
        self.assertEqual(current['ignored_at'], first['ignored_at'])
        self.assertEqual(current['ignored_word'], 'PS5 Slim')
        ps5_id = self.store.rows("SELECT id FROM ignored_keywords WHERE normalized='ps5 slim'")[0]['id']
        self.store.remove_ignored(ps5_id)
        self.assertEqual(self.store.rows('SELECT ignored_word FROM offers WHERE message_id=1')[0]['ignored_word'], 'PS5 Slim')
        self.store.ingest(-100123, 1, 'Oferta Xbox Series', '2026-11-04', None)
        current = self.store.rows('SELECT ignored_at,ignored_word FROM offers WHERE message_id=1')[0]
        self.assertEqual(current['ignored_at'], first['ignored_at'])
        self.assertEqual(current['ignored_word'], 'Xbox Series')
        xbox_id = self.store.rows("SELECT id FROM ignored_keywords WHERE normalized='xbox series'")[0]['id']
        self.store.remove_ignored(xbox_id)
        current = self.store.rows('SELECT ignored_at,ignored_word FROM offers WHERE message_id=1')[0]
        self.assertIsNone(current['ignored_at'])
        self.assertIsNone(current['ignored_word'])
        self.store.ingest(-100123, 1, 'Oferta visível', '2026-11-04', None)
        self.assertIsNone(self.store.rows('SELECT ignored_at FROM offers WHERE message_id=1')[0]['ignored_at'])

    def test_new_ignored_cause_backfills_offer_ending_in_punctuation(self):
        self.add_offer(1, 'Oferta PS5 Slim!')
        self.store.add_ignored('PS5 Slim')
        row = self.store.rows('SELECT ignored_at,ignored_word FROM offers WHERE message_id=1')[0]
        self.assertTrue(row['ignored_at'])
        self.assertEqual(row['ignored_word'], 'PS5 Slim')

    def test_new_album_cause_is_shared_by_all_parts(self):
        self.store.add_ignored('PS5 Slim')
        self.add_offer(1, 'Parte sem correspondência', grouped=55)
        self.add_offer(2, 'Parte PS5 Slim', grouped=55)
        rows = self.store.rows('SELECT ignored_word FROM offers WHERE grouped_id=?', ('55',))
        self.assertEqual(rows, [{'ignored_word': 'PS5 Slim'}, {'ignored_word': 'PS5 Slim'}])

    def test_new_offer_matching_multiple_words_uses_oldest_registered_cause(self):
        self.store.add_ignored('PS5 Slim')
        self.store.add_ignored('Café')
        self.add_offer(1, 'Oferta Café e PS5 Slim')
        self.assertEqual(self.store.rows('SELECT ignored_word FROM offers WHERE message_id=1'),
                         [{'ignored_word': 'PS5 Slim'}])

    def test_ignored_timestamp_migration_leaves_previously_hidden_rows_null(self):
        self.add_offer(1, 'PS5 Slim antigo')
        self.store.add_ignored('PS5 Slim')
        self.store.execute('ALTER TABLE offers DROP COLUMN ignored_at')
        reopened = Store(self.store.path)
        self.assertIsNone(reopened.rows('SELECT ignored_at FROM offers WHERE message_id=1')[0]['ignored_at'])
        reopened.ingest(-100123, 1, 'PS5 Slim antigo editado', '2026-11-04', None)
        self.assertIsNone(reopened.rows('SELECT ignored_at FROM offers WHERE message_id=1')[0]['ignored_at'])
        backup = sqlite3.connect(str(self.store.path) + '.before-ignored-at.db')
        try:
            self.assertNotIn('ignored_at', {row[1] for row in backup.execute('PRAGMA table_info(offers)')})
            self.assertEqual(backup.execute('SELECT body FROM offers WHERE message_id=1').fetchone()[0], 'PS5 Slim antigo')
        finally:
            backup.close()

    def test_ignore_album_if_any_part_matches_but_keep_alert_and_other_chat(self):
        self.store.add_ignored('PS5 Slim')
        self.add_offer(1, 'Notebook', grouped=55)
        self.add_offer(2, 'Acompanha PS5 Slim.', grouped=55)
        self.store.execute('INSERT INTO chats VALUES(-100456,?)', ('Outro',))
        self.store.ingest(-100456, 1, 'Notebook normal', '2026-11-04', None,
                          source_json=json.dumps({'grouped_id': 55}))
        self.assertEqual({o['chat_id'] for o in self.store.feed()}, {-100456, -100123})
        cards = self.store.feed(alerts=True)
        album = next(o for o in cards if o['chat_id'] == -100123)
        self.assertEqual([p['message_id'] for p in album['parts']], [1, 2])
        self.assertEqual(self.store.unread(), 2)
        self.store.mark_seen(album['id'])
        self.assertEqual(self.store.unread(), 1)

    def test_filter_before_limit_keeps_older_visible_items(self):
        self.store.add_ignored('PS5 Slim')
        self.add_offer(1, 'Oferta visível')
        for i in range(2, 112):
            self.add_offer(i, 'PS5 Slim em promoção')
        self.assertEqual([o['message_id'] for o in self.store.feed()], [1])
        self.assertEqual(len(self.store.rows('SELECT * FROM offers')), 111)

    def test_alerts_override_ignored_filter_and_auto_delete_for_messages_and_albums(self):
        self.store.add_ignored('PS5 Slim', auto_delete=True)
        single = self.store.ingest(-100123, 1, 'Notebook com PS5 Slim', '2026-11-04', None)
        self.store.ingest(-100123, 2, 'Notebook álbum', '2026-11-04', None,
                          source_json='{"grouped_id":55}')
        self.store.ingest(-100123, 3, 'PS5 Slim acompanha', '2026-11-04', None,
                          source_json='{"grouped_id":55}')
        self.assertEqual(len(self.store.rows('SELECT * FROM offers')), 3)
        self.assertEqual(len(self.store.rows('SELECT * FROM hits')), 2)
        self.assertIn(single, [card['id'] for card in self.store.feed()])
        self.assertEqual(len(self.store.feed()), 2)
        self.assertEqual(self.store.feed(deleted=True), [])
        self.assertEqual(self.store.term_offers('notebook')[1], 2)

    def test_removing_last_alert_rule_applies_existing_auto_delete_to_album_atomically(self):
        self.store.add_ignored('PS5 Slim', auto_delete=True)
        self.store.ingest(-100123, 1, 'Notebook com PS5 Slim', '2026-11-04', None)
        self.store.ingest(-100123, 2, 'Notebook álbum', '2026-11-04', None,
                          source_json='{"grouped_id":55}')
        self.store.ingest(-100123, 3, 'PS5 Slim acompanha', '2026-11-04', None,
                          source_json='{"grouped_id":55}')
        self.assertTrue(self.store.remove_rule(1))
        self.assertEqual(self.store.rows('SELECT * FROM offers'), [])
        self.assertEqual(self.store.rows('SELECT * FROM hits'), [])

    def test_recently_deleted_includes_manual_and_ignored_until_physical_removal(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        self.store.add_ignored('PS5 Slim')
        self.store.ingest(-100123, 1, 'PS5 Slim ignorado', (now - timedelta(minutes=5)).isoformat(), None)
        manual_id = self.store.ingest(-100123, 2, 'Oferta excluída manualmente', now.isoformat(), None)
        self.store.delete_offer(manual_id)
        self.store.execute('UPDATE offers SET deleted_at=? WHERE id=?', ((now - timedelta(minutes=10)).isoformat(), manual_id))
        for message_id in range(3, 104):
            self.store.ingest(-100123, message_id, 'PS5 Slim ignorado',
                              (now - timedelta(minutes=5)).isoformat(), None)
        self.store.execute('UPDATE offers SET ignored_at=NULL WHERE message_id=1')
        offers = self.store.feed(deleted=True)
        self.assertEqual(offers[0]['deletion_reason'], 'ignored')
        self.assertEqual(offers[-2]['deletion_reason'], 'manual')
        self.assertIsNone(offers[-1]['deletion_at'])
        self.assertTrue(all(offer['deletion_reason'] == 'ignored' for offer in offers[:-2]))
        self.assertEqual(len(offers), 103)
        self.assertGreater(offers[0]['deletion_at'], offers[-2]['deletion_at'])
        self.assertIsNone(offers[0].get('physical_delete_at'))

    def test_deleted_cards_show_initial_cause_matching_one_album_part(self):
        self.store.add_ignored('PS5 Slim')
        self.store.add_ignored('Café')
        self.add_offer(1, 'Oferta PS5 Slim!', grouped=55)
        self.add_offer(2, 'CAFÉ em promoção', grouped=55)
        manual_id = self.store.ingest(-100123, 3, 'Exclusão manual', '2026-11-04', None)
        self.store.delete_offer(manual_id)

        cards = self.store.feed(deleted=True)
        ignored = next(card for card in cards if card['deletion_reason'] == 'ignored')
        manual = next(card for card in cards if card['deletion_reason'] == 'manual')
        self.assertEqual(ignored['ignored_words'], ['PS5 Slim'])
        self.assertNotIn('ignored_words', manual)

    def test_ignored_word_migration_infers_oldest_match_and_preserves_backup(self):
        self.add_offer(1, 'Oferta sem termo', grouped=55)
        self.add_offer(2, 'Parte PS5 Slim e Café', grouped=55)
        self.store.add_ignored('PS5 Slim')
        self.store.add_ignored('Café')
        self.store.execute('ALTER TABLE offers DROP COLUMN ignored_word')

        reopened = Store(self.store.path)

        rows = reopened.rows('SELECT ignored_word FROM offers WHERE grouped_id=? ORDER BY message_id', ('55',))
        self.assertEqual(rows, [{'ignored_word': 'PS5 Slim'}, {'ignored_word': 'PS5 Slim'}])
        backup = sqlite3.connect(str(self.store.path) + '.before-ignored-word.db')
        try:
            self.assertNotIn('ignored_word', {row[1] for row in backup.execute('PRAGMA table_info(offers)')})
        finally:
            backup.close()

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

    def test_home_hides_read_alerts_but_keeps_unread_alerts_and_non_alert_offers(self):
        self.add_offer(1, 'Notebook alerta não lido')
        self.add_offer(2, 'Notebook alerta lido')
        self.add_offer(3, 'Oferta sem alerta')
        self.store.mark_seen(2)
        for message_id in (4, 5, 6, 7):
            self.add_offer(message_id, f'Notebook álbum {message_id}', grouped=99 if message_id < 6 else 100)
        self.store.mark_seen(4)
        home = self.store.feed()
        self.assertEqual({card['id'] for card in home}, {1, 3, 6})
        self.assertEqual({card['id'] for card in self.store.feed(alerts=True, read=False)}, {1, 6})

    def test_new_offers_respect_filters_and_count_albums_once(self):
        self.add_offer(1, 'Notebook antigo', grouped=11)
        marker = self.store.rows('SELECT max(id) AS id FROM offers')[0]['id']
        self.store.add_ignored('PS5 Slim')
        self.add_offer(2, 'Notebook parte antiga', grouped=11)
        self.add_offer(3, 'Notebook novo', grouped=12)
        self.add_offer(4, 'Outra parte', grouped=12)
        self.add_offer(5, 'Notebook PS5 Slim')
        self.add_offer(6, 'Oferta diferente')
        self.assertEqual(self.store.new_offers(marker), 3)
        self.assertEqual(self.store.new_offers(marker, 'Notebook'), 2)
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

    def test_auto_delete_migration_defaults_existing_words_to_false_without_backup_file(self):
        self.store.add_ignored('Palavra antiga')
        self.store.execute('ALTER TABLE ignored_keywords DROP COLUMN auto_delete')

        reopened = Store(self.store.path)

        self.assertEqual(reopened.rows('SELECT word,auto_delete FROM ignored_keywords'),
                         [{'word': 'Palavra antiga', 'auto_delete': 0}])
        self.assertFalse(Path(str(self.store.path) + '.before-ignored-auto-delete.db').exists())

    def test_auto_delete_physically_removes_matching_albums(self):
        self.store.remove_rule(1)
        self.add_offer(1, 'Notebook e PS5 Slim', grouped=55)
        self.add_offer(2, 'Parte sem termo', grouped=55)
        self.add_offer(3, 'Notebook sem filtro')
        self.assertEqual(len(self.store.rows('SELECT * FROM hits')), 0)

        self.assertTrue(self.store.add_ignored('PS5 Slim'))
        word_id = self.store.rows("SELECT id FROM ignored_keywords WHERE normalized='ps5 slim'")[0]['id']
        self.assertEqual(self.store.set_ignored_auto_delete(word_id, True), 2)

        self.assertEqual(self.store.rows('SELECT message_id FROM offers'), [{'message_id': 3}])
        self.assertEqual(self.store.rows('SELECT * FROM hits'), [])
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords WHERE id=?', (word_id,)),
                         [{'auto_delete': 1}])

    def test_auto_delete_flag_on_creation_deletes_existing_matches_and_false_remains_default(self):
        self.store.remove_rule(1)
        self.add_offer(1, 'Notebook com Xbox Series')
        self.assertTrue(self.store.add_ignored('Xbox Series', auto_delete=True))

        self.assertEqual(self.store.rows('SELECT * FROM offers'), [])
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords'), [{'auto_delete': 1}])

        self.assertTrue(self.store.add_ignored('Palavra comum'))
        self.assertEqual(self.store.rows("SELECT auto_delete FROM ignored_keywords WHERE normalized='palavra comum'"),
                         [{'auto_delete': 0}])


class IgnoredWordsWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
        self.store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Notebook', 'notebook'))
        self.store.ingest(-100123, 1, 'Notebook e PS5 Slim!', '2026-11-04', None)
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

    def test_deleted_page_displays_ignored_word_but_not_for_manual_deletion(self):
        self.store.add_ignored('PS5 Slim')
        self.store.ingest(-100123, 3, 'PS5 Slim sem alerta', '2026-11-04', None)
        manual_id = self.store.ingest(-100123, 2, 'Excluída manualmente', '2026-11-04', None)
        self.store.delete_offer(manual_id)

        page = self.client.get('/deleted', cookies=self.auth)

        self.assertIn('Excluída por palavra ignorada · PS5 Slim', page.text)
        self.assertIn('Excluída manualmente ·', page.text)
        self.assertNotIn('Excluída manualmente · PS5 Slim', page.text)

    def test_collapsed_menu_auth_csrf_add_delete_and_alert_view(self):
        page = self.client.get('/', cookies=self.auth)
        self.assertNotIn('id="ignored-settings"', page.text)
        self.assertIn('id="ignored-settings"', self.client.get('/ignored', cookies=self.auth).text)
        self.assertIn('Palavras ignoradas', page.text)
        self.assertEqual(self.client.post('/ignored', data={'word': 'PS5 Slim'}, follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/ignored', cookies=self.auth, data={'word': 'PS5 Slim'}).status_code, 403)
        data = {'word': 'PS5 Slim', 'csrf': main.csrf_token, 'q': 'Notebook', 'alerts': 'false'}
        response = self.client.post('/ignored', cookies=self.auth, data=data, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['location'].startswith('/ignored?'))
        self.assertIn('Notebook e PS5 Slim!', self.client.get('/', cookies=self.auth).text)
        alerts = self.client.get('/?alerts=true', cookies=self.auth)
        self.assertIn('Notebook e PS5 Slim!', alerts.text)
        self.assertIn('Novo alerta', alerts.text)
        duplicate = self.client.post('/ignored', cookies=self.auth, data={**data, 'word': 'ps5 slim'}, headers={'Accept': 'application/json'})
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('já está no filtro', duplicate.json()['message'])
        updated = self.client.post('/ignored', cookies=self.auth,
            data={**data, 'word': 'ps5 slim', 'auto_delete': 'true'}, headers={'Accept': 'application/json'})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords'), [{'auto_delete': 1}])
        updated = self.client.post('/ignored', cookies=self.auth, data=data, headers={'Accept': 'application/json'})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords'), [{'auto_delete': 0}])
        response = self.client.post('/ignored/1/delete', cookies=self.auth,
                                    data={'csrf': main.csrf_token, 'alerts': 'true', 'q': 'Notebook'},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['location'].startswith('/ignored?'))
        self.assertIn('Notebook e PS5 Slim!', self.client.get('/', cookies=self.auth).text)
        self.assertEqual(self.store.unread(), 1)

    def test_create_with_auto_delete_and_toggle_existing_rule(self):
        page = self.client.get('/ignored', cookies=self.auth)
        self.assertIn('name="auto_delete" value="true"', page.text)
        self.assertIn('Excluir permanentemente ofertas e álbuns correspondentes', page.text)
        response = self.client.post('/ignored', cookies=self.auth,
                                    data={'csrf': main.csrf_token, 'word': 'PS5 Slim', 'auto_delete': 'true'},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.store.rows('SELECT message_id FROM offers'), [{'message_id': 1}])
        self.assertEqual(len(self.store.rows('SELECT * FROM hits')), 1)
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords'), [{'auto_delete': 1}])

        self.store.ingest(-100123, 2, 'Xbox Series', '2026-11-04', None)
        self.store.add_ignored('Xbox Series')
        word_id = self.store.rows("SELECT id FROM ignored_keywords WHERE normalized='xbox series'")[0]['id']
        response = self.client.post(f'/ignored/{word_id}/auto-delete', cookies=self.auth,
                                    content=f'csrf={main.csrf_token}&enabled=false&enabled=true',
                                    headers={'Content-Type': 'application/x-www-form-urlencoded',
                                             'Accept': 'application/json'})
        self.assertEqual(response.json()['deleted'], 1)
        self.assertEqual(self.store.rows('SELECT message_id FROM offers'), [{'message_id': 1}])
        response = self.client.post(f'/ignored/{word_id}/auto-delete', cookies=self.auth,
                                    data={'csrf': main.csrf_token, 'enabled': 'false'},
                                    headers={'Accept': 'application/json'})
        self.assertTrue(response.json()['ok'])
        self.assertEqual(self.store.rows('SELECT auto_delete FROM ignored_keywords WHERE id=?', (word_id,)),
                         [{'auto_delete': 0}])
        self.store.ingest(-100123, 3, 'Xbox Series', '2026-11-04', None)
        self.assertEqual(self.store.rows('SELECT message_id FROM offers'), [{'message_id': 1}, {'message_id': 3}])

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
