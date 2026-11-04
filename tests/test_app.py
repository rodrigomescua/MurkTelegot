import os
import tempfile
import unittest
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


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(?,?)', (-100123, 'Ofertas'))
        self.store.execute('INSERT INTO rules VALUES(1,?,?)', ('Café', 'café'))

    def ingest(self, chat=-100123, body='Café barato'):
        self.store.ingest(chat, 1, body, '2026-11-04T12:00:00+00:00', None)

    def test_only_selected_chats_and_nonempty_messages(self):
        self.ingest(chat=42)
        self.ingest(body='')
        self.assertEqual(self.store.rows('SELECT * FROM offers'), [])

    def test_duplicate_edit_and_matching_are_atomic(self):
        self.ingest()
        self.ingest()
        self.assertEqual(len(self.store.rows('SELECT * FROM offers')), 1)
        self.assertEqual(len(self.store.rows('SELECT * FROM hits')), 1)
        self.ingest(body='Outro produto')
        self.assertEqual(self.store.rows('SELECT * FROM hits'), [])
        reopened = Store(self.store.path)
        self.assertEqual(reopened.rows('SELECT body FROM offers')[0]['body'], 'Outro produto')


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
        self.assertEqual(main.store.rows('SELECT name FROM rules'), [{'name': 'Café'}])

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
            initial = self.client.get('/', cookies=self.auth)
            self.assertNotIn('name="code"', initial.text)
            response = self.client.post('/telegram/code', cookies=self.auth,
                headers={'Accept': 'application/json'},
                data={'csrf': main.csrf_token, 'phone': '+5511999999999'})
            self.assertEqual(response.status_code, 200)
            html = response.json()['html']
            self.assertIn('value="+5511999999999"', html)
            self.assertIn('name="code"', html)
            self.assertNotIn('private-hash', response.text)
            self.assertIn('value="+5511999999999"', self.client.get('/', cookies=self.auth).text)
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
