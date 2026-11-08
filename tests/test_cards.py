import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.messages import preview_lines
from app.store import Store

_runtime = tempfile.TemporaryDirectory()
os.environ.update(DATA_DIR=_runtime.name, APP_PASSWORD='test-password-with-32-characters',
                  TELEGRAM_API_ID='', TELEGRAM_API_HASH='')
from app import main


class OfferCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'offers.db')
        self.store.execute('INSERT INTO chats VALUES(-100123,?)', ('Ofertas',))
        self.patch = patch.object(main, 'store', self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(main.app)
        self.auth = {'panel_session': 'test-session'}
        main.sessions['test-session'] = __import__('time').monotonic() + 60

    def add(self, message_id, text, source):
        return self.store.ingest(-100123, message_id, text, '2026-11-04',
                                 f'https://t.me/c/123/{message_id}', source_json=json.dumps(source))

    def test_preview_skips_blank_lines_and_reads_across_album_parts(self):
        self.assertEqual(preview_lines([{'body': '\n  \nPrimeira  \n\t\n Segunda\nTerceira'},
                                        {'body': 'Outra'}]), ['Primeira', 'Segunda'])
        self.assertEqual(preview_lines([{'body': '\n '}, {'body': 'Álbum\n\nLegenda'}]), ['Álbum', 'Legenda'])
        self.assertEqual(preview_lines([{'body': '\n\t\n'}]), [])

    def test_preview_masks_spoiler_after_emoji_without_losing_other_text(self):
        body = '😀 segredo\nOferta visível'
        source = {'entities': [{'_': 'MessageEntitySpoiler', 'offset': 3, 'length': 7}]}
        self.assertEqual(preview_lines([{'body': body, 'source_json': json.dumps(source)}]),
                         ['😀 •••••••', 'Oferta visível'])

    def test_album_card_uses_first_photo_and_expands_full_message(self):
        source1 = {'grouped_id': 50, 'media': {'_': 'MessageMediaPhoto', 'photo': {'_': 'Photo', 'id': 12}}}
        source2 = {'grouped_id': 50}
        self.add(1, '\n \n', source1)
        self.add(2, '\nPrimeira linha\n\nSegunda linha\nTerceira linha', source2)
        response = self.client.get('/', cookies=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count('class="offer-card"'), 1)
        summary = re.search(r'<summary class="offer-summary">(.*?)</summary>', response.text, re.S).group(1)
        self.assertIn('src="/offers/1/media"', summary)
        self.assertIn('<span>Primeira linha</span>', summary)
        self.assertIn('<span>Segunda linha</span>', summary)
        self.assertNotIn('Terceira linha', summary)
        self.assertIn('Terceira linha', response.text)
        self.assertIn('2 mensagens', summary)
        self.assertIn('data-delete-offer', response.text)
        self.assertIn('Abrir no Telegram', response.text)
        self.assertIn('offer-card-actions', response.text)
        self.assertIn('Excluir', response.text)

    def test_spoiler_photo_is_not_requested_in_cover_and_text_is_masked(self):
        body = 'Oferta secreta'
        source = {'media': {'_': 'MessageMediaPhoto', 'photo': {'_': 'Photo', 'id': 1}, 'spoiler': True},
                  'entities': [{'_': 'MessageEntitySpoiler', 'offset': 7, 'length': 7}]}
        self.add(1, body, source)
        response = self.client.get('/', cookies=self.auth)
        summary = re.search(r'<summary class="offer-summary">(.*?)</summary>', response.text, re.S).group(1)
        self.assertIn('Mídia com spoiler', summary)
        self.assertNotIn('/offers/1/media', summary)
        self.assertNotIn('secreta', summary)
        self.assertIn('Oferta •••••••', summary)
        self.assertIn('class="spoiler"', response.text)

    def test_no_image_uses_placeholder_and_is_accessible(self):
        self.add(1, 'Só texto', {'_': 'Message'})
        response = self.client.get('/', cookies=self.auth)
        self.assertIn('Sem imagem', response.text)
        self.assertIn('<details class="offer-detail">', response.text)
        summary = re.search(r'<summary class="offer-summary">(.*?)</summary>', response.text, re.S).group(1)
        self.assertIn('class="offer-cover"', summary)
        self.assertIn('class="offer-overview"', summary)
        self.assertNotIn('Ver oferta completa', response.text)

    def test_deleted_page_renders_non_spoiler_cover_and_keeps_placeholders(self):
        image_id = self.add(1, 'Oferta removida com imagem', {
            'media': {'_': 'MessageMediaPhoto', 'photo': {'_': 'Photo', 'id': 12}}})
        no_image_id = self.add(2, 'Oferta removida sem imagem', {'_': 'Message'})
        spoiler_id = self.add(3, 'Oferta removida com spoiler', {
            'media': {'_': 'MessageMediaPhoto', 'photo': {'_': 'Photo', 'id': 13}, 'spoiler': True}})
        for offer_id in (image_id, no_image_id, spoiler_id):
            self.store.execute('UPDATE offers SET deleted_at=? WHERE id=?', ('2026-11-04T00:00:00+00:00', offer_id))

        response = self.client.get('/deleted', cookies=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-date-only', response.text)
        self.assertIn('>2026-11-04</time>', response.text)
        self.assertNotIn('exclusão física prevista', response.text)
        image_card = re.search(r'<article class="offer-card" id="offer-%s">(.*?)</article>' % image_id,
                               response.text, re.S).group(1)
        self.assertIn(f'src="/offers/{image_id}/media"', image_card)
        no_image_card = re.search(r'<article class="offer-card" id="offer-%s">(.*?)</article>' % no_image_id,
                                  response.text, re.S).group(1)
        self.assertIn('Sem imagem', no_image_card)
        spoiler_card = re.search(r'<article class="offer-card" id="offer-%s">(.*?)</article>' % spoiler_id,
                                 response.text, re.S).group(1)
        spoiler_summary = re.search(r'<summary class="offer-summary">(.*?)</summary>', spoiler_card, re.S).group(1)
        self.assertIn('Mídia com spoiler', spoiler_card)
        self.assertNotIn(f'src="/offers/{spoiler_id}/media"', spoiler_summary)
