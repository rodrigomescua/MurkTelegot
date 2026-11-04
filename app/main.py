import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from telethon import errors

from app.messages import media_info, present, preview_lines, source_data
from app.store import Store
from app.telegram import Telegram

logging.basicConfig(level=logging.INFO)
os.umask(0o077)
data_dir = Path(os.getenv('DATA_DIR', '/data'))
data_dir.mkdir(parents=True, exist_ok=True)
os.chmod(data_dir, 0o700)
password = os.environ.get('APP_PASSWORD', '')
if len(password) < 12 or password == 'SUBSTITUA-POR-UMA-SENHA-ALEATORIA-LONGA':
    raise RuntimeError('Set APP_PASSWORD to a unique password with at least 12 characters')
store = Store(data_dir / 'offers.db')
telegram = Telegram(store, data_dir, os.getenv('TELEGRAM_API_ID'), os.getenv('TELEGRAM_API_HASH'))
csrf_token = secrets.token_urlsafe(32)
security = HTTPBasic()


def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    user_ok = secrets.compare_digest(credentials.username.encode(), os.getenv('APP_USER', 'admin').encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), password.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(401, 'Credenciais inválidas', headers={'WWW-Authenticate': 'Basic'})


async def csrf(request: Request):
    form = await request.form()
    if not secrets.compare_digest(str(form.get('csrf', '')), csrf_token):
        raise HTTPException(403, 'Formulário expirado. Recarregue a página.')


@asynccontextmanager
async def lifespan(app):
    await telegram.start()
    yield
    await telegram.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount('/static', StaticFiles(directory='app/static'), name='static')
app.mount('/brand', StaticFiles(directory='assets/murktelegot-logo'), name='brand')
templates = Jinja2Templates(directory='app/templates')


@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/health')
async def health():
    return {'status': 'ok'}


@app.get('/', dependencies=[Depends(authenticate)])
async def dashboard(request: Request, alerts: bool = False, q: str = '', notice: str = ''):
    with store.connect() as db:
        db.execute('BEGIN')
        marker = db.execute('SELECT coalesce(max(id), 0) FROM offers').fetchone()[0]
        offers = store.feed(q, alerts, db)
    for offer in offers:
        offer['parts'] = [present(part) for part in offer['parts']]
        offer['preview_lines'] = preview_lines(offer['parts'])
        offer['cover'] = next((part for part in offer['parts'] if part['media'] and
                               (part['media']['kind'] == 'photo' or part['media'].get('thumbnail'))), None)
    return templates.TemplateResponse(request, 'index.html', {
        'csrf': csrf_token, 'authorized': await telegram.authorized(),
        'configured': bool(telegram.client), 'connection_error': telegram.error,
        'phone': telegram.phone or '', 'code_pending': bool(telegram.code_hash),
        'needs_password': telegram.needs_password,
        'chats': store.rows('SELECT * FROM chats ORDER BY title'),
        'rules': store.rows('SELECT * FROM rules ORDER BY id DESC'),
        'ignored_words': store.rows('SELECT id,word FROM ignored_keywords ORDER BY word COLLATE NOCASE'),
        'offers': offers, 'marker': marker,
        'unread': store.unread(),
        'alerts': alerts, 'q': q, 'notice': notice,
    })


@app.get('/offers/new', dependencies=[Depends(authenticate)])
async def new_offers(after: int = 0, q: str = '', alerts: bool = False):
    if after < 0 or len(q) > 200:
        raise HTTPException(400, 'Filtro inválido.')
    return {'count': store.new_offers(after, q, alerts)}


def redirect(notice='', *, q='', alerts=False, anchor=''):
    from urllib.parse import urlencode
    return RedirectResponse('/?' + urlencode({'notice': notice, 'q': q, 'alerts': str(alerts).lower()}) + anchor, status_code=303)


@app.post('/telegram/{action}', dependencies=[Depends(authenticate), Depends(csrf)])
async def telegram_action(request: Request, action: str, phone: str = Form('', max_length=30),
                          code: str = Form('', max_length=20), password: str = Form('', max_length=256)):
    async def reply(message, ok=False):
        if 'application/json' not in request.headers.get('accept', ''):
            return redirect(message)
        payload = {'ok': ok, 'message': message}
        if ok:
            payload['connected'] = await telegram.authorized()
            payload['html'] = templates.env.get_template('telegram.html').render(
                csrf=csrf_token, authorized=payload['connected'],
                configured=bool(telegram.client), phone=telegram.phone or '',
                code_pending=bool(telegram.code_hash), needs_password=telegram.needs_password,
                chats=store.rows('SELECT * FROM chats ORDER BY title'),
            )
        return JSONResponse(payload, status_code=200 if ok else 400)

    async with telegram.lock:
        try:
            if await telegram.authorized():
                return await reply('Sua conta já está conectada.', True)
            if action == 'code':
                await telegram.send_code(phone.strip())
                return await reply('Código enviado. Confira a conversa oficial do Telegram e, se necessário, o SMS.', True)
            if action == 'login':
                connected = await telegram.login(code.strip(), password)
                if not connected:
                    return await reply('Código aceito. Agora informe sua senha de verificação em duas etapas.', True)
                return await reply('Conta conectada! Selecione os grupos que deseja acompanhar.', True)
            raise HTTPException(404)
        except ValueError as exc:
            return await reply(str(exc))
        except errors.FloodWaitError as exc:
            return await reply(f'Telegram solicitou aguardar {exc.seconds} segundos antes de tentar novamente.')
        except errors.PhoneNumberInvalidError:
            return await reply('Telefone inválido. Inclua o DDI, por exemplo +5511999999999.')
        except errors.PhoneCodeInvalidError:
            return await reply('Código incorreto. Confira o código mais recente e tente novamente.')
        except errors.PhoneCodeExpiredError:
            return await reply('Código expirado. Use “Reenviar ou alterar telefone” para solicitar outro.')
        except errors.PasswordHashInvalidError:
            return await reply('Senha de duas etapas incorreta. Corrija a senha e tente novamente.')
        except errors.RPCError:
            return await reply('Telegram recusou a operação. Confira seus dados e tente novamente.')
        except (OSError, asyncio.TimeoutError):
            return await reply('Falha de conexão com o Telegram. Seus campos foram mantidos; tente novamente.')


@app.get('/groups', dependencies=[Depends(authenticate)])
async def groups(request: Request):
    try:
        dialogs = await telegram.dialogs()
    except (errors.RPCError, OSError, asyncio.TimeoutError):
        return redirect('Não foi possível listar os grupos. Tente novamente mais tarde.')
    return templates.TemplateResponse(request, 'groups.html', {
        'csrf': csrf_token, 'dialogs': dialogs,
        'selected': [r['id'] for r in store.rows('SELECT id FROM chats')],
    })


@app.post('/groups', dependencies=[Depends(authenticate), Depends(csrf)])
async def save_groups(chat_ids: list[int] = Form(default=[])):
    if not await telegram.authorized():
        return redirect('Conecte a conta Telegram primeiro.')
    try:
        dialogs = await telegram.dialogs()
    except (errors.RPCError, OSError, asyncio.TimeoutError):
        return redirect('Não foi possível atualizar os grupos. Seleção anterior preservada.')
    available = {d['id']: d['title'] for d in dialogs}
    if any(chat_id not in available for chat_id in chat_ids):
        raise HTTPException(400, 'Grupo inválido. Atualize a lista.')
    with store.connect() as db:
        db.execute('DELETE FROM chats')
        db.executemany('INSERT INTO chats VALUES(?,?)', [(i, available[i]) for i in set(chat_ids)])
    return redirect('Grupos atualizados. Novas mensagens serão monitoradas.')


@app.post('/rules', dependencies=[Depends(authenticate), Depends(csrf)])
async def add_rule(name: str = Form(..., max_length=100), keywords: str = Form(..., max_length=1000)):
    if not name.strip() or not any(w.strip() for w in keywords.split(',')):
        return redirect('Informe um nome e pelo menos uma palavra-chave.')
    store.execute('INSERT INTO rules(name, keywords) VALUES(?,?)', (name.strip(), keywords.strip()))
    return redirect('Regra criada. Ela será aplicada às próximas mensagens e edições.')


@app.post('/rules/{rule_id}/delete', dependencies=[Depends(authenticate), Depends(csrf)])
async def delete_rule(rule_id: int):
    with store.connect() as db:
        db.execute('DELETE FROM hits WHERE rule_id=?', (rule_id,))
        db.execute('DELETE FROM rules WHERE id=?', (rule_id,))
    return redirect('Regra removida.')


@app.post('/ignored', dependencies=[Depends(authenticate), Depends(csrf)])
async def add_ignored(word: str = Form(..., max_length=100), q: str = Form('', max_length=200),
                      alerts: bool = Form(False)):
    try:
        added = store.add_ignored(word)
        message = 'Palavra adicionada ao filtro.' if added else 'Esta palavra já está no filtro.'
    except ValueError as exc:
        message = str(exc)
    return redirect(message, q=q, alerts=alerts, anchor='#ignored-menu')


@app.post('/ignored/{word_id}/delete', dependencies=[Depends(authenticate), Depends(csrf)])
async def delete_ignored(word_id: int, q: str = Form('', max_length=200), alerts: bool = Form(False)):
    store.execute('DELETE FROM ignored_keywords WHERE id=?', (word_id,))
    return redirect('Palavra removida do filtro.', q=q, alerts=alerts, anchor='#ignored-menu')


@app.post('/offers/{offer_id}/seen', dependencies=[Depends(authenticate), Depends(csrf)])
async def seen(offer_id: int, q: str = Form('', max_length=200), alerts: bool = Form(False)):
    store.mark_seen(offer_id)
    return redirect('Oferta marcada como lida.', q=q, alerts=alerts, anchor=f'#offer-{offer_id}')


@app.get('/offers/{offer_id}/media', dependencies=[Depends(authenticate)])
async def offer_media(offer_id: int, thumbnail: bool = False):
    rows = store.rows('SELECT * FROM offers WHERE id=?', (offer_id,))
    if not rows:
        raise HTTPException(404, 'Oferta não encontrada.')
    offer = rows[0]
    info = media_info(source_data(offer))
    if not info or info['kind'] == 'unsupported':
        raise HTTPException(404, 'Mídia não disponível para visualização.')
    try:
        path = await telegram.download(offer, thumbnail)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except (errors.RPCError, OSError, asyncio.TimeoutError):
        raise HTTPException(503, 'Não foi possível carregar a mídia. Tente novamente ou abra no Telegram.')
    inline = info['kind'] in ('photo', 'video', 'audio')
    mime = 'image/jpeg' if thumbnail else (info['mime'] if inline else 'application/octet-stream')
    return FileResponse(path, media_type=mime, filename='miniatura.jpg' if thumbnail else info['name'],
                        content_disposition_type='inline' if inline or thumbnail else 'attachment')


@app.post('/offers/{offer_id}/refresh', dependencies=[Depends(authenticate), Depends(csrf)])
async def refresh_offer(offer_id: int, q: str = Form('', max_length=200), alerts: bool = Form(False)):
    rows = store.rows('SELECT * FROM offers WHERE id=?', (offer_id,))
    if not rows:
        raise HTTPException(404, 'Oferta não encontrada.')
    try:
        async with telegram.lock:
            await telegram.refresh(rows[0])
        message = 'Conteúdo original recuperado do Telegram.'
    except ValueError as exc:
        message = str(exc)
    except errors.FloodWaitError as exc:
        message = f'Telegram solicitou aguardar {exc.seconds} segundos antes de recuperar o original.'
    except (errors.RPCError, OSError, asyncio.TimeoutError):
        message = 'Não foi possível recuperar o original. Conteúdo anterior preservado; tente novamente.'
    return redirect(message, q=q, alerts=alerts, anchor=f'#message-{offer_id}')
