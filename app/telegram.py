import asyncio
import logging

from telethon import TelegramClient, events, errors

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self, store, data_dir, api_id, api_hash):
        self.store = store
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

    async def receive(self, event):
        try:
            message = event.message
            chat_id = event.chat_id
            # Only selected chats are stored; private conversations never enter the database.
            if not self.store.rows('SELECT id FROM chats WHERE id=?', (chat_id,)):
                return
            url = f'https://t.me/c/{str(chat_id)[4:]}/{message.id}' if str(chat_id).startswith('-100') else None
            self.store.ingest(chat_id, message.id, message.raw_text,
                              message.date.isoformat(), url)
        except Exception:
            log.exception('Failed to process a Telegram message')
