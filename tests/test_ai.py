import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ai import AIError, extract, list_models
from app.store import Store


class AIClientTests(unittest.TestCase):
    def test_catalog_is_sorted_and_uses_model_ids(self):
        with patch('app.ai.request', return_value={'data': [
            {'id': 'z-model', 'name': 'Zulu'}, {'id': 'a-model', 'name': 'Alpha'}, {'id': 'hidden'},
        ]}):
            self.assertEqual(list_models('openai', 'key'), [
                {'id': 'a-model', 'name': 'Alpha'}, {'id': 'hidden', 'name': 'hidden'},
                {'id': 'z-model', 'name': 'Zulu'},
            ])

    def test_extraction_accepts_partial_json_and_rejects_empty_or_invalid_output(self):
        payload = {'choices': [{'message': {'content': json.dumps({
            'product_name': 'Fone', 'description': 'texto que não deve ser extraído', 'original_price': 'R$ 200',
            'discounted_price': None, 'coupon_code': None,
        })}}]}
        with patch('app.ai.request', return_value=payload) as request:
            self.assertEqual(extract('openrouter', 'key', 'model', 'Fone por R$ 200'), {
                'product_name': 'Fone', 'original_price': 'R$ 200',
                'discounted_price': None, 'coupon_code': None,
            })
        self.assertNotIn('description', request.call_args.args[3]['messages'][0]['content'])
        for content in ('not JSON', '{"product_name": null}', '{"product_name": 42}'):
            with self.subTest(content=content), patch('app.ai.request', return_value={
                    'choices': [{'message': {'content': content}}]}):
                with self.assertRaises(AIError):
                    extract('openai', 'key', 'model', 'Oferta')


class AIStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(?,?)', (-1001, 'Grupo'))

    def save_models(self):
        self.store.save_ai_settings('secret-openai', 'secret-router', [
            {'provider': 'openai', 'id': 'a'}, {'provider': 'openrouter', 'id': 'b'},
        ])

    def test_settings_keep_keys_private_and_survive_reopen(self):
        self.save_models()
        settings = self.store.ai_settings()
        self.assertEqual(settings['model_order'], [
            {'provider': 'openai', 'id': 'a'}, {'provider': 'openrouter', 'id': 'b'},
        ])
        self.assertTrue(settings['providers']['openai']['configured'])
        self.assertNotIn('secret-openai', repr(settings))
        self.assertEqual(Store(self.store.path).ai_api_key('openai'), 'secret-openai')

    def test_old_database_gets_ai_tables_without_changing_offers(self):
        path = Path(self.tmp.name) / 'legacy.db'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE offers (
            id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            chat_title TEXT NOT NULL, body TEXT NOT NULL, url TEXT,
            date TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0,
            UNIQUE(chat_id,message_id));
            INSERT INTO offers VALUES(1,-1001,42,'Grupo','Oferta preservada',NULL,'2026-11-01',0);''')
        db.close()
        migrated = Store(path)
        self.assertEqual(migrated.rows('SELECT body FROM offers'), [{'body': 'Oferta preservada'}])
        tables = {row['name'] for row in migrated.rows("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'offer_extractions', 'ai_jobs', 'ai_job_items', 'ai_job_attempts'} <= tables)

    def test_job_selection_matches_home_feed_and_excludes_existing_extractions(self):
        self.store.add_ignored('blocked')
        for message_id in range(1, 106):
            body = 'blocked oferta' if message_id == 105 else f'oferta {message_id}'
            group = 500 if message_id in (1, 2) else None
            self.store.ingest(-1001, message_id, body, f'2026-11-{message_id % 28 + 1:02d}T00:00:00+00:00',
                              None, source_json=json.dumps({'grouped_id': group}) if group else None)
        cards = self.store.feed()
        self.assertLessEqual(len(cards), 100)
        self.save_models()
        first = cards[0]
        self.store.execute('''INSERT INTO offer_extractions
            (offer_id,product_name,original_price,discounted_price,coupon_code,job_id,updated_at)
            VALUES(?,?,?,?,?,?,?)''', (first['id'], 'Extraído', None, None, None, 0, 'now'))
        missing = [card['id'] for card in cards[1:]]
        job_id, count = self.store.enqueue_ai_job()
        queued = self.store.rows('SELECT offer_id FROM ai_job_items WHERE job_id=? ORDER BY position', (job_id,))
        self.assertEqual(count, len(missing))
        self.assertEqual([row['offer_id'] for row in queued], missing)
        replace_id, replace_count = self.store.enqueue_ai_job(replace_existing=True)
        self.assertEqual(replace_count, len(cards))
        self.assertEqual(len(self.store.rows('SELECT * FROM ai_job_items WHERE job_id=?', (replace_id,))), len(cards))

    def test_automatic_job_selects_one_visible_offer_and_deduplicates(self):
        self.store.save_ai_settings('secret-openai', '', [{'provider': 'openai', 'id': 'a'}])
        self.store.add_ignored('blocked')
        self.store.ingest(-1001, 1, 'Offer one', '2026-11-05', None)
        self.store.ingest(-1001, 2, 'blocked Offer two', '2026-11-05', None)
        self.store.ingest(-1001, 3, 'Oferta válida', '2026-11-05', None,
                          source_json='{"grouped_id":77}')
        self.store.ingest(-1001, 4, 'blocked parte do álbum', '2026-11-05', None,
                          source_json='{"grouped_id":77}')
        first, count = self.store.enqueue_ai_job(offer_ids=[1], automatic=True)
        self.assertIsNotNone(first)
        self.assertEqual(count, 1)
        self.assertEqual(self.store.enqueue_ai_job(offer_ids=[1], automatic=True), (None, 0))
        self.assertEqual(self.store.enqueue_ai_job(offer_ids=[2], automatic=True), (None, 0))
        self.assertEqual(self.store.enqueue_ai_job(offer_ids=[3], automatic=True), (None, 0))
        self.assertEqual(self.store.enqueue_ai_job(offer_ids=[1], automatic=True), (None, 0))

    def test_automatic_enqueue_without_provider_configuration_is_a_noop(self):
        self.store.ingest(-1001, 1, 'Offer', '2026-11-05', None)
        self.assertEqual(self.store.enqueue_ai_job(offer_ids=[1], automatic=True), (None, 0))

    def test_album_text_is_ordered_and_extraction_clears_after_edit(self):
        for message_id, body in ((10, 'Parte um'), (11, 'Parte dois')):
            self.store.ingest(-1001, message_id, body, '2026-11-01', None,
                              source_json=json.dumps({'grouped_id': 88}))
        self.save_models()
        job_id, _ = self.store.enqueue_ai_job()
        self.store.claim_ai_job()
        item = self.store.claim_ai_item(job_id)
        self.assertEqual(self.store.ai_item_content(item)['text'], 'Parte um\n\nParte dois')
        self.store.finish_ai_item(item['id'], 'succeeded', {'product_name': 'Produto'})
        self.assertEqual(self.store.feed()[0]['extraction']['product_name'], 'Produto')
        self.store.ingest(-1001, 12, 'Parte que chegou depois', '2026-11-01', None,
                          source_json=json.dumps({'grouped_id': 88}))
        self.assertIsNone(self.store.feed()[0]['extraction'])
        self.store.execute('''INSERT INTO offer_extractions
            (offer_id,product_name,original_price,discounted_price,coupon_code,job_id,updated_at)
            VALUES(?,?,?,?,?,?,?)''', (1, 'Produto', None, None, None, 0, 'now'))
        self.store.ingest(-1001, 11, 'Texto editado', '2026-11-01', None,
                          source_json=json.dumps({'grouped_id': 88}))
        self.assertIsNone(self.store.feed()[0]['extraction'])

    def test_legacy_description_is_ignored_without_destroying_existing_schema(self):
        self.store.ingest(-1001, 1, 'Oferta original', '2026-11-01', None)
        self.store.execute('ALTER TABLE offer_extractions ADD COLUMN description TEXT')
        self.store.execute('''INSERT INTO offer_extractions
            (offer_id,product_name,description,original_price,discounted_price,coupon_code,job_id,updated_at)
            VALUES(1,'Produto','Descrição antiga',NULL,NULL,NULL,0,'now')''')
        self.assertEqual(self.store.feed()[0]['extraction'], {
            'product_name': 'Produto', 'original_price': None,
            'discounted_price': None, 'coupon_code': None,
        })

    def test_result_is_discarded_if_offer_changes_during_provider_request(self):
        self.store.ingest(-1001, 10, 'Texto inicial', '2026-11-01', None)
        self.save_models()
        job_id, _ = self.store.enqueue_ai_job()
        self.store.claim_ai_job()
        item = self.store.claim_ai_item(job_id)
        content = self.store.ai_item_content(item)
        self.store.ingest(-1001, 10, 'Texto atualizado', '2026-11-01', None)
        saved = self.store.finish_ai_item(item['id'], 'succeeded',
                                         {'product_name': 'Extração antiga'}, content['content_hash'])
        self.assertEqual(saved, 'stale')
        self.assertIsNone(self.store.feed()[0]['extraction'])
        self.assertEqual(self.store.rows('SELECT status FROM ai_job_items WHERE id=?',
                                         (item['id'],))[0]['status'], 'skipped')

    def test_recovery_resets_inflight_items_and_jobs_fifo(self):
        self.store.ingest(-1001, 1, 'Oferta A', '2026-11-01', None)
        self.save_models()
        first, _ = self.store.enqueue_ai_job(True)
        second, _ = self.store.enqueue_ai_job(True)
        claimed = self.store.claim_ai_job()
        self.assertEqual(claimed['id'], first)
        item = self.store.claim_ai_item(first)
        self.store.recover_ai_jobs()
        self.assertEqual(self.store.claim_ai_job()['id'], first)
        self.assertEqual(self.store.claim_ai_item(first)['id'], item['id'])
        self.assertEqual(self.store.claim_ai_job(), None)
        self.store.finish_ai_item(item['id'], 'failed')
        self.store.finish_ai_job(first)
        self.assertEqual(self.store.claim_ai_job()['id'], second)

    def test_queued_job_cancellation_finishes_all_items_without_claiming(self):
        for number in range(2):
            self.store.ingest(-1001, number + 1, f'Oferta {number}', '2026-11-01', None)
        self.save_models()
        job_id, total = self.store.enqueue_ai_job(True)
        self.assertEqual(total, 2)
        self.assertEqual(self.store.cancel_ai_job(job_id), 'cancelled')
        jobs, active = self.store.ai_jobs()
        self.assertIsNone(active)
        self.assertEqual(jobs[0]['status'], 'cancelled')
        self.assertEqual(jobs[0]['cancelled'], 2)
        self.assertIsNone(self.store.claim_ai_job())

    def test_running_job_cancellation_discards_inflight_result_and_remaining_items(self):
        for number in range(2):
            self.store.ingest(-1001, number + 1, f'Oferta {number}', '2026-11-01', None)
        self.save_models()
        job_id, _ = self.store.enqueue_ai_job(True)
        self.store.claim_ai_job()
        item = self.store.claim_ai_item(job_id)
        content = self.store.ai_item_content(item)
        self.assertEqual(self.store.cancel_ai_job(job_id), 'cancelling')
        self.assertTrue(self.store.ai_job_cancel_requested(job_id))
        self.assertEqual(self.store.finish_ai_item(item['id'], 'succeeded',
                         {'product_name': 'Resultado ainda não salvo'}, content['content_hash']), 'cancelled')
        self.store.finish_ai_job(job_id)
        jobs, active = self.store.ai_jobs()
        self.assertIsNone(active)
        self.assertEqual(jobs[0]['status'], 'cancelled')
        self.assertEqual(jobs[0]['cancelled'], 2)
        self.assertIsNone(self.store.feed()[0]['extraction'])

    def test_live_provider_configuration_changes_for_next_attempt(self):
        self.save_models()
        self.assertEqual([model['id'] for model in self.store.configured_ai_models()], ['a', 'b'])
        self.store.save_ai_settings('rotated-openai', '', [{'provider': 'openai', 'id': 'replacement'}])
        models = self.store.configured_ai_models()
        self.assertEqual(models, [{'provider': 'openai', 'id': 'replacement', 'api_key': 'rotated-openai'}])


if __name__ == '__main__':
    unittest.main()
