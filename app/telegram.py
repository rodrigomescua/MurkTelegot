import asyncio
import logging
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from app.gotify import gotify_message, send_gotify
from app.messages import media_info, message_link, source_data

from telethon import TelegramClient, events, errors, utils

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self, store, data_dir, api_id, api_hash):
        self.store = store
        self.media_dir = Path(data_dir) / 'media'
        self.media_slots = asyncio.Semaphore(2)
        self.notification_slots = asyncio.Semaphore(4)
        self.client = TelegramClient(str(data_dir / 'telegram'), int(api_id), api_hash) if api_id and api_hash else None
        self.phone = None
        self.code_hash = None
        self.needs_password = False
        self.lock = asyncio.Lock()
        self.error = None
        self.task = None
        if self.client:
            self.client.add_event_handler(self.receive, events.NewMessage())
            self.client.add_event_handler(self.receive, events.MessageEdited())

    async def start(self):
        if self.client:
            self.task = asyncio.create_task(self.connect())

    async def connect(self):
        try:
            await self.client.connect()
            self.error = None
        except Exception:
            self.error = 'Não foi possível conectar ao Telegram. Reinicie o app para tentar novamente.'
            log.warning('Telegram connection failed; credentials are omitted from logs')

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.client:
            await self.client.disconnect()

    async def authorized(self):
        return bool(self.client and self.client.is_connected() and await self.client.is_user_authorized())

    async def send_code(self, phone):
        if not self.client:
            raise ValueError('Configure TELEGRAM_API_ID e TELEGRAM_API_HASH e reinicie o app.')
        if not self.client.is_connected():
            await self.client.connect()
        result = await self.client.send_code_request(phone)
        self.phone, self.code_hash = phone, result.phone_code_hash
        self.needs_password = False
        self.error = None

    async def login(self, code, password):
        if not self.phone or not self.code_hash:
            raise ValueError('Solicite um novo código primeiro.')
        if self.needs_password:
            if not password:
                raise ValueError('Informe sua senha de verificação em duas etapas.')
            await self.client.sign_in(password=password)
        else:
            try:
                await self.client.sign_in(self.phone, code, phone_code_hash=self.code_hash)
            except errors.SessionPasswordNeededError:
                self.needs_password = True
                if not password:
                    return False
                await self.client.sign_in(password=password)
        self.phone = self.code_hash = None
        self.needs_password = False
        return True

    async def dialogs(self):
        if not await self.authorized():
            return []
        return [{'id': dialog.id, 'title': dialog.name or str(dialog.id)}
                async for dialog in self.client.iter_dialogs() if dialog.is_group or dialog.is_channel]

    def save_message(self, chat_id, message, *, report_alert=False):
        source = json.loads(message.to_json())
        sender = getattr(message, 'sender', None)
        if sender:
            source['_sender_name'] = utils.get_display_name(sender)
        return self.store.ingest(chat_id, message.id, message.raw_text,
                                 message.date.isoformat(), message_link(chat_id, message.id),
                                 source_json=json.dumps(source), report_alert=report_alert)

    async def receive(self, event):
        try:
            # Only selected chats are stored; private conversations never enter the database.
            if not self.store.rows('SELECT id FROM chats WHERE id=?', (event.chat_id,)):
                return
            result = self.save_message(event.chat_id, event.message, report_alert=True)
            await self.notify_alert(result[1] if result else None)
        except Exception:
            log.warning('Failed to store a Telegram message; private content omitted from logs')

    async def notify_alert(self, alert):
        if not alert:
            return
        config = self.store.gotify_settings()
        if not (config['enabled'] and config['url'] and config['token']):
            return
        content = gotify_message(alert)
        async with self.notification_slots:
            sent, detail = await asyncio.to_thread(send_gotify, config['url'], config['token'],
                                           'Novo alerta · ' + alert['chat'], content)
        if not sent:
            log.warning('Falha ao enviar notificação Gotify: %s; alerta mantido no painel', detail)

    async def refresh(self, offer):
        if not await self.authorized():
            raise ValueError('Conecte a conta Telegram para recuperar o original.')
        if not self.store.rows('SELECT id FROM chats WHERE id=?', (offer['chat_id'],)):
            raise ValueError('Selecione este grupo novamente antes de recuperar o original.')
        message = await self.client.get_messages(offer['chat_id'], ids=offer['message_id'])
        if not message or not getattr(message, 'date', None):
            raise ValueError('A mensagem não está mais disponível no Telegram.')
        messages = [message]
        if message.grouped_id:
            neighbors = await self.client.get_messages(offer['chat_id'], ids=list(range(max(1, message.id - 9), message.id + 10)))
            messages = [m for m in neighbors if m and getattr(m, 'grouped_id', None) == message.grouped_id]
            if not any(m.id == message.id for m in messages):
                messages.append(message)
        for item in messages:
            result = self.save_message(offer['chat_id'], item, report_alert=True)
            await self.notify_alert(result[1] if result else None)

    async def download(self, offer, thumbnail=False):
        source = source_data(offer)
        info = media_info(source)
        if not info or info['kind'] == 'unsupported' or (thumbnail and not info['thumbnail']):
            raise ValueError('Esta mídia não pode ser exibida aqui. Abra a mensagem no Telegram.')
        key = hashlib.sha256(f"{offer['chat_id']}:{offer['message_id']}:{info['identity']}:{thumbnail}".encode()).hexdigest()
        self.media_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.media_dir / key
        if path.is_file():
            return path
        async with self.media_slots:
            if path.is_file():
                return path
            if not await self.authorized():
                raise ValueError('Conecte a conta Telegram para carregar esta mídia.')
            message = await self.client.get_messages(offer['chat_id'], ids=offer['message_id'])
            if not message:
                raise ValueError('A mídia não está mais disponível no Telegram.')
            current = media_info(json.loads(message.to_json()))
            if not current or current.get('identity') != info['identity']:
                raise ValueError('A mídia mudou no Telegram. Use Recuperar original para atualizar a oferta.')
            reserve = 64 * 1024 * 1024
            if not thumbnail and info['size'] > shutil.disk_usage(self.media_dir).free - reserve:
                raise ValueError('Espaço insuficiente no servidor para carregar este arquivo.')

            def progress(current, total):
                if shutil.disk_usage(self.media_dir).free < reserve:
                    raise OSError('Media cache disk reserve reached')

            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.media_dir, prefix='.download-', delete=False) as output:
                    temporary = Path(output.name)
                    async with asyncio.timeout(120):
                        downloaded = await self.client.download_media(message, file=output,
                            thumb=-1 if thumbnail else None, progress_callback=progress)
                if downloaded is None or temporary.stat().st_size == 0:
                    raise ValueError('Não foi possível carregar esta mídia. Abra no Telegram ou tente novamente.')
                os.replace(temporary, path)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
            return path
