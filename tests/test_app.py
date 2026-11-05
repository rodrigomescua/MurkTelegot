import os
import hashlib
import hmac
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.store import Store, matches

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
        self.store.execute('INSERT INTO rules VALUES(1,?,?)', ('Café', 'café'))

    def ingest(self, chat=-100123, body='Café barato'):
        self.store.ingest(chat, 1, body, '2026-11-04T12:00:00+00:00', None)

    def test_media_signing_key_persists_in_settings(self):
        key = self.store.media_signing_key()
        self.assertEqual(Store(self.store.path).media_signing_key(), key)

    def test_only_selected_chats_and_nonempty_messages(self):
        self.ingest(chat=42)
        self.ingest(body='')
        self.assertEqual(self.store.rows('SELECT * FROM offers'), [])

    def test_expiry_uses_offer_date_and_preserves_alert_albums(self):
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
        self.store.expire_offers(now)
        self.assertEqual({r['message_id'] for r in self.store.rows('SELECT message_id FROM offers')},
                         {11, 13, 14, 17, 18})

    def test_duplicate_edit_and_matching_are_atomic(self):
        self.ingest()
        self.ingest()
        self.assertEqual(len(self.store.rows('SELECT * FROM offers')), 1)
        self.assertEqual(len(self.store.rows('SELECT * FROM hits')), 1)
        self.ingest(body='Outro produto')
        self.assertEqual(self.store.rows('SELECT * FROM hits'), [])
        reopened = Store(self.store.path)
        self.assertEqual(reopened.rows('SELECT body FROM offers')[0]['body'], 'Outro produto')

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
        count = self.store.add_rule('Notebook', 'notebook')
        self.assertEqual(count, 3)
        self.assertEqual({row['offer_id'] for row in self.store.rows(
            'SELECT h.offer_id FROM hits h JOIN rules r ON r.id=h.rule_id WHERE r.name=?', ('Notebook',))},
            {row['id'] for row in self.store.rows('SELECT id FROM offers WHERE message_id IN (10,11,12)')})
        self.assertEqual(self.store.rows('SELECT seen FROM offers WHERE message_id IN (10,11)'),
                         [{'seen': 0}, {'seen': 0}])
        self.assertEqual(len(self.store.feed(alerts=True)), 3)

    def test_add_rule_notifies_each_matching_album_once(self):
        self.store.ingest(-100123, 10, 'Café já alertado', '2026-11-04T12:00:00+00:00', None,
                          source_json='{"grouped_id": 50}')
        self.store.ingest(-100123, 11, 'Notebook no mesmo álbum', '2026-11-04T12:00:01+00:00', None,
                          source_json='{"grouped_id": 50}')
        self.store.ingest(-100123, 12, 'Notebook novo', '2026-11-04T12:00:02+00:00', None)
        matched, alerts = self.store.add_rule('Notebook', 'notebook', return_alerts=True)
        self.assertEqual(matched, 2)
        self.assertEqual([alert['body'] for alert in alerts], ['Notebook no mesmo álbum', 'Notebook novo'])


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
        self.assertEqual(self.client.post('/rules', cookies=self.auth, data={'name': 'x', 'keywords': 'x'}).status_code, 403)

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
        self.assertEqual(self.client.post('/rules', cookies=self.auth, headers=headers, data={'name': 'x', 'keywords': 'x'}).status_code, 403)
        invalid = self.client.post('/rules', cookies=self.auth, headers=headers, data={'csrf': main.csrf_token, 'name': ' ', 'keywords': 'x'})
        self.assertEqual(invalid.status_code, 400)
        valid = self.client.post('/rules', cookies=self.auth, headers=headers, data={'csrf': main.csrf_token, 'name': 'Café', 'keywords': 'café'})
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
                data={'csrf': main.csrf_token, 'name': 'Notebook', 'keywords': 'notebook'})
        self.assertEqual(response.json()['matched'], 2)
        notify.assert_awaited_once()
        self.assertEqual(notify.await_args.args[0]['body'], 'Notebook capa')
        self.assertNotIn('token', response.text)
        self.assertIn('Notebook', self.client.get('/alerts', cookies=self.auth).text)
        self.assertEqual(main.store.unread(), 1)

    def test_rule_management_has_own_page(self):
        home = self.client.get('/', cookies=self.auth)
        self.assertNotIn('id="rules-list"', home.text)
        self.assertNotIn('id="quick-rule"', home.text)
        page = self.client.get('/rules-page', cookies=self.auth)
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="rules-list"', page.text)
        self.assertEqual(self.client.get('/rules-page', follow_redirects=False).status_code, 303)

    def test_alert_offer_deletion_is_confirmed_authenticated_and_album_wide(self):
        import json
        main.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Grupo',))
        main.store.execute('INSERT INTO rules VALUES(1,?,?)', ('Notebook', 'notebook'))
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
        self.assertIn('action="/offers/1/delete"', home.text)
        self.assertNotIn('id="telegram-panel"', home.text)
        telegram_page = self.client.get('/telegram', cookies=self.auth)
        self.assertIn('id="telegram-panel"', telegram_page.text)
        self.assertIn('action="/offers/3/delete"', home.text)
        self.assertEqual(self.client.post('/offers/3/delete', cookies=self.auth,
            data={'csrf': main.csrf_token, 'alerts': 'false'}, follow_redirects=False).headers['location'], '/?notice=Oferta+removida.&q=')
        self.assertEqual(self.client.post('/offers/1/delete', data={'csrf': main.csrf_token},
                                          follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/offers/1/delete', cookies=self.auth,
            data={'csrf': main.csrf_token, 'q': 'Notebook'}, follow_redirects=False).status_code, 303)
        self.assertEqual(main.store.rows('SELECT message_id FROM offers'), [])
        self.assertEqual(main.store.rows('SELECT * FROM hits'), [])
        self.assertEqual(self.post('/offers/1/delete').status_code, 404)

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
            self.assertEqual(self.client.get(path.replace(signature, 'bad')).status_code, 404)
            expired = int(time.time()) - 1
            expired_identity = f"{offer['chat_id']}:{offer['message_id']}:{expired}"
            expired_signature = hmac.new(main.store.media_signing_key().encode(), expired_identity.encode(), hashlib.sha256).hexdigest()
            self.assertEqual(self.client.get(f"/public-media/{offer['id']}/{expired}/{expired_signature}").status_code, 404)
            future = int(time.time()) + 24 * 60 * 60 + 60
            future_identity = f"{offer['chat_id']}:{offer['message_id']}:{future}"
            future_signature = hmac.new(main.store.media_signing_key().encode(), future_identity.encode(), hashlib.sha256).hexdigest()
            self.assertEqual(self.client.get(f"/public-media/{offer['id']}/{future}/{future_signature}").status_code, 404)

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
        self.assertEqual(self.post('/rules', {'name': 'Café', 'keywords': 'café'}).status_code, 200)
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
        main.store.execute('INSERT INTO rules VALUES(1,?,?)', ('Notebook', 'notebook'))
        main.store.add_ignored('PS5')
        first = main.store.ingest(1, 1, 'Notebook PS5', '2026-11-04', None)
        second = main.store.ingest(1, 2, 'Notebook lido', '2026-11-04', None)
        main.store.mark_seen(second)
        page = self.client.get('/alerts', cookies=self.auth)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Não lidos · 1', page.text)
        self.assertIn('Lidos · 1', page.text)
        self.assertIn('Notebook PS5', page.text)
        self.assertIn('data-mark-seen', page.text)
        self.assertNotIn('Notebook PS5', self.client.get('/', cookies=self.auth).text)
        self.assertEqual(self.client.post(f'/offers/{first}/seen', cookies=self.auth, headers={'Accept': 'application/json'}).status_code, 403)
        response = self.client.post(f'/offers/{first}/seen', cookies=self.auth, headers={'Accept': 'application/json'}, data={'csrf': main.csrf_token})
        self.assertTrue(response.json()['ok'])
        updated = self.client.get('/alerts', cookies=self.auth).text
        self.assertIn('Não lidos · 0', updated)
        self.assertIn('Lidos · 2', updated)
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
    async def test_event_ingestion_ignores_private_and_handles_edits(self):
        from types import SimpleNamespace
        from datetime import datetime, timezone
        from app.telegram import Telegram
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db.sqlite')
            store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
            store.execute('INSERT INTO rules VALUES(1,?,?)', ('Notebook', 'notebook'))
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
