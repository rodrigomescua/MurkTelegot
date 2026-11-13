import asyncio
import json
import os
import hashlib
import hmac
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.store import Store, matches
from app.ai import AIError

_runtime = tempfile.TemporaryDirectory()
os.environ.update(DATA_DIR=_runtime.name, APP_PASSWORD='test-password-with-32-characters')
from fastapi.testclient import TestClient
from app import main


class MatchingTests(unittest.TestCase):
    def test_accents_case_phrases_and_word_boundaries(self):
        self.assertTrue(matches('CAFÉ em promoção', 'notebook, café'))
        self.assertTrue(matches('Oferta: RTX 4060!', 'rtx 4060'))
        self.assertFalse(matches('cafeteira e cafés', 'café'))
        self.assertFalse(matches('qualquer oferta', ' , '))
        self.assertTrue(matches('C++ em oferta', 'c++'))

    def test_signed_media_access_filter_hides_bearer_url(self):
        import logging
        access_filter = main.SignedMediaAccessFilter()
        signed = logging.LogRecord('uvicorn.access', logging.INFO, '', 0,
                                   'GET /public-media/1/123/secret HTTP/1.1', (), None)
        ordinary = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, 'GET /health HTTP/1.1', (), None)
        self.assertFalse(access_filter.filter(signed))
        self.assertTrue(access_filter.filter(ordinary))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(?,?)', (-100123, 'Ofertas'))
        self.store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Café', 'café'))

    def ingest(self, chat=-100123, body='Café barato'):
        self.store.ingest(chat, 1, body, '2026-11-04T12:00:00+00:00', None)

    def test_media_signing_key_persists_in_settings(self):
        key = self.store.media_signing_key()
        self.assertEqual(Store(self.store.path).media_signing_key(), key)

    def test_only_selected_chats_and_nonempty_messages(self):
        self.ingest(chat=42)
        self.ingest(body='')
        self.assertEqual(self.store.rows('SELECT * FROM offers'), [])

    def test_expiry_uses_offer_date_preserves_alert_albums_and_purges_deleted(self):
        from datetime import datetime, timezone, timedelta
        self.store.add_ignored('blocked')
        now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        add = lambda message_id, body, age, group=None: self.store.ingest(
            -100123, message_id, body, (now - age).isoformat(), None,
            source_json=f'{{"grouped_id": {group}}}' if group is not None else None)
        add(10, 'blocked vencida', timedelta(hours=4, seconds=1))
        add(11, 'blocked recente', timedelta(hours=3, minutes=59))
        add(12, 'Oferta antiga', timedelta(hours=24, seconds=1))
        add(13, 'Oferta recente', timedelta(hours=23, minutes=59))
        add(14, 'Café com alerta', timedelta(hours=25))
        add(15, 'blocked álbum expirado', timedelta(hours=5), 44)
        add(16, 'Outra parte', timedelta(hours=5), 44)
        add(17, 'blocked álbum alertado', timedelta(hours=25), 45)
        add(18, 'Café', timedelta(hours=25), 45)
        pending_delete = add(19, 'Café em exclusão pendente', timedelta(hours=25))
        self.store.delete_offer(pending_delete)
        expired_delete = add(20, 'Café exclusão expirada', timedelta(hours=25))
        self.store.delete_offer(expired_delete)
        self.store.execute('UPDATE offers SET deleted_at=? WHERE id=?',
                           ((now - timedelta(minutes=30)).isoformat(), pending_delete))
        self.store.execute('UPDATE offers SET deleted_at=? WHERE id=?',
                           ((now - timedelta(hours=1, seconds=1)).isoformat(), expired_delete))
        self.store.expire_offers(now)
        self.assertEqual({r['message_id'] for r in self.store.rows('SELECT message_id FROM offers')},
                         {11, 13, 14, 17, 18, 19})
        self.assertFalse(self.store.restore_deleted_offer(expired_delete))

    def test_duplicate_edit_and_matching_are_atomic(self):
        self.ingest()
        self.ingest()
        self.assertEqual(len(self.store.rows('SELECT * FROM offers')), 1)
        self.assertEqual(len(self.store.rows('SELECT * FROM hits')), 1)
        self.ingest(body='Outro produto')
        self.assertEqual(self.store.rows('SELECT * FROM hits'), [])
        reopened = Store(self.store.path)
        self.assertEqual(reopened.rows('SELECT body FROM offers')[0]['body'], 'Outro produto')

    def test_late_album_parts_inherit_logical_deletion(self):
        self.store.ingest(-100123, 10, 'Oferta sem alerta', '2026-11-04T12:00:00+00:00', None,
                          source_json='{"grouped_id":77}')
        self.store.delete_offer(1)
        offer_id, alert = self.store.ingest(-100123, 11, 'Café parte atrasada', '2026-11-04T12:00:01+00:00', None,
                                            source_json='{"grouped_id":77}', report_alert=True)
        rows = self.store.rows('SELECT deleted_at FROM offers WHERE grouped_id=?', ('77',))
        self.assertIsNotNone(offer_id)
        self.assertIsNone(alert)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['deleted_at'] for row in rows))
        self.assertEqual(self.store.feed(alerts=True), [])

    def test_add_rule_backfills_ignored_offers_and_album_parts(self):
        self.store.add_ignored('blocked')
        self.store.ingest(-100123, 10, 'Notebook oferta', '2026-11-04T12:00:00+00:00', None)
        self.store.ingest(-100123, 11, 'blocked Notebook', '2026-11-04T12:00:01+00:00', None)
        self.store.ingest(-100123, 12, 'Notebook capa', '2026-11-04T12:00:02+00:00', None,
                          source_json='{"grouped_id": 50}')
        self.store.ingest(-100123, 13, 'Outra parte', '2026-11-04T12:00:03+00:00', None,
                          source_json='{"grouped_id": 50}')
        self.store.ingest(-100123, 14, 'Sem correspondência', '2026-11-04T12:00:04+00:00', None)
        self.store.execute('UPDATE offers SET seen=1 WHERE message_id IN (10,11)')
        count = self.store.add_rule('Notebook')
        self.assertEqual(count, 3)
        self.assertEqual({row['offer_id'] for row in self.store.rows(
            'SELECT h.offer_id FROM hits h JOIN rules r ON r.id=h.rule_id WHERE r.name=?', ('Notebook',))},
            {row['id'] for row in self.store.rows('SELECT id FROM offers WHERE message_id IN (10,11,12)')})
        self.assertEqual(self.store.rows('SELECT seen FROM offers WHERE message_id IN (10,11)'),
                         [{'seen': 0}, {'seen': 0}])
        self.assertEqual(len(self.store.feed(alerts=True)), 3)

    def test_add_rule_removes_equal_or_containing_ignored_filters_atomically(self):
        self.store.add_ignored('notebook')
        self.store.add_ignored('supernotebook')
        self.store.add_ignored('café notebook pro')
        self.store.add_ignored('xbox series')
        self.store.ingest(-100123, 10, 'supernotebook oferta', '2026-11-04T12:00:00+00:00', None)
        self.store.ingest(-100123, 11, 'café notebook pro', '2026-11-04T12:00:01+00:00', None)
        self.store.ingest(-100123, 12, 'xbox series', '2026-11-04T12:00:02+00:00', None)

        self.store.add_rule('NOTÉBOOK')

        self.assertEqual(self.store.rows('SELECT normalized FROM ignored_keywords'),
                         [{'normalized': 'xbox series'}])
        self.assertEqual({row['message_id'] for row in self.store.feed()}, {10, 11})
        self.assertEqual(self.store.rows('''SELECT ignored_at,ignored_word FROM offers
                                            WHERE message_id IN (10,11) ORDER BY message_id'''),
                         [{'ignored_at': None, 'ignored_word': None},
                          {'ignored_at': None, 'ignored_word': None}])

    def test_add_rule_notifies_each_matching_album_once(self):
        self.store.ingest(-100123, 10, 'Café já alertado', '2026-11-04T12:00:00+00:00', None,
                          source_json='{"grouped_id": 50}')
        self.store.ingest(-100123, 11, 'Notebook no mesmo álbum', '2026-11-04T12:00:01+00:00', None,
                          source_json='{"grouped_id": 50}')
        self.store.ingest(-100123, 12, 'Notebook novo', '2026-11-04T12:00:02+00:00', None)
        matched, alerts = self.store.add_rule('Notebook', return_alerts=True)
        self.assertEqual(matched, 2)
        self.assertEqual([alert['body'] for alert in alerts], ['Notebook no mesmo álbum', 'Notebook novo'])

    def test_legacy_rules_split_by_term_and_preserve_matching_hits(self):
        self.store.execute('UPDATE rules SET name=?,keywords=? WHERE id=1',
                           ('Ofertas favoritas', 'café, notebook'))
        self.ingest(body='Café puro')
        self.store.ingest(-100123, 2, 'Notebook novo', '2026-11-04T12:00:01+00:00', None)
        self.store.ingest(-100123, 3, 'Café com notebook', '2026-11-04T12:00:02+00:00', None)
        self.store.execute("DELETE FROM settings WHERE key='rules_one_term_v1'")

        reopened = Store(self.store.path)
        self.assertEqual(reopened.rows('SELECT name,keywords FROM rules ORDER BY id'), [
            {'name': 'café', 'keywords': 'café'}, {'name': 'notebook', 'keywords': 'notebook'},
        ])
        self.assertEqual({(row['body'], row['keywords']) for row in reopened.rows(
            'SELECT o.body,r.keywords FROM hits h JOIN offers o ON o.id=h.offer_id JOIN rules r ON r.id=h.rule_id')}, {
            ('Café puro', 'café'), ('Notebook novo', 'notebook'),
            ('Café com notebook', 'café'), ('Café com notebook', 'notebook'),
        })
        self.assertTrue(Path(str(self.store.path) + '.before-rule-terms.db').exists())
        Store(self.store.path)
        self.assertEqual(len(reopened.rows('SELECT * FROM rules')), 2)


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(main, 'store', Store(Path(self.tmp.name) / 'db.sqlite'))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(main.app)
        self.auth = {'panel_session': 'test-session'}
        main.sessions['test-session'] = __import__('time').monotonic() + 60

    def post(self, url, data=None):
        return self.client.post(url, cookies=self.auth, data={'csrf': main.csrf_token, **(data or {})})

    def test_auth_csrf_and_dashboard(self):
        self.assertEqual(self.client.get('/', follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get('/', cookies={'panel_session': 'wrong'}, follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get('/health').status_code, 200)
        response = self.client.get('/', cookies=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Seu radar está pronto', response.text)
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(self.client.post('/rules', cookies=self.auth, data={'keyword': 'x'}).status_code, 403)

    def test_unread_counter_is_linked_and_present_on_all_pages(self):
        main.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Grupo',))
        main.store.add_rule('Notebook')
        main.store.ingest(-100123, 1, 'Notebook oferta', '2026-11-07T12:00:00+00:00', None)
        for path in ('/', '/alerts', '/telegram', '/rules-page', '/terms', '/groups', '/coupons',
                     '/ignored', '/ai-jobs', '/settings'):
            with self.subTest(path=path):
                response = self.client.get(path, cookies=self.auth)
                self.assertEqual(response.status_code, 200)
                self.assertIn('id="alert-counter" class="unread-count" href="/alerts"', response.text)
                self.assertIn('<strong>1</strong>', response.text)
        count = self.client.get('/alerts/unread-count', cookies=self.auth)
        self.assertEqual(count.json(), {'unread': 1})
        self.assertEqual(TestClient(main.app).get('/alerts/unread-count', follow_redirects=False).status_code, 303)

    def test_coupons_page_and_manual_inactivation_require_auth_and_csrf(self):
        main.store.execute('''INSERT INTO coupons
            (store,store_key,code,code_key,conditions,status,links_json,inactive_at,updated_at)
            VALUES(?,?,?,?,?,'active',?,NULL,'now')''',
            ('Loja X', 'loja x', 'SAVE', 'save', 'Mínimo R$ 100', json.dumps([
                {'type': 'redeem', 'url': 'https://loja.example/resgatar'},
                {'type': 'products', 'url': 'javascript:alert(1)'},
            ])))
        page = self.client.get('/coupons', cookies=self.auth)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Loja X', page.text)
        self.assertIn('Mínimo R$ 100', page.text)
        self.assertIn('Resgatar cupom', page.text)
        self.assertIn('https://loja.example/resgatar', page.text)
        self.assertNotIn('javascript:', page.text)
        self.assertEqual(self.client.get('/coupons', follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/coupons/1/inactive', cookies=self.auth,
                                          data={'csrf': 'invalid'}).status_code, 403)
        response = self.client.post('/coupons/1/inactive', cookies=self.auth,
                                    data={'csrf': main.csrf_token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(main.store.rows('SELECT status FROM coupons'), [{'status': 'inactive'}])
        main.store.execute('''INSERT INTO coupons
            (store,store_key,code,code_key,conditions,status,links_json,inactive_at,updated_at)
            VALUES('Loja Y','loja y','SECOND','second',NULL,'active','[]',NULL,'now')''')
        response = self.client.post('/coupons/2/inactive', cookies=self.auth,
                                    data={'csrf': main.csrf_token},
                                    headers={'Accept': 'application/json'}, follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'message': 'Cupom marcado como inativo.'})
        missing = self.client.post('/coupons/999/inactive', cookies=self.auth,
                                   data={'csrf': main.csrf_token},
                                   headers={'Accept': 'application/json'}, follow_redirects=False)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {'ok': False, 'message': 'Cupom não encontrado.'})

    def test_compact_page_titles_and_navigation_order(self):
        home = self.client.get('/', cookies=self.auth).text
        alerts = self.client.get('/alerts', cookies=self.auth).text
        terms = self.client.get('/terms', cookies=self.auth).text
        self.assertIn('<h1 class="page-title">Ofertas</h1>', home)
        self.assertNotIn('RADAR PESSOAL', home)
        self.assertNotIn('Ofertas que importam.', home)
        self.assertIn('<h1 class="page-title">Alertas</h1>', alerts)
        self.assertNotIn('Acompanhe suas ofertas por estado de leitura.', alerts)
        self.assertNotIn('Termos formados apenas por números são ignorados.', terms)
        self.assertNotIn('Veja palavras e expressões de até três palavras', terms)
        nav = home.split('<div id="main-nav" class="main-nav">', 1)[1].split('</div>', 1)[0]
        positions = [nav.index(f'href="{path}"') for path in
                     ('/', '/alerts', '/rules-page', '/terms', '/telegram', '/groups', '/coupons', '/ignored', '/ai-jobs', '/settings')]
        self.assertEqual(positions, sorted(positions))

    def test_ai_settings_use_auth_csrf_and_never_render_saved_keys(self):
        self.assertEqual(self.client.get('/settings', follow_redirects=False).status_code, 303)
        page = self.client.get('/settings', cookies=self.auth)
        self.assertIn('Inteligência artificial', page.text)
        self.assertIn('Carregar modelos disponíveis', page.text)
        bad = self.client.post('/settings/ai', cookies=self.auth, data={
            'csrf': 'invalid', 'openai_key': 'private-key', 'models_openai': 'gpt-mini',
            'model_order': '[{"provider":"openai","id":"gpt-mini"}]',
        })
        self.assertEqual(bad.status_code, 403)
        response = self.client.post('/settings/ai', cookies=self.auth, data={
            'csrf': main.csrf_token, 'openai_key': 'private-key', 'models_openai': ['gpt-mini'],
            'model_order': '[{"provider":"openai","id":"gpt-mini"}]', 'value': '3',
            'prompt_extra': 'Inclua as condições de uso quando presentes.',
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(main.store.ai_api_key('openai'), 'private-key')
        self.assertEqual(main.store.ai_parallelism(), 3)
        self.assertEqual(main.store.ai_settings()['prompt_extra'], 'Inclua as condições de uso quando presentes.')
        page = self.client.get('/settings', cookies=self.auth)
        self.assertNotIn('private-key', page.text)
        self.assertIn('Chave configurada', page.text)
        self.assertIn('Visualizar prompt base enviado à IA', page.text)
        self.assertIn('Inclua as condições de uso quando presentes.', page.text)

    def test_ai_parallelism_setting_requires_auth_csrf_and_renders_saved_value(self):
        self.assertEqual(self.client.post('/settings/ai/parallelism', data={'value': 2},
                                          follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/settings/ai/parallelism', cookies=self.auth,
                                          data={'csrf': 'invalid', 'value': 2}).status_code, 403)
        response = self.client.post('/settings/ai/parallelism', cookies=self.auth,
                                    data={'csrf': main.csrf_token, 'value': 3}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        page = self.client.get('/settings', cookies=self.auth)
        self.assertIn('name="value" type="number" min="1" max="8" value="3"', page.text)

    def test_ai_provider_timeout_requeues_once_then_marks_item_failed(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100125, 'Grupo'))
        main.store.ingest(-100125, 1, 'Oferta', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        job_id, _ = main.store.enqueue_ai_job(True)

        async def hanging_extract(*_args):
            await asyncio.Event().wait()

        async def run():
            with patch.object(main, 'AI_REQUEST_TIMEOUT', 0.01), patch.object(
                    main, 'extract_ai', side_effect=hanging_extract):
                job = main.store.claim_ai_job()
                await main.process_ai_job(job)
                self.assertEqual(main.store.rows('SELECT status FROM ai_jobs WHERE id=?',
                                                 (job_id,))[0]['status'], 'queued')
                job = main.store.claim_ai_job()
                await main.process_ai_job(job)

        asyncio.run(run())
        self.assertEqual(main.store.rows('SELECT status FROM ai_jobs WHERE id=?',
                                         (job_id,))[0]['status'], 'completed_with_errors')
        self.assertEqual(main.store.rows('SELECT status FROM ai_job_items WHERE job_id=?',
                                         (job_id,))[0]['status'], 'failed')
        outcomes = [row['outcome'] for row in main.store.rows(
            'SELECT outcome FROM ai_job_attempts WHERE job_id=? ORDER BY id', (job_id,))]
        self.assertEqual(outcomes.count('retry'), 1)
        self.assertEqual(outcomes.count('failed'), 3)
        self.assertEqual(main.store.rows("SELECT failure_type,count(*) AS n FROM ai_job_attempts WHERE provider='openai' GROUP BY failure_type"),
                         [{'failure_type': 'request_timeout', 'n': 2}])
        self.assertEqual(main.store.ai_model_metrics()[0]['failures_by_type'], {'request_timeout': 2})
        self.assertIn('Métricas dos modelos', self.client.get('/ai-jobs', cookies=self.auth).text)

    def test_ai_catalog_uses_typed_key_without_persisting_it(self):
        self.assertEqual(self.client.post('/settings/ai/models', headers={'Accept': 'application/json'}, data={
            'csrf': main.csrf_token, 'provider': 'openai', 'api_key': 'no-session',
        }).status_code, 401)
        self.assertEqual(self.client.post('/settings/ai/models', cookies=self.auth, data={
            'csrf': 'invalid', 'provider': 'openai',
        }).status_code, 403)
        with patch.object(main, 'list_ai_models', return_value=[{'id': 'model-a', 'name': 'Model A'}]) as catalog:
            response = self.post('/settings/ai/models', {'provider': 'openai', 'api_key': 'typed-key'})
        self.assertEqual(response.json(), {'ok': True, 'models': [{'id': 'model-a', 'name': 'Model A'}]})
        catalog.assert_called_once_with('openai', 'typed-key')
        self.assertEqual(main.store.rows("SELECT * FROM settings WHERE key='ai_openai_key'"), [])

    def test_ai_job_falls_back_and_extraction_is_prioritized_on_all_offer_screens(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100123, 'Grupo'))
        main.store.add_rule('relógio')
        main.store.ingest(-100123, 1, 'Oferta original: relógio R$ 200', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', 'key-router', [
            {'provider': 'openai', 'id': 'model-first'}, {'provider': 'openrouter', 'id': 'model-second'},
        ], 'Preserve instruções personalizadas.')
        response = self.client.post('/ai-jobs', cookies=self.auth,
                                    data={'csrf': main.csrf_token, 'replace_existing': 'false'},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn('/ai-jobs?notice=Job+', response.headers['location'])
        self.assertNotIn('data-job-create', self.client.get('/settings', cookies=self.auth).text)
        jobs_page = self.client.get('/ai-jobs', cookies=self.auth)
        self.assertIn('data-job-create', jobs_page.text)
        self.assertIn('Job #1', jobs_page.text)
        self.assertIn('Progresso do job', jobs_page.text)
        for url in ('/', '/alerts', '/terms/offers?word=relógio'):
            self.assertIn('IA pendente', self.client.get(url, cookies=self.auth).text)
        self.assertEqual(self.client.get('/ai-jobs/status', cookies=self.auth).status_code, 200)
        job = main.store.claim_ai_job()
        extraction = {
            'product_name': 'Relógio <novo>',
            'original_price': 'R$ 200', 'discounted_price': 'R$ 120', 'coupon_code': 'TEMPO20',
            'product_present': True,
            'coupons': [{'store': 'Loja X', 'code': 'TEMPO20', 'conditions': 'Mínimo R$ 100',
                         'status': 'active'}],
        }
        with patch.object(main, 'extract_ai', side_effect=[AIError('HTTP 429'), extraction]) as extract:
            asyncio.run(main.process_ai_job(job))
        self.assertEqual([call.args[0] for call in extract.call_args_list], ['openai', 'openrouter'])
        attempts = main.store.ai_jobs()[0][0]['logs']
        self.assertEqual([log['outcome'] for log in reversed(attempts)], ['failed', 'succeeded'])
        for url in ('/', '/alerts', '/terms/offers?word=relógio'):
            page = self.client.get(url, cookies=self.auth)
            self.assertIn('Relógio &lt;novo&gt;', page.text)
            self.assertIn('R$ 120', page.text)
            self.assertIn('TEMPO20', page.text)
            self.assertNotIn('Modelo premium', page.text)
            self.assertIn('Oferta original: relógio R$ 200', page.text)
            self.assertIn('Dados retornados pela IA', page.text)
            self.assertIn(r'M\u00ednimo R$ 100', page.text)

    def test_manual_reextraction_requires_auth_csrf_and_returns_result_after_completion(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100123, 'Grupo'))
        offer_id = main.store.ingest(-100123, 1, 'Oferta original', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        self.assertEqual(self.client.post(f'/offers/{offer_id}/extract', data={
            'csrf': main.csrf_token,
        }, follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post(f'/offers/{offer_id}/extract', cookies=self.auth,
            headers={'Accept': 'application/json'}, data={'csrf': 'invalid'}).status_code, 403)
        response = self.client.post(f'/offers/{offer_id}/extract', cookies=self.auth,
                                    headers={'Accept': 'application/json'},
                                    data={'csrf': main.csrf_token})
        self.assertEqual(response.json()['status'], 'queued')
        job = main.store.claim_ai_job()
        extraction = {'product_present': True, 'product_name': 'Produto atualizado',
                      'original_price': None, 'discounted_price': None,
                      'coupon_code': None, 'coupons': []}
        with patch.object(main, 'extract_ai', return_value=extraction):
            asyncio.run(main.process_ai_job(job))
        status = self.client.get(f'/offers/{offer_id}/extraction-status', cookies=self.auth)
        self.assertEqual(status.json(), {'status': 'succeeded', 'extraction': extraction})
        self.assertEqual(status.headers['Cache-Control'], 'no-store')
        replacement = {'product_present': False, 'product_name': None, 'original_price': None,
                       'discounted_price': None, 'coupon_code': 'SAVE', 'coupons': [
                           {'store': 'Loja X', 'code': 'SAVE', 'conditions': None, 'status': 'active', 'links': []},
                       ]}
        response = self.client.post(f'/offers/{offer_id}/extract', cookies=self.auth,
                                    headers={'Accept': 'application/json'},
                                    data={'csrf': main.csrf_token})
        self.assertTrue(response.json()['ok'])
        with patch.object(main, 'extract_ai', return_value=replacement):
            asyncio.run(main.process_ai_job(main.store.claim_ai_job()))
        self.assertEqual(main.store.rows('SELECT count(*) AS n FROM offers'), [{'n': 0}])
        status = self.client.get(f'/offers/{offer_id}/extraction-status', cookies=self.auth)
        self.assertEqual(status.json(), {'status': 'succeeded', 'extraction': replacement})
        self.assertIsNone(main.store.rows('SELECT result_json FROM ai_job_items ORDER BY id DESC LIMIT 1')[0]['result_json'])
        self.assertEqual(self.client.get(f'/offers/{offer_id}/extraction-status', cookies=self.auth).json(),
                         {'status': 'succeeded', 'extraction': None})

    def test_later_default_job_skips_extractions_completed_by_an_earlier_job(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100123, 'Grupo'))
        main.store.ingest(-100123, 1, 'Oferta teste', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        first_id, _ = main.store.enqueue_ai_job()
        second_id, _ = main.store.enqueue_ai_job()
        result = {'product_name': 'Produto', 'original_price': None,
                  'discounted_price': None, 'coupon_code': None}
        first_job = main.store.claim_ai_job()
        self.assertEqual(first_job['id'], first_id)
        with patch.object(main, 'extract_ai', return_value=result):
            asyncio.run(main.process_ai_job(first_job))
        second_job = main.store.claim_ai_job()
        self.assertEqual(second_job['id'], second_id)
        with patch.object(main, 'extract_ai') as extract:
            asyncio.run(main.process_ai_job(second_job))
        extract.assert_not_called()
        jobs, _ = main.store.ai_jobs()
        second = next(job for job in jobs if job['id'] == second_id)
        self.assertEqual(second['status'], 'completed')
        self.assertEqual(second['skipped'], 1)

    def test_live_provider_settings_apply_before_each_fallback_call(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100123, 'Grupo'))
        main.store.ingest(-100123, 1, 'Oferta teste', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', 'key-router', [
            {'provider': 'openai', 'id': 'model-first'}, {'provider': 'openrouter', 'id': 'model-second'},
        ], 'Preserve instruções personalizadas.')
        main.store.enqueue_ai_job()
        job = main.store.claim_ai_job()
        calls = []

        def extract(provider, key, model, text, prompt_extra=''):
            calls.append((provider, key, model, prompt_extra))
            if len(calls) == 1:
                main.store.save_ai_settings('rotated-openai', '', [{'provider': 'openai', 'id': 'replacement'}],
                                            'Instruções atualizadas.')
                raise AIError('Falha simulada')
            return {'product_name': 'Produto atualizado', 'original_price': None,
                    'discounted_price': None, 'coupon_code': None}

        with patch.object(main, 'extract_ai', side_effect=extract):
            asyncio.run(main.process_ai_job(job))
        self.assertEqual(calls, [('openai', 'key-openai', 'model-first', 'Preserve instruções personalizadas.'),
                                 ('openai', 'rotated-openai', 'replacement', 'Instruções atualizadas.')])

    def test_cancel_pending_ai_job_requires_auth_and_csrf(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100123, 'Grupo'))
        main.store.ingest(-100123, 1, 'Oferta teste', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        job_id, _ = main.store.enqueue_ai_job()
        page = self.client.get('/ai-jobs', cookies=self.auth)
        self.assertIn(f'action="/ai-jobs/{job_id}/cancel"', page.text)
        self.assertIn('Cancelar job', page.text)
        self.assertEqual(self.client.post(f'/ai-jobs/{job_id}/cancel', data={'csrf': main.csrf_token},
                                          follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post(f'/ai-jobs/{job_id}/cancel', cookies=self.auth,
                                          data={'csrf': 'bad'}).status_code, 403)
        response = self.client.post(f'/ai-jobs/{job_id}/cancel', cookies=self.auth,
                                    data={'csrf': main.csrf_token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(main.store.ai_jobs()[0][0]['status'], 'cancelled')

    def test_ai_job_cleanup_actions_keep_auth_csrf_and_wait_for_active_worker(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100126, 'Grupo'))
        main.store.ingest(-100126, 1, 'Oferta teste', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        completed_id, _ = main.store.enqueue_ai_job()
        main.store.cancel_ai_job(completed_id)
        page = self.client.get('/ai-jobs', cookies=self.auth)
        self.assertIn('Limpar concluídos', page.text)
        self.assertIn('Cancelar e limpar tudo', page.text)
        self.assertIn('data-confirm=', page.text)
        queued_id, _ = main.store.enqueue_ai_job()
        response = self.client.post('/ai-jobs/clear-completed', cookies=self.auth,
                                    data={'csrf': main.csrf_token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(main.store.rows('SELECT id FROM ai_jobs'), [{'id': queued_id}])
        self.assertEqual(self.client.post('/ai-jobs/clear-all', cookies=self.auth,
                                          data={'csrf': 'bad'}).status_code, 403)
        self.assertEqual(self.client.post('/ai-jobs/clear-all', cookies=self.auth,
                                          data={'csrf': main.csrf_token}, follow_redirects=False).status_code, 303)
        self.assertEqual(main.store.rows('SELECT id FROM ai_jobs'), [])

        active_id, _ = main.store.enqueue_ai_job(True)
        job = main.store.claim_ai_job()
        started = asyncio.Event()

        async def hanging_extract(*_args):
            started.set()
            await asyncio.Event().wait()

        async def run():
            with patch.object(main, 'extract_ai', side_effect=hanging_extract):
                worker = asyncio.create_task(main.process_ai_job(job))
                await started.wait()
                response = await main.clear_all_ai_jobs()
                self.assertEqual(response.status_code, 303)
                await asyncio.wait_for(worker, timeout=1)

        asyncio.run(run())
        self.assertEqual(main.store.rows('SELECT id FROM ai_jobs'), [])
        self.assertEqual(main.store.rows('SELECT * FROM ai_job_items'), [])
        self.assertEqual(main.store.rows('SELECT * FROM ai_job_attempts'), [])

    def test_running_ai_job_cancellation_discards_call_result_and_stops_batch(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100123, 'Grupo'))
        for message_id in (1, 2):
            main.store.ingest(-100123, message_id, f'Oferta {message_id}', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        job_id, _ = main.store.enqueue_ai_job(True)
        job = main.store.claim_ai_job()
        calls = []

        def extract(provider, key, model, text, prompt_extra=''):
            calls.append(text)
            main.store.cancel_ai_job(job_id)
            return {'product_name': 'Resultado descartado', 'original_price': None,
                    'discounted_price': None, 'coupon_code': None}

        with patch.object(main, 'extract_ai', side_effect=extract):
            asyncio.run(main.process_ai_job(job))
        jobs, active = main.store.ai_jobs()
        self.assertEqual(len(calls), 1)
        self.assertIsNone(active)
        self.assertEqual(jobs[0]['status'], 'cancelled')
        self.assertEqual(jobs[0]['cancelled'], 2)
        self.assertTrue(all(card['extraction'] is None for card in main.store.feed()))

    def test_cancelling_running_ai_job_interrupts_local_request_and_worker_continues(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100124, 'Grupo'))
        for message_id in (1, 2):
            main.store.ingest(-100124, message_id, f'Oferta {message_id}', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        job_id, _ = main.store.enqueue_ai_job(True)
        job = main.store.claim_ai_job()
        started = asyncio.Event()
        calls = []

        async def hanging_extract(*_args):
            calls.append('started')
            started.set()
            await asyncio.Event().wait()

        async def run():
            with patch.object(main, 'extract_ai', side_effect=hanging_extract):
                worker = asyncio.create_task(main.process_ai_job(job))
                await started.wait()
                await main.cancel_ai_job(job_id)
                await asyncio.wait_for(worker, timeout=1)

        asyncio.run(run())
        jobs, active = main.store.ai_jobs()
        self.assertEqual(calls, ['started'])
        self.assertIsNone(active)
        self.assertEqual(jobs[0]['status'], 'cancelled')
        self.assertEqual(jobs[0]['cancelled'], 2)
        self.assertEqual(jobs[0]['logs'][0]['outcome'], 'cancelled')
        self.assertIn('pode continuar', jobs[0]['logs'][0]['detail'])

        next_id, _ = main.store.enqueue_ai_job(True)
        next_job = main.store.claim_ai_job()
        self.assertEqual(next_job['id'], next_id)
        with patch.object(main, 'extract_ai', return_value={'product_name': 'Produto'}):
            asyncio.run(main.process_ai_job(next_job))
        self.assertEqual(main.store.ai_jobs()[0][0]['status'], 'completed')

    def test_permanent_ignore_interrupts_inflight_ai_and_cancels_remaining_items(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100125, 'Grupo'))
        main.store.ingest(-100125, 1, 'Oferta comum', '2026-11-05T12:00:00+00:00', None)
        main.store.ingest(-100125, 2, 'Notebook secreto', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        job_id, _ = main.store.enqueue_ai_job(True)
        job = main.store.claim_ai_job()
        main.store.add_ignored('secreto')
        rule_id = main.store.rows("SELECT id FROM ignored_keywords WHERE normalized='secreto'")[0]['id']
        started = asyncio.Event()
        calls = []

        async def hanging_extract(*_args):
            calls.append('started')
            started.set()
            await asyncio.Event().wait()

        async def run():
            with patch.object(main, 'extract_ai', side_effect=hanging_extract):
                worker = asyncio.create_task(main.process_ai_job(job))
                await started.wait()
                main.store.set_ignored_auto_delete(rule_id, True)
                self.assertTrue(main.store.ai_job_cancel_requested(job_id))
                await asyncio.wait_for(worker, timeout=1)

        asyncio.run(run())
        jobs, active = main.store.ai_jobs()
        self.assertEqual(calls, ['started'])
        self.assertIsNone(active)
        self.assertEqual(jobs[0]['status'], 'cancelled')
        self.assertEqual(jobs[0]['cancelled'], 2)
        self.assertEqual(main.store.rows('SELECT message_id FROM offers'), [{'message_id': 1}])
        self.assertEqual(main.store.rows('SELECT * FROM offer_extractions'), [])

    def test_worker_shutdown_keeps_inflight_item_recoverable(self):
        main.store.execute('INSERT INTO chats VALUES(?,?)', (-100125, 'Grupo'))
        main.store.ingest(-100125, 1, 'Oferta', '2026-11-05T12:00:00+00:00', None)
        main.store.save_ai_settings('key-openai', '', [{'provider': 'openai', 'id': 'model'}])
        job_id, _ = main.store.enqueue_ai_job(True)
        job = main.store.claim_ai_job()
        started = asyncio.Event()

        async def hanging_extract(*_args):
            started.set()
            await asyncio.Event().wait()

        async def run():
            with patch.object(main, 'extract_ai', side_effect=hanging_extract):
                worker = asyncio.create_task(main.process_ai_job(job))
                await started.wait()
                worker.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker

        asyncio.run(run())
        self.assertEqual(main.store.rows('SELECT status FROM ai_job_items WHERE job_id=?',
                                         (job_id,))[0]['status'], 'processing')
        main.store.recover_ai_jobs()
        self.assertEqual(main.store.rows('SELECT status FROM ai_job_items WHERE job_id=?',
                                         (job_id,))[0]['status'], 'queued')

    def test_feed_layout_and_new_offers_button_structure(self):
        home = self.client.get('/', cookies=self.auth).text
        alerts = self.client.get('/alerts', cookies=self.auth).text
        css = self.client.get('/static/style.css').text
        self.assertIn('<div class="layout"><div>', home)
        self.assertIn('<div class="layout"><div>', alerts)
        self.assertIn('<div id="new-offers-status" class="new-offers-status" role="status" aria-live="polite" hidden><button type="button" id="new-offers"></button></div>', home)
        self.assertIn('.layout{display:grid;grid-template-columns:minmax(0,1fr);', css)
        self.assertNotIn('grid-template-columns:340px', css)
        self.assertIn('.new-offers-status.error #new-offers', css)
        self.assertIn('@media(max-width:600px){#new-offers{padding-right:80px}}', css)

    def test_panel_login_session_logout_and_csrf(self):
        page = self.client.get('/', follow_redirects=False)
        self.assertEqual(page.headers['location'], '/login')
        self.assertNotIn('www-authenticate', page.headers)
        self.assertIn('Entre no seu painel', self.client.get('/login').text)
        self.assertEqual(self.client.post('/login', data={'username': 'admin', 'panel_password': 'bad'}).status_code, 403)
        invalid = self.client.post('/login', data={'csrf': main.csrf_token, 'username': 'admin', 'panel_password': 'wrong-secret'})
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn('wrong-secret', invalid.text)
        login = self.client.post('/login', data={'csrf': main.csrf_token, 'username': 'admin', 'panel_password': main.password}, follow_redirects=False)
        self.assertEqual(login.status_code, 303)
        self.assertIn('HttpOnly', login.headers['set-cookie'])
        self.assertIn('SameSite=strict', login.headers['set-cookie'])
        self.assertNotIn(main.password, login.headers['set-cookie'])
        session_cookie = self.client.cookies.get('panel_session')
        self.assertEqual(self.client.get('/ignored').status_code, 200)
        self.assertEqual(self.client.post('/logout').status_code, 403)
        self.assertEqual(self.client.post('/logout', data={'csrf': main.csrf_token}, follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get('/ignored', follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get('/ignored', cookies={'panel_session': session_cookie}, follow_redirects=False).status_code, 303)
        main.sessions['expired'] = 0
        self.assertEqual(self.client.get('/ignored', cookies={'panel_session': 'expired'}, follow_redirects=False).status_code, 303)
        self.assertNotIn('expired', main.sessions)
        secure = self.client.post('https://testserver/login', data={'csrf': main.csrf_token, 'username': 'admin', 'panel_password': main.password}, follow_redirects=False)
        self.assertIn('Secure', secure.headers['set-cookie'])

    def test_quick_rule_validates_csrf_and_data(self):
        headers = {'Accept': 'application/json'}
        self.assertEqual(self.client.post('/rules', cookies=self.auth, headers=headers, data={'keyword': 'x'}).status_code, 403)
        invalid = self.client.post('/rules', cookies=self.auth, headers=headers, data={'csrf': main.csrf_token, 'keyword': ' '})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.post('/rules', cookies=self.auth, headers=headers,
            data={'csrf': main.csrf_token, 'keyword': 'café, notebook'}).status_code, 400)
        valid = self.client.post('/rules', cookies=self.auth, headers=headers, data={'csrf': main.csrf_token, 'keyword': 'Café'})
        self.assertTrue(valid.json()['ok'])
        self.assertEqual(valid.json()['matched'], 0)
        self.assertEqual(main.store.rows('SELECT name FROM rules'), [{'name': 'Café'}])

    def test_rule_creation_reports_existing_alerts(self):
        main.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Grupo',))
        main.store.ingest(-100123, 1, 'Notebook capa', '2026-11-04T12:00:00+00:00', None,
                          source_json='{"grouped_id": 50}')
        main.store.ingest(-100123, 2, 'Notebook segunda parte', '2026-11-04T12:00:01+00:00', None,
                          source_json='{"grouped_id": 50}')
        with patch.object(main.telegram, 'notify_alert', new_callable=AsyncMock) as notify:
            response = self.client.post('/rules', cookies=self.auth, headers={'Accept': 'application/json'},
                data={'csrf': main.csrf_token, 'keyword': 'notebook'})
        self.assertEqual(response.json()['matched'], 2)
        notify.assert_awaited_once()
        self.assertEqual(notify.await_args.args[0]['body'], 'Notebook capa')
        self.assertNotIn('token', response.text)
        self.assertIn('Notebook', self.client.get('/alerts', cookies=self.auth).text)
        self.assertEqual(main.store.unread(), 1)

    def test_rule_management_has_own_page(self):
        main.store.add_rule('Notebook')
        home = self.client.get('/', cookies=self.auth)
        self.assertNotIn('id="rules-list"', home.text)
        self.assertNotIn('id="quick-rule"', home.text)
        page = self.client.get('/rules-page', cookies=self.auth)
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="rules-list"', page.text)
        self.assertIn('id="rule-search"', page.text)
        self.assertNotIn('name="name"', page.text)
        self.assertIn('data-confirm="Remover a regra', page.text)
        self.assertEqual(self.client.get('/rules-page', follow_redirects=False).status_code, 303)

    def test_rule_and_ignored_management_sort_newest_first_and_show_dates(self):
        main.store.execute("INSERT INTO rules(id,name,keywords,created_at) VALUES(1,'Antiga','antiga','2026-01-01T00:00:00Z')")
        main.store.execute("INSERT INTO rules(id,name,keywords,created_at) VALUES(2,'Nova','nova','2026-02-01T00:00:00Z')")
        main.store.execute("INSERT INTO ignored_keywords(id,word,normalized,created_at) VALUES(1,'Antiga','antiga','2026-01-01T00:00:00Z')")
        main.store.execute("INSERT INTO ignored_keywords(id,word,normalized,created_at) VALUES(2,'Nova','nova','2026-02-01T00:00:00Z')")
        rules = self.client.get('/rules-page', cookies=self.auth).text
        ignored = self.client.get('/ignored', cookies=self.auth).text
        self.assertLess(rules.index('>nova</td>'), rules.index('>antiga</td>'))
        self.assertLess(ignored.index('<span>Nova</span>'), ignored.index('<span>Antiga</span>'))
        self.assertIn('2026-02-01T00:00:00Z', rules)
        self.assertIn('data-sort="date" aria-sort="descending"', ignored)

    def test_ignored_search_and_pagination_are_server_side_and_toggle_redirect_preserves_state(self):
        for i in range(30):
            word = f'produto-{i:02d}'
            main.store.execute('INSERT INTO ignored_keywords(word,normalized,created_at) VALUES(?,?,?)',
                               (word, word, f'2026-11-{(i % 9) + 1:02d}T00:00:{i:02d}Z'))
        first = self.client.get('/ignored?q=PRODUTO&page=1', cookies=self.auth).text
        second = self.client.get('/ignored?q=produto&page=2', cookies=self.auth).text
        self.assertIn('30 palavras cadastradas', first)
        self.assertIn('Página 1 de 2', first)
        self.assertIn('Página 2 de 2', second)
        self.assertNotIn('produto-00', first)
        self.assertIn('produto-00', second)
        self.assertIn('name="q" value="produto"', second)
        row = main.store.rows("SELECT id FROM ignored_keywords WHERE normalized='produto-00'")[0]
        response = self.client.post(f"/ignored/{row['id']}/auto-delete", cookies=self.auth,
            data={'csrf': main.csrf_token, 'enabled': 'true', 'q': 'produto', 'page': '2'},
            follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn('/ignored?q=produto&page=2', response.headers['location'])

    def test_ignored_search_matches_accentless_and_keeps_search_literals(self):
        main.store.add_ignored('Café especial')
        page = self.client.get('/ignored?q=CAFE%20ESPECIAL', cookies=self.auth).text
        self.assertIn('Café especial', page)
        literal = self.client.get('/ignored?q=%25', cookies=self.auth).text
        self.assertNotIn('Café especial', literal)

    def test_recently_deleted_page_shows_ignored_and_manual_offers(self):
        from datetime import datetime, timezone
        main.store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
        main.store.add_ignored('PS5 Slim')
        date = datetime.now(timezone.utc).isoformat()
        main.store.ingest(1, 1, 'PS5 Slim oferta', date, None)
        manual_id = main.store.ingest(1, 2, 'Oferta removida manualmente', date, None)
        main.store.delete_offer(manual_id)
        page = self.client.get('/deleted', cookies=self.auth)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Excluídas recentemente', page.text)
        self.assertIn('Excluída por palavra ignorada', page.text)
        self.assertIn('Excluída manualmente', page.text)
        self.assertEqual(self.client.get('/deleted', follow_redirects=False).status_code, 303)

    def test_deleted_page_paginates_cards_without_splitting_album(self):
        main.store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
        for message_id in range(1, 25):
            offer_id = main.store.ingest(1, message_id, f'Oferta manual {message_id}', '2026-11-08', None)
            main.store.delete_offer(offer_id)
            main.store.execute('UPDATE offers SET deleted_at=? WHERE id=?',
                               ('2026-11-08T12:00:00+00:00', offer_id))
        main.store.ingest(1, 25, 'Álbum parte um', '2026-11-08', None,
                          source_json='{"grouped_id":77}')
        main.store.ingest(1, 26, 'Álbum parte dois', '2026-11-08', None,
                          source_json='{"grouped_id":77}')
        main.store.delete_offer(main.store.rows('SELECT id FROM offers WHERE message_id=25')[0]['id'])
        main.store.execute("UPDATE offers SET deleted_at='2026-11-08T11:00:00+00:00' WHERE grouped_id='77'")
        main.store.execute("UPDATE offers SET deleted_at='2026-11-08T11:30:00+00:00' WHERE message_id=25")
        middle_id = main.store.ingest(1, 27, 'Oferta manual do meio', '2026-11-08', None)
        main.store.delete_offer(middle_id)
        main.store.execute('UPDATE offers SET deleted_at=? WHERE id=?',
                           ('2026-11-08T11:15:00+00:00', middle_id))
        last_id = main.store.ingest(1, 28, 'Oferta manual da página dois', '2026-11-08', None)
        main.store.delete_offer(last_id)
        main.store.execute('UPDATE offers SET deleted_at=? WHERE id=?',
                           ('2026-11-08T10:00:00+00:00', last_id))

        first = self.client.get('/deleted', cookies=self.auth)
        second = self.client.get('/deleted?page=2', cookies=self.auth)
        beyond = self.client.get('/deleted?page=99', cookies=self.auth)

        self.assertIn('27 ofertas ocultas', first.text)
        self.assertIn('Página 1 de 2', first.text)
        self.assertIn('Álbum parte um', first.text)
        self.assertIn('Álbum parte dois', first.text)
        self.assertNotIn('data-reextract', first.text)
        self.assertIn('datetime="2026-11-08T11:30:00+00:00"', first.text)
        self.assertNotIn('Oferta manual da página dois', first.text)
        self.assertIn('Página 2 de 2', second.text)
        self.assertIn('Oferta manual do meio', second.text)
        self.assertIn('Oferta manual da página dois', second.text)
        self.assertNotIn('Álbum parte um', second.text)
        self.assertIn('Página 2 de 2', beyond.text)

    def test_alert_offer_deletion_is_soft_authenticated_and_album_wide(self):
        import json
        main.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Grupo',))
        main.store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Notebook', 'notebook'))
        main.store.ingest(-100123, 1, 'Notebook parte alertada', '2026-11-04T12:00:00+00:00', None,
                          source_json=json.dumps({'grouped_id': 123}))
        main.store.ingest(-100123, 2, 'Notebook outra parte', '2026-11-04T12:00:01+00:00', None,
                          source_json=json.dumps({'grouped_id': 123}))
        main.store.ingest(-100123, 3, 'Sem alerta', '2026-11-04T12:00:02+00:00', None)
        self.assertEqual(len(main.store.rows('SELECT * FROM hits')), 2)
        card = self.client.get('/alerts', cookies=self.auth)
        self.assertIn('data-mark-seen', card.text)
        self.assertNotIn('data-confirm="Excluir definitivamente esta oferta', card.text)
        self.client.post('/offers/1/seen', cookies=self.auth,
            data={'csrf': main.csrf_token, 'alerts': 'true'})
        home = self.client.get('/', cookies=self.auth)
        self.assertNotIn('action="/offers/1/delete"', home.text)
        self.assertNotIn('id="telegram-panel"', home.text)
        telegram_page = self.client.get('/telegram', cookies=self.auth)
        self.assertIn('id="telegram-panel"', telegram_page.text)
        self.assertIn('action="/offers/3/delete"', home.text)
        read_alerts = self.client.get('/alerts?read=true', cookies=self.auth)
        self.assertIn('action="/offers/1/delete"', read_alerts.text)
        self.assertEqual(self.client.post('/offers/3/delete', cookies=self.auth,
            data={'csrf': main.csrf_token, 'alerts': 'false'}, follow_redirects=False).headers['location'], '/?notice=Oferta+removida.&q=')
        self.assertEqual(self.client.post('/offers/1/delete', data={'csrf': main.csrf_token},
                                          follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/offers/1/delete', cookies=self.auth,
              data={'csrf': main.csrf_token, 'q': 'Notebook', 'alerts': 'true'},
              follow_redirects=False).status_code, 303)
        self.assertEqual({row['message_id'] for row in main.store.rows('SELECT message_id FROM offers')}, {1, 2, 3})
        self.assertEqual(main.store.rows('SELECT count(*) AS n FROM offers WHERE deleted_at IS NOT NULL')[0]['n'], 3)
        self.assertEqual(main.store.rows('SELECT count(*) AS n FROM hits')[0]['n'], 2)
        self.assertEqual(main.store.feed(alerts=True), [])
        self.assertEqual(self.client.post('/offers/1/delete/undo', cookies=self.auth,
            headers={'Accept': 'application/json'}, data={'csrf': main.csrf_token}).json()['ok'], True)
        self.assertEqual(len(main.store.feed(alerts=True)), 1)

    def test_card_actions_return_json_and_can_undo_without_moving_cards(self):
        main.store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
        main.store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Notebook', 'notebook'))
        first = main.store.ingest(1, 1, 'Notebook promoção', '2026-11-04', None)
        headers = {'Accept': 'application/json'}
        data = {'csrf': main.csrf_token}
        self.assertEqual(self.client.post(f'/offers/{first}/seen/undo', headers=headers, data=data).status_code, 401)
        self.assertEqual(self.client.post(f'/offers/{first}/seen/undo', cookies=self.auth,
            headers=headers, data={}).status_code, 403)
        seen = self.client.post(f'/offers/{first}/seen', cookies=self.auth, headers=headers, data=data)
        self.assertTrue(seen.json()['ok'])
        self.assertEqual(seen.json()['unread'], 0)
        self.assertTrue(self.client.post(f'/offers/{first}/seen/undo', cookies=self.auth,
            headers=headers, data=data).json()['ok'])
        deleted = self.client.post(f'/offers/{first}/delete', cookies=self.auth, headers=headers, data=data)
        self.assertTrue(deleted.json()['ok'])
        self.assertEqual(main.store.feed(alerts=True), [])
        self.assertTrue(self.client.post(f'/offers/{first}/delete/undo', cookies=self.auth,
            headers=headers, data=data).json()['ok'])
        self.assertEqual(len(main.store.feed(alerts=True)), 1)

    def test_signed_offer_image_requires_valid_unexpired_signature(self):
        from pathlib import Path
        main.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Grupo',))
        main.store.ingest(-100123, 9, 'Oferta com imagem', '2026-11-04T12:00:00+00:00', None,
                          source_json='{"media":{"photo":{"_":"Photo","id":55}}}')
        offer = main.store.rows('SELECT * FROM offers')[0]
        expiry = int(time.time()) + 3600
        identity = f"{offer['chat_id']}:{offer['message_id']}:{expiry}"
        signature = hmac.new(main.store.media_signing_key().encode(), identity.encode(), hashlib.sha256).hexdigest()
        path = f"/public-media/{offer['id']}/{expiry}/{signature}"
        image = Path(self.tmp.name) / 'thumbnail.jpg'
        image.write_bytes(b'fake jpeg')
        with patch.object(main.telegram, 'download', new_callable=AsyncMock, return_value=image):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cross-Origin-Resource-Policy'], 'cross-origin')
            self.assertEqual(response.content, b'fake jpeg')
            main.store.delete_offer(offer['id'])
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.get(path.replace(signature, 'bad')).status_code, 404)
            expired = int(time.time()) - 1
            expired_identity = f"{offer['chat_id']}:{offer['message_id']}:{expired}"
            expired_signature = hmac.new(main.store.media_signing_key().encode(), expired_identity.encode(), hashlib.sha256).hexdigest()
            self.assertEqual(self.client.get(f"/public-media/{offer['id']}/{expired}/{expired_signature}").status_code, 404)
            future = int(time.time()) + 24 * 60 * 60 + 60
            future_identity = f"{offer['chat_id']}:{offer['message_id']}:{future}"
            future_signature = hmac.new(main.store.media_signing_key().encode(), future_identity.encode(), hashlib.sha256).hexdigest()
            self.assertEqual(self.client.get(f"/public-media/{offer['id']}/{future}/{future_signature}").status_code, 404)

    def test_offer_media_is_available_until_deleted_offer_is_purged(self):
        from pathlib import Path
        main.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Grupo',))
        offer_id = main.store.ingest(-100123, 10, 'Oferta com imagem', '2026-11-04T12:00:00+00:00', None,
                                     source_json='{"media":{"photo":{"_":"Photo","id":55}}}')
        image = Path(self.tmp.name) / 'offer.jpg'
        image.write_bytes(b'fake jpeg')
        with patch.object(main.telegram, 'download', new_callable=AsyncMock, return_value=image) as download:
            self.assertEqual(self.client.get(f'/offers/{offer_id}/media', cookies=self.auth).status_code, 200)
            self.assertEqual(download.await_count, 1)

            main.store.delete_offer(offer_id)
            self.assertEqual(self.client.get(f'/offers/{offer_id}/media', cookies=self.auth).status_code, 200)
            main.store.execute('DELETE FROM offers WHERE id=?', (offer_id,))
            self.assertEqual(self.client.get(f'/offers/{offer_id}/media', cookies=self.auth).status_code, 404)

    def test_signed_offer_image_does_not_expose_spoilers(self):
        main.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Grupo',))
        main.store.ingest(-100123, 10, 'Oferta com spoiler', '2026-11-04T12:00:00+00:00', None,
                          source_json='{"media":{"photo":{"_":"Photo","id":56},"spoiler":true}}')
        offer = main.store.rows('SELECT * FROM offers')[0]
        expiry = int(time.time()) + 3600
        identity = f"{offer['chat_id']}:{offer['message_id']}:{expiry}"
        signature = hmac.new(main.store.media_signing_key().encode(), identity.encode(), hashlib.sha256).hexdigest()
        with patch.object(main.telegram, 'download', new_callable=AsyncMock) as download:
            response = self.client.get(f"/public-media/{offer['id']}/{expiry}/{signature}")
        self.assertEqual(response.status_code, 404)
        download.assert_not_awaited()

    def test_brand_assets_are_accessible_and_used_by_dashboard(self):
        response = self.client.get('/', cookies=self.auth)
        self.assertIn('src="/brand/logo.svg"', response.text)
        self.assertIn('href="/brand/logo-icon.svg"', response.text)
        self.assertIn('alt="MurkTelegot"', response.text)
        for name in ('logo.svg', 'logo-icon.svg'):
            asset = self.client.get('/brand/' + name)
            self.assertEqual(asset.status_code, 200)
            self.assertIn('image/svg+xml', asset.headers['content-type'])
            self.assertEqual(asset.content, (Path('assets/murktelegot-logo') / name).read_bytes())

    def test_rule_offer_alert_read_and_delete(self):
        self.assertEqual(self.post('/rules', {'keyword': 'Café'}).status_code, 200)
        main.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Grupo',))
        main.store.ingest(-100123, 1, '<script>alert(1)</script> café', '2026-11-04T12:00:00+00:00', 'https://t.me/c/123/1')
        response = self.client.get('/?alerts=true', cookies=self.auth)
        self.assertIn('Novo alerta', response.text)
        self.assertIn('&lt;script&gt;', response.text)
        self.assertNotIn('<script>', response.text)
        self.assertNotIn('Novo alerta', self.post('/offers/1/seen').text)
        self.post('/rules/1/delete')
        self.assertEqual(main.store.rows('SELECT * FROM hits'), [])
        self.assertEqual(len(main.store.rows('SELECT * FROM offers')), 1)

    def test_search_escapes_wildcards(self):
        main.store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
        main.store.ingest(1, 1, 'Oferta 50% OFF', '2026-11-04', None)
        main.store.ingest(1, 2, 'Outro produto', '2026-11-04', None)
        result = self.client.get('/', params={'q': '%'}, cookies=self.auth)
        self.assertIn('50% OFF', result.text)
        self.assertNotIn('Outro produto', result.text)

    def test_group_selection_validates_membership_and_preserves_on_error(self):
        with patch.object(main.telegram, 'authorized', AsyncMock(return_value=True)), patch.object(main.telegram, 'dialogs', AsyncMock(return_value=[{'id': -100123, 'title': 'Grupo'}])):
            self.assertEqual(self.post('/groups', {'chat_ids': '-100123'}).status_code, 200)
            self.assertEqual(self.post('/groups', {'chat_ids': '999'}).status_code, 400)
            self.assertEqual(main.store.rows('SELECT id FROM chats'), [{'id': -100123}])

    def test_login_preserves_phone_and_exposes_only_current_step(self):
        from types import SimpleNamespace
        from app.telegram import Telegram
        from telethon import errors
        telegram = Telegram(main.store, Path(self.tmp.name), None, None)
        telegram.client = AsyncMock()
        telegram.client.is_connected = Mock(return_value=True)
        telegram.client.is_user_authorized.return_value = False
        telegram.client.send_code_request.return_value = SimpleNamespace(phone_code_hash='private-hash')
        with patch.object(main, 'telegram', telegram):
            initial = self.client.get('/telegram', cookies=self.auth)
            self.assertNotIn('name="code"', initial.text)
            response = self.client.post('/telegram/code', cookies=self.auth,
                headers={'Accept': 'application/json'},
                data={'csrf': main.csrf_token, 'phone': '+5511999999999'})
            self.assertEqual(response.status_code, 200)
            html = response.json()['html']
            self.assertIn('value="+5511999999999"', html)
            self.assertIn('name="code"', html)
            self.assertNotIn('private-hash', response.text)
            self.assertIn('value="+5511999999999"', self.client.get('/telegram', cookies=self.auth).text)
            telegram.client.sign_in.side_effect = errors.PhoneCodeInvalidError(None)
            error = self.client.post('/telegram/login', cookies=self.auth,
                headers={'Accept': 'application/json'},
                data={'csrf': main.csrf_token, 'code': '99999', 'password': 'secret-value'})
            self.assertEqual(error.status_code, 400)
            self.assertIn('Código incorreto', error.json()['message'])
            self.assertNotIn('html', error.json())
            self.assertNotIn('99999', error.text)
            self.assertNotIn('secret-value', error.text)
            self.assertEqual(telegram.phone, '+5511999999999')

    def test_two_factor_response_shows_password_without_requiring_code(self):
        from app.telegram import Telegram
        from telethon import errors
        telegram = Telegram(main.store, Path(self.tmp.name), None, None)
        telegram.client = AsyncMock()
        telegram.client.is_connected = Mock(return_value=True)
        telegram.client.is_user_authorized.return_value = False
        telegram.phone, telegram.code_hash = '+5511999999999', 'private-hash'
        telegram.client.sign_in.side_effect = errors.SessionPasswordNeededError(None)
        with patch.object(main, 'telegram', telegram):
            response = self.client.post('/telegram/login', cookies=self.auth,
                headers={'Accept': 'application/json'},
                data={'csrf': main.csrf_token, 'code': '12345'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('name="password"', response.json()['html'])
            self.assertNotIn('name="code"', response.json()['html'])
            self.assertNotIn('12345', response.text)

    def test_mark_read_preserves_filter_search_and_position(self):
        response = self.client.post('/offers/1/seen', cookies=self.auth, follow_redirects=False,
            data={'csrf': main.csrf_token, 'q': 'café', 'alerts': 'true'})
        from urllib.parse import urlparse, parse_qs
        url = urlparse(response.headers['location'])
        self.assertEqual(parse_qs(url.query)['q'], ['café'])
        self.assertEqual(url.path, '/alerts')
        self.assertEqual(url.fragment, '')

    def test_alert_page_separates_states_and_direct_mark_read(self):
        main.store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
        main.store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Notebook', 'notebook'))
        main.store.add_ignored('PS5 Slim')
        first = main.store.ingest(1, 1, 'Notebook PS5 Slim', '2026-11-04', None)
        second = main.store.ingest(1, 2, 'Notebook lido', '2026-11-04', None)
        main.store.mark_seen(second)
        page = self.client.get('/alerts', cookies=self.auth)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Não lidos · <span data-alert-count>1</span>', page.text)
        self.assertIn('Lidos · <span data-alert-count>1</span>', page.text)
        self.assertIn('Notebook PS5 Slim', page.text)
        self.assertIn('data-mark-seen', page.text)
        self.assertIn('Notebook PS5 Slim', self.client.get('/', cookies=self.auth).text)
        self.assertEqual(self.client.post(f'/offers/{first}/seen', cookies=self.auth, headers={'Accept': 'application/json'}).status_code, 403)
        response = self.client.post(f'/offers/{first}/seen', cookies=self.auth, headers={'Accept': 'application/json'}, data={'csrf': main.csrf_token})
        self.assertTrue(response.json()['ok'])
        updated = self.client.get('/alerts', cookies=self.auth).text
        self.assertIn('Não lidos · <span data-alert-count>0</span>', updated)
        self.assertIn('Lidos · <span data-alert-count>2</span>', updated)
        self.assertNotIn('Notebook PS5 Slim', self.client.get('/', cookies=self.auth).text)
        self.assertEqual(main.store.unread(), 0)
        third = main.store.ingest(1, 3, 'Notebook fallback', '2026-11-04', None)
        response = self.client.post(f'/offers/{third}/seen', cookies=self.auth, follow_redirects=False,
            data={'csrf': main.csrf_token, 'q': 'Notebook', 'alerts': 'true'})
        self.assertTrue(response.headers['location'].startswith('/alerts?'))
        self.assertIn('q=Notebook', response.headers['location'])
        self.assertEqual(main.store.unread(), 0)

    def test_empty_search_and_alerts_have_specific_guidance(self):
        self.assertIn('Nenhuma oferta encontrada.', self.client.get('/?q=nothing', cookies=self.auth).text)
        self.assertIn('Nenhum alerta não lido', self.client.get('/alerts', cookies=self.auth).text)

class TelegramTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_messages_are_not_ingested(self):
        from types import SimpleNamespace
        from datetime import datetime, timezone
        from app.telegram import Telegram
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db.sqlite')
            store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
            store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Notebook', 'notebook'))
            telegram = Telegram(store, Path(directory), None, None)
            message = SimpleNamespace(
                id=9,
                raw_text='Notebook em oferta',
                date=datetime.now(timezone.utc),
                to_json=lambda: json.dumps({'reply_to': {'reply_to_msg_id': 4}}),
            )

            await telegram.receive(SimpleNamespace(chat_id=-100123, message=message))

            self.assertEqual(store.rows('SELECT * FROM offers'), [])
            self.assertEqual(store.rows('SELECT * FROM hits'), [])

    async def test_event_ingestion_ignores_private_and_handles_edits(self):
        from types import SimpleNamespace
        from datetime import datetime, timezone
        from app.telegram import Telegram
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db.sqlite')
            store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
            store.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Notebook', 'notebook'))
            telegram = Telegram(store, Path(directory), None, None)
            message = SimpleNamespace(id=5, raw_text='Notebook em oferta', date=datetime.now(timezone.utc), to_json=lambda: '{}')
            await telegram.receive(SimpleNamespace(chat_id=99, message=message))
            self.assertEqual(store.rows('SELECT * FROM offers'), [])
            await telegram.receive(SimpleNamespace(chat_id=-100123, message=message))
            self.assertEqual(store.rows('SELECT url FROM offers'), [{'url': 'https://t.me/c/123/5'}])
            self.assertEqual(len(store.rows('SELECT * FROM hits')), 1)
            message.raw_text = 'Outro produto'
            await telegram.receive(SimpleNamespace(chat_id=-100123, message=message))
            self.assertEqual(len(store.rows('SELECT * FROM offers')), 1)
            self.assertEqual(store.rows('SELECT * FROM hits'), [])

    async def test_two_factor_login_and_clear_temporary_credentials(self):
        from app.telegram import Telegram
        from telethon import errors
        with tempfile.TemporaryDirectory() as directory:
            telegram = Telegram(None, Path(directory), None, None)
            telegram.client = AsyncMock()
            telegram.phone, telegram.code_hash = '+5511999999999', 'hash'
            telegram.client.sign_in.side_effect = [errors.SessionPasswordNeededError(None), None]
            await telegram.login('12345', 'password')
            telegram.client.sign_in.assert_awaited_with(password='password')
            self.assertIsNone(telegram.phone)
            self.assertIsNone(telegram.code_hash)

    async def test_two_factor_retry_does_not_resubmit_accepted_code(self):
        from app.telegram import Telegram
        from telethon import errors
        with tempfile.TemporaryDirectory() as directory:
            telegram = Telegram(None, Path(directory), None, None)
            telegram.client = AsyncMock()
            telegram.phone, telegram.code_hash = '+5511999999999', 'hash'
            telegram.client.sign_in.side_effect = [
                errors.SessionPasswordNeededError(None),
                errors.PasswordHashInvalidError(None), None,
            ]
            self.assertFalse(await telegram.login('12345', ''))
            self.assertTrue(telegram.needs_password)
            with self.assertRaises(errors.PasswordHashInvalidError):
                await telegram.login('', 'wrong')
            self.assertTrue(telegram.needs_password)
            self.assertTrue(await telegram.login('', 'correct'))
            self.assertEqual(telegram.client.sign_in.await_args_list[1].kwargs, {'password': 'wrong'})
            self.assertEqual(telegram.client.sign_in.await_args_list[2].kwargs, {'password': 'correct'})
            self.assertIsNone(telegram.phone)
            self.assertFalse(telegram.needs_password)


if __name__ == '__main__':
    unittest.main()
