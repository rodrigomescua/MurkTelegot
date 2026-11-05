import json
import hashlib
import hmac
import socket
import ssl
import urllib.error
import urllib.request
from unittest.mock import Mock
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from app.gotify import gotify_message, send_gotify, validate_gotify_token, validate_gotify_url
from app.store import Store
from app.telegram import Telegram

_runtime = tempfile.TemporaryDirectory()
os.environ.update(DATA_DIR=_runtime.name, APP_PASSWORD='test-password-with-32-characters')
from app import main


class GotifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite')

    def test_validation_and_settings_persist_without_exposing_token(self):
        for url in ('ftp://gotify.local', 'http://user:secret@host', 'http://host?token=secret', 'http://host:99999', 'http://host\nheader'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_gotify_url(url)
        with self.assertRaises(ValueError):
            validate_gotify_token('bad\nheader')
        self.assertEqual(validate_gotify_url('http://gotify.local/base/'), 'http://gotify.local/base')
        with patch.object(main, 'store', self.store):
            client = TestClient(main.app)
            session = 'test-gotify-settings'
            main.sessions[session] = time.monotonic() + 60
            self.addCleanup(main.sessions.pop, session, None)
            cookies = {'panel_session': session}
            self.assertEqual(client.get('/settings', follow_redirects=False).status_code, 303)
            self.assertEqual(client.post('/settings/gotify', cookies=cookies, data={'url':'http://gotify', 'token':'secret-test', 'enabled':'true'}).status_code, 403)
            saved = client.post('/settings/gotify', cookies=cookies, follow_redirects=False, data={
                'csrf': main.csrf_token, 'url': 'http://gotify/base/', 'token': 'secret-test', 'enabled': 'true'})
            self.assertEqual(saved.status_code, 303)
            self.assertNotIn('secret-test', saved.headers['location'])
            page = client.get('/settings', cookies=cookies)
            self.assertNotIn('secret-test', page.text)
            self.assertIn('Token configurado', page.text)
            self.assertTrue(Store(self.store.path).gotify_settings()['enabled'])
            rejected = client.post('/settings/gotify', cookies=cookies, follow_redirects=False, data={
                'csrf': main.csrf_token, 'url': 'http://user:secret@gotify', 'enabled': 'true'})
            self.assertNotIn('secret', rejected.headers['location'])
            self.assertEqual(self.store.gotify_settings()['url'], 'http://gotify/base')
            self.assertEqual(client.post('/settings/gotify/test', cookies=cookies).status_code, 403)
            with patch('app.main.send_gotify', return_value=(True, '')) as send:
                tested = client.post('/settings/gotify/test', cookies=cookies, follow_redirects=False, data={'csrf': main.csrf_token})
                self.assertEqual(tested.status_code, 303)
                send.assert_called_once()
                self.assertNotIn('secret-test', tested.headers['location'])
            client.post('/settings/gotify', cookies=cookies, data={'csrf': main.csrf_token, 'url':'http://gotify/base'})
            config = self.store.gotify_settings()
            self.assertEqual(config['token'], 'secret-test')
            self.assertFalse(config['enabled'])
            client.post('/settings/gotify/clear', cookies=cookies, data={'csrf': main.csrf_token})
            self.assertEqual(self.store.gotify_settings()['token'], '')

    def test_markdown_formats_utf16_links_and_escapes_untrusted_text(self):
        body = '😀 Café link *literal* <script>'
        source = {'entities': [
            {'_': 'MessageEntityBold', 'offset': 3, 'length': 4},
            {'_': 'MessageEntityTextUrl', 'offset': 8, 'length': 4, 'url': 'https://example.com/a(b)'},
        ]}
        result = gotify_message({'body': body, 'source_json': json.dumps(source), 'url': 'https://t.me/c/123/1'})
        self.assertIn('😀 **Café** [link](https://example.com/a%28b%29)', result)
        self.assertIn(r'\*literal\*', result)
        self.assertIn('&lt;script&gt;', result)
        self.assertIn('[Abrir oferta no Telegram](https://t.me/c/123/1)', result)
        self.assertNotIn('<script>', result)

    def test_markdown_hides_spoilers_and_blocks_unsafe_links(self):
        body = 'segredo clique'
        source = {'entities': [
            {'_': 'MessageEntitySpoiler', 'offset': 0, 'length': 7},
            {'_': 'MessageEntityTextUrl', 'offset': 8, 'length': 6, 'url': 'javascript:alert(1)'},
        ]}
        result = gotify_message({'body': body, 'source_json': json.dumps(source)})
        self.assertNotIn('segredo', result)
        self.assertIn('spoiler oculto', result)
        self.assertIn('clique', result)
        self.assertNotIn('javascript:', result)

    def test_markdown_nested_styles_quotes_and_spoilers(self):
        text = 'Oferta segredo\nDetalhes'
        source = {'entities': [
            {'_': 'MessageEntityBold', 'offset': 0, 'length': 13},
            {'_': 'MessageEntityItalic', 'offset': 0, 'length': 6},
            {'_': 'MessageEntitySpoiler', 'offset': 7, 'length': 7},
            {'_': 'MessageEntityBlockquote', 'offset': 15, 'length': 8},
        ]}
        result = gotify_message({'body': text, 'source_json': json.dumps(source)})
        self.assertIn('*Oferta*', result)
        self.assertTrue(result.startswith('**'))
        self.assertIn('spoiler oculto', result)
        self.assertNotIn('segredo', result)
        self.assertIn('> Detalhes', result)
        inline = gotify_message({'body': 'a`b', 'source_json': json.dumps({'entities': [{'_':'MessageEntityCode', 'offset':0, 'length':3}]})})
        self.assertEqual(inline, '`` a`b ``')

    def test_markdown_pre_code_strike_and_spoiler_media(self):
        source = {'entities': [{'_': 'MessageEntityPre', 'offset': 0, 'length': 5}],
                  'media': {'_': 'MessageMediaPhoto', 'photo': {'_': 'Photo', 'id': 1}, 'spoiler': True}}
        result = gotify_message({'body': 'a`bcd', 'source_json': json.dumps(source)})
        self.assertTrue(result.startswith('```\na`bcd\n```'))
        self.assertIn('Mídia disponível no Telegram', result)
        strike = gotify_message({'body': 'oferta', 'source_json': json.dumps({'entities': [{'_':'MessageEntityStrike', 'offset':0, 'length':6}]})})
        self.assertEqual(strike, '~~oferta~~')

    def test_old_database_adds_settings_without_changing_offers(self):
        self.store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
        self.store.ingest(1, 1, 'Oferta', '2026-11-04', None)
        self.store.execute('DROP TABLE settings')
        before = self.store.rows('SELECT * FROM offers')
        reopened = Store(self.store.path)
        self.assertEqual(reopened.rows('SELECT * FROM offers'), before)
        self.assertEqual(reopened.gotify_settings(), {'url': '', 'token': '', 'enabled': False})

    def test_failures_classified_without_leaking_server_details(self):
        cases = [
            (urllib.error.HTTPError('http://secret-test', 401, 'secret-test', {}, None), 'HTTP 401'),
            (urllib.error.HTTPError('http://secret-test', 403, 'secret-test', {}, None), 'HTTP 403'),
            (urllib.error.HTTPError('http://secret-test', 404, 'secret-test', {}, None), 'HTTP 404'),
            (urllib.error.HTTPError('http://secret-test', 502, 'secret-test', {}, None), 'HTTP 502'),
            (urllib.error.URLError(socket.gaierror(-2, 'secret-test')), 'DNS'),
            (urllib.error.URLError(ConnectionRefusedError(111, 'secret-test')), 'recusada'),
            (urllib.error.URLError(TimeoutError('secret-test')), 'esgotado'),
            (urllib.error.URLError(ssl.SSLCertVerificationError('secret-test')), 'Certificado HTTPS'),
            (urllib.error.URLError(ssl.SSLError('secret-test')), 'TLS'),
            (urllib.error.URLError('secret-test'), 'Falha na comunicação'),
        ]
        for exc, expected in cases:
            with self.subTest(expected=expected), patch('app.gotify.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = exc
                ok, detail = send_gotify('https://host', 'secret-test', 'private-text', 'secret-test')
                self.assertFalse(ok)
                self.assertIn(expected, detail)
                self.assertNotIn('secret-test', detail)
                self.assertNotIn('private-text', detail)

    def test_diagnostics_visible_persistently_and_logged_without_token(self):
        self.store.save_gotify('http://gotify', 'secret-test', True)
        with patch.object(main, 'store', self.store):
            client = TestClient(main.app)
            session = 'test-gotify-error'
            main.sessions[session] = time.monotonic() + 60
            self.addCleanup(main.sessions.pop, session, None)
            cookies = {'panel_session': session}
            with patch('app.main.send_gotify', return_value=(False, 'O servidor retornou HTTP 401. Confira o token.')):
                with self.assertLogs('app.main', level='WARNING') as logs:
                    response = client.post('/settings/gotify/test', cookies=cookies, follow_redirects=False,
                                           data={'csrf': main.csrf_token})
                page = client.get(response.headers['location'], cookies=cookies)
                self.assertIn('HTTP 401', page.text)
                self.assertIn('role="alert"', page.text)
                self.assertNotIn('data-toast>Não foi possível', page.text)
                self.assertIn('HTTP 401', '\n'.join(logs.output))
                self.assertNotIn('secret-test', response.headers['location'] + page.text + '\n'.join(logs.output))

    def test_cloudflare_style_user_agent_restriction(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                allowed = self.headers.get('User-Agent') == 'Mozilla/5.0 (compatible; MurkTelegot/1.0)'
                self.send_response(200 if allowed else 403)
                self.end_headers()
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        request = urllib.request.Request(url + '/message', data=b'{}', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 403)
        self.assertEqual(send_gotify(url, 'test-token', 'Título', 'Oferta'), (True, ''))

    def test_http_protocol_and_redirect_does_not_forward_token(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.headers.get('X-Gotify-Key'), self.headers.get('User-Agent'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(302 if self.path == '/redirect/message' else 200)
                if self.path == '/redirect/message':
                    self.send_header('Location', '/other')
                self.end_headers()
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        self.assertEqual(send_gotify(url + '/base', 'test-token', 'Título', 'Oferta'), (True, ''))
        self.assertEqual(received[0], ('/base/message', 'test-token', 'Mozilla/5.0 (compatible; MurkTelegot/1.0)', {'title': 'Título', 'message': 'Oferta', 'priority': 5, 'extras': {'client::display': {'contentType': 'text/markdown'}}}))
        image_url = 'https://panel.example/public-media/1/123/signature'
        self.assertEqual(send_gotify(url + '/base', 'test-token', 'Título', 'Oferta', image_url), (True, ''))
        self.assertEqual(received[1][3]['extras']['client::notification']['bigImageUrl'], image_url)
        self.assertIn('HTTP 302', send_gotify(url + '/redirect', 'test-token', 'Título', 'Oferta')[1])
        self.assertEqual(len(received), 3)


class GotifyEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_album_notification_uses_image_from_any_non_spoiler_part(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db.sqlite')
            store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
            store.ingest(1, 1, 'Oferta com texto', '2026-11-04T12:00:00+00:00', None,
                         source_json=json.dumps({'grouped_id': 7}))
            store.ingest(1, 2, '', '2026-11-04T12:00:01+00:00', None,
                         source_json=json.dumps({'grouped_id': 7, 'media': {'photo': {'_': 'Photo', 'id': 99}}}))
            store.save_gotify('http://gotify', 'test-token', True)
            alert = {'offer_id': 1, 'chat_id': 1, 'message_id': 1, 'grouped_id': '7', 'chat': 'Grupo',
                     'body': 'Oferta com texto', 'source_json': json.dumps({'grouped_id': 7}), 'url': None}
            telegram = Telegram(store, Path(directory), None, None)
            with patch.dict(os.environ, {'APP_PUBLIC_URL': 'https://panel.example'}), \
                 patch('app.telegram.send_gotify', return_value=(True, '')) as send:
                await telegram.notify_alert(alert)
            image_url = send.call_args.kwargs['image_url']
            self.assertIn('/public-media/2/', image_url)

    async def test_notification_uses_signed_image_url_except_for_spoilers(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db.sqlite')
            store.save_gotify('http://gotify', 'test-token', True)
            telegram = Telegram(store, Path(directory), None, None)
            alert = {'offer_id': 8, 'chat_id': 1, 'message_id': 17, 'chat': 'Grupo', 'body': 'Oferta', 'url': None,
                     'source_json': json.dumps({'media': {'photo': {'_': 'Photo', 'id': 99}}}), 'rules': ['Oferta']}
            with patch.dict(os.environ, {'APP_PUBLIC_URL': 'https://panel.example'}), \
                 patch('app.telegram.send_gotify', return_value=(True, '')) as send:
                await telegram.notify_alert(alert)
                image_url = send.call_args.kwargs['image_url']
                self.assertTrue(image_url.startswith('https://panel.example/public-media/8/'))
                path = urlsplit(image_url).path.split('/')
                expiry, signature = int(path[-2]), path[-1]
                signed = f"1:17:{expiry}"
                expected = hmac.new(store.media_signing_key().encode(), signed.encode(), hashlib.sha256).hexdigest()
                self.assertEqual(signature, expected)
                self.assertIn(image_url, send.call_args.args[3])
                alert['source_json'] = json.dumps({'media': {'photo': {'_': 'Photo', 'id': 99}, 'spoiler': True}})
                await telegram.notify_alert(alert)
                self.assertEqual(send.call_args.kwargs['image_url'], '')

    async def test_new_alert_edit_album_and_ignored_offers(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db.sqlite')
            store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
            store.execute('INSERT INTO rules VALUES(1,?,?)', ('Notebook', 'notebook'))
            store.add_ignored('PS5')
            store.save_gotify('http://gotify', 'test-token', True)
            telegram = Telegram(store, Path(directory), None, None)
            def event(mid, body, group=None, chat=1):
                message = SimpleNamespace(id=mid, raw_text=body, date=datetime.now(timezone.utc),
                                          to_json=lambda: json.dumps({'grouped_id': group, 'entities': [{'_': 'MessageEntityBold', 'offset': 0, 'length': 8}]}))
                return SimpleNamespace(chat_id=chat, message=message)
            with patch('app.telegram.send_gotify', return_value=(True, '')) as send:
                await telegram.receive(event(1, 'Notebook PS5', group=9))
                await telegram.receive(event(1, 'Notebook PS5', group=9))
                await telegram.receive(event(2, 'Notebook PS5', group=9))
                await telegram.receive(event(3, 'Outros produtos'))
                await telegram.receive(event(3, 'Notebook editado'))
                await telegram.receive(event(4, 'Notebook', chat=999))
                self.assertEqual(send.call_count, 2)
                self.assertIn('**Notebook** PS5', send.call_args_list[0].args[3])
                self.assertEqual(len(store.feed()), 1)
                self.assertEqual(store.unread(), 2)

    async def test_refresh_also_sends_new_alert_once(self):
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db.sqlite')
            store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
            store.execute('INSERT INTO rules VALUES(1,?,?)', ('Notebook', 'notebook'))
            store.save_gotify('http://gotify', 'test-token', True)
            store.ingest(1, 1, 'Sem correspondência', '2026-11-04', None)
            telegram = Telegram(store, Path(directory), None, None)
            telegram.authorized = AsyncMock(return_value=True)
            message = SimpleNamespace(id=1, raw_text='Notebook atualizado', date=datetime.now(timezone.utc),
                                      grouped_id=None, to_json=lambda: '{}')
            telegram.client = SimpleNamespace(get_messages=AsyncMock(return_value=message))
            offer = store.rows('SELECT * FROM offers')[0]
            with patch('app.telegram.send_gotify', return_value=(True, '')) as send:
                await telegram.refresh(offer)
                await telegram.refresh(offer)
                send.assert_called_once()
                self.assertEqual(store.unread(), 1)

    async def test_failure_does_not_lose_alert_and_disabled_does_not_send(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db.sqlite')
            store.execute('INSERT INTO chats VALUES(1,?)', ('Grupo',))
            store.execute('INSERT INTO rules VALUES(1,?,?)', ('Notebook', 'notebook'))
            telegram = Telegram(store, Path(directory), None, None)
            def event(mid):
                message = SimpleNamespace(id=mid, raw_text='Notebook', date=datetime.now(timezone.utc), to_json=lambda: '{}')
                return SimpleNamespace(chat_id=1, message=message)
            with patch('app.telegram.send_gotify', return_value=(False, 'Conexão recusada.')) as send:
                await telegram.receive(event(1))
                send.assert_not_called()
                store.save_gotify('http://gotify', 'test-token', True)
                with self.assertLogs('app.telegram', level='WARNING') as logs:
                    await telegram.receive(event(2))
                self.assertIn('Conexão recusada.', logs.output[0])
                self.assertNotIn('test-token', logs.output[0])
                send.assert_called_once()
                self.assertEqual(store.unread(), 2)
