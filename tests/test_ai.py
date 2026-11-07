import json
import asyncio
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
import httpx
from pathlib import Path
from unittest.mock import patch

from app.ai import AIError, extract, list_models
from app.store import Store


class AIClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelling_provider_request_closes_pending_http_operation(self):
        from app.ai import request
        started = asyncio.Event()

        async def handler(_request):
            started.set()
            await asyncio.Event().wait()

        client_class = httpx.AsyncClient
        with patch('app.ai.httpx.AsyncClient', side_effect=lambda **kwargs:
                   client_class(transport=httpx.MockTransport(handler), **kwargs)):
            pending = asyncio.create_task(request('openai', 'key', '/models'))
            await started.wait()
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending

    async def test_catalog_is_sorted_and_uses_model_ids(self):
        with patch('app.ai.request', return_value={'data': [
            {'id': 'z-model', 'name': 'Zulu'}, {'id': 'a-model', 'name': 'Alpha'}, {'id': 'hidden'},
        ]}):
            self.assertEqual(await list_models('openai', 'key'), [
                {'id': 'a-model', 'name': 'Alpha'}, {'id': 'hidden', 'name': 'hidden'},
                {'id': 'z-model', 'name': 'Zulu'},
            ])

    async def test_extraction_accepts_partial_json_and_rejects_empty_or_invalid_output(self):
        payload = {'choices': [{'message': {'content': json.dumps({
            'product_name': 'Fone', 'description': 'texto que não deve ser extraído', 'original_price': 'R$ 200',
            'discounted_price': None, 'coupon_code': None,
        })}}]}
        with patch('app.ai.request', return_value=payload) as request:
            self.assertEqual(await extract('openrouter', 'key', 'model', 'Fone por R$ 200'), {
                'product_name': 'Fone', 'original_price': 'R$ 200',
                'discounted_price': None, 'coupon_code': None,
            })
        self.assertNotIn('description', request.call_args.args[3]['messages'][0]['content'])
        for content in ('not JSON', '{"product_name": null}', '{"product_name": 42}'):
            with self.subTest(content=content), patch('app.ai.request', return_value={
                    'choices': [{'message': {'content': content}}]}):
                with self.assertRaises(AIError):
                    await extract('openai', 'key', 'model', 'Oferta')


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

    def test_parallelism_is_persisted_and_claimed_jobs_respect_the_limit(self):
        self.store.ingest(-1001, 1, 'Oferta', '2026-11-01', None)
        self.save_models()
        jobs = [self.store.enqueue_ai_job(True)[0] for _ in range(3)]
        self.assertEqual(self.store.ai_parallelism(), 1)
        self.assertEqual(self.store.claim_ai_job()['id'], jobs[0])
        self.assertIsNone(self.store.claim_ai_job())
        self.store.save_ai_parallelism(2)
        self.assertEqual(Store(self.store.path).ai_parallelism(), 2)
        self.assertEqual(self.store.claim_ai_job()['id'], jobs[1])
        self.assertIsNone(self.store.claim_ai_job())
        for invalid in (0, 9, 'invalid'):
            with self.assertRaises(ValueError):
                self.store.save_ai_parallelism(invalid)

    def test_simultaneous_claims_never_exceed_configured_parallelism(self):
        self.store.ingest(-1001, 1, 'Oferta', '2026-11-01', None)
        self.save_models()
        for _ in range(8):
            self.store.enqueue_ai_job(True)
        self.store.save_ai_parallelism(3)
        with ThreadPoolExecutor(max_workers=8) as workers:
            claims = list(workers.map(lambda _: self.store.claim_ai_job(), range(8)))
        claimed = [job['id'] for job in claims if job]
        self.assertEqual(len(claimed), 3)
        self.assertEqual(len(set(claimed)), 3)

    def test_failed_item_requeues_its_job_after_already_queued_jobs_once(self):
        self.store.ingest(-1001, 1, 'Oferta', '2026-11-01', None)
        self.save_models()
        first, _ = self.store.enqueue_ai_job(True)
        second, _ = self.store.enqueue_ai_job(True)
        self.store.save_ai_parallelism(2)
        self.assertEqual(self.store.claim_ai_job()['id'], first)
        item = self.store.claim_ai_item(first)
        self.assertTrue(self.store.requeue_failed_ai_item(first, item['id']))
        self.assertEqual(self.store.rows('SELECT status FROM ai_jobs WHERE id=?', (first,))[0]['status'], 'queued')
        self.assertEqual(self.store.claim_ai_job()['id'], second)
        self.assertEqual(self.store.cancel_ai_job(second), 'cancelling')
        self.store.finish_ai_job(second)
        self.assertEqual(self.store.claim_ai_job()['id'], first)
        retried = self.store.claim_ai_item(first)
        self.assertEqual(retried['id'], item['id'])
        self.assertFalse(self.store.requeue_failed_ai_item(first, retried['id']))

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

    def test_existing_ai_jobs_table_adds_cleanup_flag_after_backup(self):
        path = Path(self.tmp.name) / 'legacy-ai-jobs.db'
        with sqlite3.connect(path) as db:
            db.execute('''CREATE TABLE ai_jobs (
                id INTEGER PRIMARY KEY, status TEXT NOT NULL, replace_existing INTEGER NOT NULL,
                models_json TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT)''')
            db.execute("INSERT INTO ai_jobs VALUES(1,'completed',0,'[]','now',NULL,'now')")

        migrated = Store(path)
        columns = {row['name'] for row in migrated.rows('PRAGMA table_info(ai_jobs)')}
        self.assertIn('clear_requested', columns)
        self.assertIn('queue_at', columns)
        self.assertEqual(migrated.rows('SELECT queue_at FROM ai_jobs WHERE id=1'), [{'queue_at': 'now'}])
        self.assertEqual(migrated.rows('SELECT id,clear_requested FROM ai_jobs'),
                         [{'id': 1, 'clear_requested': 0}])
        backup = sqlite3.connect(str(path) + '.before-ai-job-cleanup.db')
        try:
            old_columns = {row[1] for row in backup.execute('PRAGMA table_info(ai_jobs)')}
            self.assertNotIn('clear_requested', old_columns)
            self.assertEqual(backup.execute('SELECT id,status FROM ai_jobs').fetchone(), (1, 'completed'))
        finally:
            backup.close()
        retry_backup = sqlite3.connect(str(path) + '.before-ai-job-retry.db')
        try:
            old_columns = {row[1] for row in retry_backup.execute('PRAGMA table_info(ai_jobs)')}
            self.assertNotIn('queue_at', old_columns)
        finally:
            retry_backup.close()

    def test_clear_all_jobs_are_removed_after_restart_recovery(self):
        self.store.ingest(-1001, 1, 'Oferta ativa', '2026-11-01', None)
        self.save_models()
        job_id, _ = self.store.enqueue_ai_job(True)
        self.store.claim_ai_job()
        item = self.store.claim_ai_item(job_id)
        self.store.record_ai_attempt(job_id, item['id'], 'openai', 'a', 'cancelled', 'Cancelado', 1)
        self.assertEqual(self.store.cancel_and_clear_ai_jobs(), [job_id])

        recovered = Store(self.store.path)
        recovered.recover_ai_jobs()
        self.assertEqual(recovered.rows('SELECT id FROM ai_jobs'), [])
        self.assertEqual(recovered.rows('SELECT id FROM ai_job_items'), [])
        self.assertEqual(recovered.rows('SELECT id FROM ai_job_attempts'), [])

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
