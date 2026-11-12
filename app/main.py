import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from urllib.parse import urlencode, urlsplit
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from telethon import errors

from app.ai import EXTRACTION_PROMPT, AIError, extract as extract_ai, list_models as list_ai_models
from app.gotify import send_gotify, validate_gotify_token, validate_gotify_url
from app.messages import media_info, present, preview_lines, source_data
from app.store import MAX_AI_PARALLELISM, Store
from app.telegram import Telegram

AI_REQUEST_TIMEOUT = 60
logging.basicConfig(level=logging.INFO)


class SignedMediaAccessFilter(logging.Filter):
    def filter(self, record):
        return '/public-media/' not in record.getMessage()


logging.getLogger('uvicorn.access').addFilter(SignedMediaAccessFilter())
os.umask(0o077)
data_dir = Path(os.getenv('DATA_DIR', '/data'))
data_dir.mkdir(parents=True, exist_ok=True)
os.chmod(data_dir, 0o700)
password = os.environ.get('APP_PASSWORD', '')
if len(password) < 12 or password == 'SUBSTITUA-POR-UMA-SENHA-ALEATORIA-LONGA':
    raise RuntimeError('Set APP_PASSWORD to a unique password with at least 12 characters')
store = Store(data_dir / 'offers.db')
telegram = Telegram(store, data_dir, os.getenv('TELEGRAM_API_ID'), os.getenv('TELEGRAM_API_HASH'))
public_url = os.getenv('APP_PUBLIC_URL', '').strip().rstrip('/')
if public_url:
    try:
        parts = urlsplit(public_url)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query
                or parts.fragment or parts.path not in ('', '/')):
            raise ValueError()
        parts.port
    except ValueError:
        raise RuntimeError('APP_PUBLIC_URL must be a valid HTTPS origin without credentials, query, or fragment')
csrf_token = secrets.token_urlsafe(32)
sessions = {}
ai_requests = {}
SESSION_AGE = 12 * 60 * 60


def authenticate(request: Request):
    token = request.cookies.get('panel_session', '')
    expires = sessions.get(token, 0)
    if expires > time.monotonic():
        return
    if token:
        sessions.pop(token, None)
    if 'application/json' in request.headers.get('accept', ''):
        raise HTTPException(401, 'Sessão expirada. Entre novamente.')
    raise HTTPException(303, headers={'Location': '/login'})


async def csrf(request: Request):
    form = await request.form()
    if not secrets.compare_digest(str(form.get('csrf', '')), csrf_token):
        raise HTTPException(403, 'Formulário expirado. Recarregue a página.')


@asynccontextmanager
async def lifespan(app):
    await telegram.start()
    async def expire_loop():
        while True:
            await asyncio.to_thread(store.expire_offers)
            await asyncio.to_thread(telegram.cleanup_media_cache)
            await asyncio.sleep(300)
    expiry = asyncio.create_task(expire_loop())
    await asyncio.to_thread(store.recover_ai_jobs)
    ai_worker = asyncio.create_task(ai_job_loop())
    yield
    expiry.cancel()
    ai_worker.cancel()
    await asyncio.gather(expiry, ai_worker, return_exceptions=True)
    await telegram.stop()


async def ai_job_loop():
    await asyncio.gather(*(ai_job_worker() for _ in range(MAX_AI_PARALLELISM)))


async def ai_job_worker():
    while True:
        try:
            job = await asyncio.to_thread(store.claim_ai_job)
        except Exception:
            logging.getLogger(__name__).exception('Falha ao buscar job de IA na fila')
            await asyncio.sleep(1)
            continue
        if not job:
            await asyncio.sleep(1)
            continue
        logging.getLogger(__name__).info('Job de IA %s iniciado', job['id'])
        try:
            await process_ai_job(job)
        except Exception:
            logging.getLogger(__name__).exception('Worker de IA falhou no job %s', job['id'])
            try:
                await asyncio.to_thread(store.fail_ai_job, job['id'], 'Falha interna no worker de IA.')
            except Exception:
                logging.getLogger(__name__).exception('Não foi possível finalizar job de IA %s após falha', job['id'])
            continue
        logging.getLogger(__name__).info('Job de IA %s encerrado', job['id'])


async def process_ai_job(job):
    while True:
        item = await asyncio.to_thread(store.claim_ai_item, job['id'])
        if not item:
            break
        await asyncio.to_thread(store.update_ai_item_stage, item['id'], 'Preparando oferta')
        logging.getLogger(__name__).info('Job de IA %s iniciou item %s (oferta %s)',
                                         job['id'], item['id'], item['message_id'])
        try:
            if not job['replace_existing'] and await asyncio.to_thread(store.ai_item_has_extraction, item):
                await asyncio.to_thread(store.finish_ai_item, item['id'], 'skipped')
                continue
            content = await asyncio.to_thread(store.ai_item_content, item)
            if not content or not content['text'].strip():
                await asyncio.to_thread(store.record_ai_attempt, job['id'], item['id'],
                                         'sistema', '-', 'failed',
                                         'A oferta foi removida ou não contém texto para extrair.', 0)
                await asyncio.to_thread(store.finish_ai_item, item['id'], 'failed')
                continue
            attempted = set()
            finished = False
            had_failure = False
            while not finished:
                if await asyncio.to_thread(store.ai_job_cancel_requested, job['id']):
                    await asyncio.to_thread(store.finish_ai_item, item['id'], 'cancelled')
                    break
                await asyncio.to_thread(store.update_ai_item_stage, item['id'], 'Selecionando modelo')
                models = ([] if len(attempted) >= 200 else
                          await asyncio.to_thread(store.configured_ai_models))
                model = next((candidate for candidate in models
                              if (candidate['provider'], candidate['id'],
                                  hashlib.sha256(candidate['api_key'].encode()).digest()) not in attempted), None)
                if not model:
                    if had_failure and await asyncio.to_thread(
                            store.requeue_failed_ai_item, job['id'], item['id'], 1):
                        logging.getLogger(__name__).info(
                            'Job de IA %s item %s reenfileirado após falha dos modelos', job['id'], item['id'])
                        return
                    detail = ('Limite de 200 tentativas por oferta atingido.' if len(attempted) >= 200 else
                              'Nenhum modelo está configurado para as próximas tentativas.')
                    await asyncio.to_thread(store.record_ai_attempt, job['id'], item['id'],
                                             'sistema', '-', 'failed', detail, 0)
                    await asyncio.to_thread(store.finish_ai_item, item['id'], 'failed')
                    break
                attempted.add((model['provider'], model['id'],
                               hashlib.sha256(model['api_key'].encode()).digest()))
                started = time.monotonic()
                await asyncio.to_thread(store.update_ai_item_stage, item['id'],
                                         f"Consultando {model['provider']} · {model['id']}")
                logging.getLogger(__name__).info('Job de IA %s item %s consultando %s/%s',
                                                 job['id'], item['id'], model['provider'], model['id'])
                try:
                    prompt_extra = (await asyncio.to_thread(store.ai_settings))['prompt_extra']
                    request_task = asyncio.create_task(extract_ai(model['provider'], model['api_key'],
                                                                  model['id'], content['text'], prompt_extra))
                    ai_requests[job['id']] = request_task
                    if await asyncio.to_thread(store.ai_job_cancel_requested, job['id']):
                        request_task.cancel()
                    try:
                        async def cancel_deleted_offer_request():
                            while not request_task.done():
                                if await asyncio.to_thread(store.ai_job_cancel_requested, job['id']):
                                    request_task.cancel()
                                    return
                                await asyncio.sleep(0.1)

                        cancel_watcher = asyncio.create_task(cancel_deleted_offer_request())
                        try:
                            extraction = await asyncio.wait_for(request_task, timeout=AI_REQUEST_TIMEOUT)
                        finally:
                            cancel_watcher.cancel()
                            await asyncio.gather(cancel_watcher, return_exceptions=True)
                    finally:
                        ai_requests.pop(job['id'], None)
                except asyncio.CancelledError:
                    if not await asyncio.to_thread(store.ai_job_cancel_requested, job['id']):
                        raise
                    await asyncio.to_thread(store.finish_ai_item, item['id'], 'cancelled')
                    outcome = 'cancelled'
                    detail = 'Conexão local interrompida; o provedor ainda pode continuar o processamento ou cobrar.'
                    failure_type = ''
                    finished = True
                except (AIError, ValueError) as exc:
                    detail = str(exc)
                    outcome = 'failed'
                    failure_type = getattr(exc, 'failure_type', 'invalid_response')
                except asyncio.TimeoutError:
                    detail = 'Tempo limite de 1 minuto excedido.'
                    outcome = 'failed'
                    failure_type = 'request_timeout'
                except Exception:
                    detail = 'Falha interna ao consultar o modelo.'
                    outcome = 'failed'
                    failure_type = 'internal'
                else:
                    detail = 'Dados comerciais extraídos.'
                    outcome = 'succeeded'
                    failure_type = ''
                if outcome == 'succeeded':
                    await asyncio.to_thread(store.update_ai_item_stage, item['id'], 'Salvando resultado')
                    saved = await asyncio.to_thread(store.finish_ai_item, item['id'], 'succeeded',
                                                    extraction, content['content_hash'])
                    if saved == 'stale':
                        outcome = 'skipped'
                        detail = 'Resultado descartado porque a oferta mudou durante a extração.'
                    elif saved == 'cancelled':
                        outcome = 'cancelled'
                        detail = 'Job cancelado durante a chamada; resultado descartado.'
                    finished = True
                await asyncio.to_thread(store.record_ai_attempt, job['id'], item['id'],
                                         model['provider'], model['id'], outcome, detail,
                                         int((time.monotonic() - started) * 1000), failure_type)
                logging.getLogger(__name__).info(
                    'Job de IA %s item %s modelo %s/%s resultado=%s tipo=%s duração_ms=%s',
                    job['id'], item['id'], model['provider'], model['id'], outcome,
                    failure_type or '-', int((time.monotonic() - started) * 1000))
                had_failure = had_failure or outcome == 'failed'
                if outcome == 'failed' and await asyncio.to_thread(store.ai_job_cancel_requested, job['id']):
                    await asyncio.to_thread(store.finish_ai_item, item['id'], 'cancelled')
                    finished = True
                if outcome in ('succeeded', 'skipped', 'cancelled'):
                    finished = True
        except Exception:
            logging.getLogger(__name__).exception('Falha ao processar item %s do job de IA %s',
                                                  item['id'], job['id'])
            await asyncio.to_thread(store.finish_ai_item, item['id'], 'failed')
    logging.getLogger(__name__).info('Finalizando job de IA %s', job['id'])
    await asyncio.to_thread(store.finish_ai_job, job['id'])


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount('/static', StaticFiles(directory='app/static'), name='static')
app.mount('/brand', StaticFiles(directory='assets/murktelegot-logo'), name='brand')


def template_context(request):
    return {} if request.url.path == '/login' else {'unread': store.unread()}


templates = Jinja2Templates(directory='app/templates', context_processors=[template_context])


@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/health')
async def health():
    return {'status': 'ok'}


@app.get('/login')
async def login_page(request: Request):
    return templates.TemplateResponse(request, 'login.html', {'csrf': csrf_token, 'error': ''})


@app.post('/login', dependencies=[Depends(csrf)])
async def login(request: Request, username: str = Form(..., max_length=256),
                panel_password: str = Form(..., max_length=256)):
    user_ok = secrets.compare_digest(username.encode(), os.getenv('APP_USER', 'admin').encode())
    pass_ok = secrets.compare_digest(panel_password.encode(), password.encode())
    if not (user_ok and pass_ok):
        return templates.TemplateResponse(request, 'login.html', {
            'csrf': csrf_token, 'error': 'Usuário ou senha inválidos.', 'username': username,
        }, status_code=401)
    sessions.pop(request.cookies.get('panel_session', ''), None)
    now = time.monotonic()
    for token, expiry in list(sessions.items()):
        if expiry <= now:
            sessions.pop(token, None)
    token = secrets.token_urlsafe(32)
    sessions[token] = now + SESSION_AGE
    response = RedirectResponse('/', status_code=303)
    response.set_cookie('panel_session', token, max_age=SESSION_AGE, httponly=True,
                        samesite='strict', secure=request.url.scheme == 'https')
    return response


@app.post('/logout', dependencies=[Depends(authenticate), Depends(csrf)])
async def logout(request: Request):
    sessions.pop(request.cookies.get('panel_session', ''), None)
    response = RedirectResponse('/login', status_code=303)
    response.delete_cookie('panel_session')
    return response


def prepare_offers(offers):
    for offer in offers:
        offer['parts'] = [present(part) for part in offer['parts']]
        offer['preview_lines'] = preview_lines(offer['parts'])
        offer['cover'] = next((part for part in offer['parts'] if part['media'] and
                               (part['media']['kind'] == 'photo' or part['media'].get('thumbnail'))), None)


@app.get('/alerts', dependencies=[Depends(authenticate)])
@app.get('/', dependencies=[Depends(authenticate)])
async def dashboard(request: Request, alerts: bool = False, q: str = '', notice: str = ''):
    alerts = alerts or request.url.path == '/alerts'
    with store.connect() as db:
        db.execute('BEGIN')
        marker = db.execute('SELECT coalesce(max(id), 0) FROM offers').fetchone()[0]
        unread_offers = store.feed(q, True, db, read=False) if alerts else []
        read_offers = store.feed(q, True, db, read=True) if alerts else []
        offers = unread_offers + read_offers if alerts else store.feed(q, False, db)
    prepare_offers(offers)
    return templates.TemplateResponse(request, 'index.html', {
        'csrf': csrf_token, 'authorized': await telegram.authorized(),
        'configured': bool(telegram.client), 'connection_error': telegram.error,
        'phone': telegram.phone or '', 'code_pending': bool(telegram.code_hash),
        'needs_password': telegram.needs_password,
        'chats': store.rows('SELECT * FROM chats ORDER BY title'),
        'offers': offers, 'unread_offers': unread_offers, 'read_offers': read_offers, 'marker': marker,
        'alerts': alerts, 'q': q, 'notice': notice,
    })


@app.get('/deleted', dependencies=[Depends(authenticate)])
def deleted_offers_page(request: Request, page: int = 1):
    offers, total, page, pages = store.deleted_feed_page(page)
    prepare_offers(offers)
    return templates.TemplateResponse(request, 'deleted.html', {
        'csrf': csrf_token, 'offers': offers, 'deleted_view': True,
        'total': total, 'page': page, 'pages': pages,
    })


@app.get('/alerts/unread-count', dependencies=[Depends(authenticate)])
async def unread_alert_count():
    return {'unread': store.unread()}


@app.get('/telegram', dependencies=[Depends(authenticate)])
async def telegram_page(request: Request, notice: str = ''):
    return templates.TemplateResponse(request, 'telegram_page.html', {
        'csrf': csrf_token, 'authorized': await telegram.authorized(),
        'configured': bool(telegram.client), 'connection_error': telegram.error,
        'phone': telegram.phone or '', 'code_pending': bool(telegram.code_hash),
        'needs_password': telegram.needs_password,
        'chats': store.rows('SELECT * FROM chats ORDER BY title'), 'notice': notice,
    })


@app.get('/offers/new', dependencies=[Depends(authenticate)])
async def new_offers(after: int = 0, q: str = '', alerts: bool = False):
    if after < 0 or len(q) > 200:
        raise HTTPException(400, 'Filtro inválido.')
    return {'count': store.new_offers(after, q, alerts)}


def redirect(notice='', *, q='', alerts=False, anchor=''):
    from urllib.parse import urlencode
    return RedirectResponse(('/alerts?' if alerts else '/?') + urlencode({'notice': notice, 'q': q}) + anchor, status_code=303)


@app.post('/telegram/{action}', dependencies=[Depends(authenticate), Depends(csrf)])
async def telegram_action(request: Request, action: str, phone: str = Form('', max_length=30),
                          code: str = Form('', max_length=20), password: str = Form('', max_length=256)):
    async def reply(message, ok=False):
        if 'application/json' not in request.headers.get('accept', ''):
            return RedirectResponse('/telegram?' + urlencode({'notice': message}), status_code=303)
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


@app.get('/settings', dependencies=[Depends(authenticate)])
async def settings_page(request: Request, notice: str = '', test_error: str = ''):
    config = store.gotify_settings()
    ai_config = store.ai_settings()
    return templates.TemplateResponse(request, 'settings.html', {
        'csrf': csrf_token, 'gotify_url': config['url'], 'gotify_enabled': config['enabled'],
        'token_configured': bool(config['token']), 'notice': notice, 'test_error': test_error,
        'frequent_terms_min_chars': store.frequent_terms_min_chars(),
          'ai_parallelism': store.ai_parallelism(),
        'ai_config': ai_config, 'ai_prompt_base': EXTRACTION_PROMPT,
    })


@app.get('/ai-jobs', dependencies=[Depends(authenticate)])
async def ai_jobs_page(request: Request, notice: str = ''):
    jobs, active = store.ai_jobs()
    ai_config = store.ai_settings()
    ai_cards = store.feed()
    ai_config['total_cards'] = len(ai_cards)
    ai_config['eligible_count'] = sum(not card.get('extraction') for card in ai_cards)
    ai_config['ready'] = bool(ai_config['model_order']) and all(
        ai_config['providers'][item['provider']]['configured'] for item in ai_config['model_order'])
    return templates.TemplateResponse(request, 'ai_jobs.html', {
        'csrf': csrf_token, 'jobs': jobs, 'active_job': active, 'notice': notice,
        'ai_config': ai_config, 'model_metrics': store.ai_model_metrics(),
    })


@app.get('/coupons', dependencies=[Depends(authenticate)])
async def coupons_page(request: Request, notice: str = ''):
    return templates.TemplateResponse(request, 'coupons.html', {
        'csrf': csrf_token, 'stores': store.coupons_by_store(), 'notice': notice,
    })


@app.post('/coupons/{coupon_id}/inactive', dependencies=[Depends(authenticate), Depends(csrf)])
async def mark_coupon_inactive(coupon_id: int):
    changed = await asyncio.to_thread(store.mark_coupon_inactive, coupon_id)
    notice = 'Cupom marcado como inativo.' if changed else 'Cupom não encontrado.'
    return RedirectResponse('/coupons?' + urlencode({'notice': notice}), status_code=303)


@app.post('/ai-jobs/clear-completed', dependencies=[Depends(authenticate), Depends(csrf)])
async def clear_completed_ai_jobs():
    await asyncio.to_thread(store.clear_completed_ai_jobs)
    return RedirectResponse('/ai-jobs?notice=Hist%C3%B3rico+conclu%C3%ADdo+limpo.', status_code=303)


@app.post('/ai-jobs/clear-all', dependencies=[Depends(authenticate), Depends(csrf)])
async def clear_all_ai_jobs():
    active = await asyncio.to_thread(store.cancel_and_clear_ai_jobs)
    for job_id in active:
        if request_task := ai_requests.get(job_id):
            request_task.cancel()
    notice = 'Cancelamento solicitado; o histórico será limpo quando os jobs em andamento encerrarem.'
    return RedirectResponse('/ai-jobs?' + urlencode({'notice': notice}), status_code=303)


@app.get('/ai-jobs/status', dependencies=[Depends(authenticate)])
async def ai_jobs_status():
    return {'active_job': store.ai_job_status(), 'model_metrics': store.ai_model_metrics()}


@app.post('/ai-jobs/{job_id}/cancel', dependencies=[Depends(authenticate), Depends(csrf)])
async def cancel_ai_job(job_id: int):
    result = await asyncio.to_thread(store.cancel_ai_job, job_id)
    if result == 'cancelling' and (request_task := ai_requests.get(job_id)):
        request_task.cancel()
    notices = {
        'cancelled': f'Job #{job_id} cancelado.',
        'cancelling': f'Job #{job_id}: conexão local interrompida. O provedor ainda pode continuar o processamento ou cobrar; as ofertas restantes foram canceladas.',
        'missing': 'Job não encontrado.',
        'finished': 'Este job já foi concluído e não pode ser cancelado.',
    }
    return RedirectResponse('/ai-jobs?' + urlencode({'notice': notices[result]}), status_code=303)


@app.post('/settings/ai/models', dependencies=[Depends(authenticate), Depends(csrf)])
async def ai_models(provider: str = Form(...), api_key: str = Form('', max_length=4096)):
    try:
        key = store.ai_api_key(provider, api_key)
        models = await list_ai_models(provider, key)
    except ValueError as exc:
        return JSONResponse({'ok': False, 'message': str(exc)}, status_code=400)
    return {'ok': True, 'models': models}


@app.post('/settings/ai', dependencies=[Depends(authenticate), Depends(csrf)])
async def save_ai_settings(openai_key: str = Form('', max_length=4096),
                           openrouter_key: str = Form('', max_length=4096),
                           models_openai: list[str] = Form(default=[]),
                           models_openrouter: list[str] = Form(default=[]),
                           model_order: str = Form('', max_length=100_000),
                           prompt_extra: str = Form('', max_length=20_000),
                           value: int | None = Form(None)):
    try:
        if value is not None and not 1 <= value <= MAX_AI_PARALLELISM:
            raise ValueError(f'A quantidade de jobs simultâneos deve ser um número entre 1 e {MAX_AI_PARALLELISM}.')
        submitted_order = json.loads(model_order) if model_order else []
        selected = {
            'openai': [model for model in models_openai if model],
            'openrouter': [model for model in models_openrouter if model],
        }
        allowed = {(provider, model) for provider, models in selected.items() for model in models}
        ordered = [item for item in submitted_order if isinstance(item, dict) and
                   (item.get('provider'), item.get('id')) in allowed] if isinstance(submitted_order, list) else []
        seen = {(item['provider'], item['id']) for item in ordered}
        ordered.extend({'provider': provider, 'id': model} for provider in ('openai', 'openrouter')
                       for model in selected[provider] if (provider, model) not in seen)
        store.save_ai_settings(openai_key, openrouter_key, ordered, prompt_extra)
        if value is not None:
            store.save_ai_parallelism(value)
    except (ValueError, TypeError) as exc:
        return settings_redirect(str(exc) or 'A ordem dos modelos é inválida.', error=True)
    return settings_redirect('Configuração de IA salva.')


@app.post('/settings/ai/parallelism', dependencies=[Depends(authenticate), Depends(csrf)])
async def save_ai_parallelism(value: int = Form(...)):
    try:
        store.save_ai_parallelism(value)
    except ValueError as exc:
        return settings_redirect(str(exc), error=True)
    return settings_redirect('Quantidade de jobs simultâneos salva.')


@app.post('/ai-jobs', dependencies=[Depends(authenticate), Depends(csrf)])
async def enqueue_ai_job(replace_existing: bool = Form(False)):
    try:
        job_id, count = store.enqueue_ai_job(replace_existing)
    except ValueError as exc:
        return settings_redirect(str(exc), error=True)
    return RedirectResponse('/ai-jobs?' + urlencode({'notice': f'Job #{job_id} criado para {count} ofertas.'}),
                            status_code=303)


@app.post('/offers/{offer_id}/extract', dependencies=[Depends(authenticate), Depends(csrf)])
async def reextract_offer(request: Request, offer_id: int):
    try:
        job_id, count = store.enqueue_ai_job(True, offer_ids=[offer_id])
    except ValueError as exc:
        if 'application/json' in request.headers.get('accept', ''):
            return JSONResponse({'ok': False, 'message': str(exc)}, status_code=400)
        return RedirectResponse('/?' + urlencode({'notice': str(exc)}), status_code=303)
    if count != 1:
        raise HTTPException(404, 'Oferta não encontrada.')
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'ok': True, 'job_id': job_id, 'status': 'queued'},
                            headers={'Cache-Control': 'no-store'})
    return RedirectResponse('/?' + urlencode({'notice': 'Extração iniciada.'}), status_code=303)


@app.get('/offers/{offer_id}/extraction-status', dependencies=[Depends(authenticate)])
def offer_extraction_status(offer_id: int):
    state = store.ai_offer_extraction_status(offer_id)
    if state is None:
        raise HTTPException(404, 'Oferta não encontrada.')
    return JSONResponse(state, headers={'Cache-Control': 'no-store'})


@app.post('/settings/frequent-terms', dependencies=[Depends(authenticate), Depends(csrf)])
async def save_frequent_terms_settings(min_chars: int = Form(...)):
    try:
        store.save_frequent_terms_min_chars(min_chars)
    except ValueError as exc:
        return settings_redirect(str(exc), error=True)
    return settings_redirect('Quantidade mínima dos termos frequentes salva.')


def settings_redirect(message, *, error=False):
    from urllib.parse import urlencode
    return RedirectResponse('/settings?' + urlencode({'test_error' if error else 'notice': message}), status_code=303)


@app.post('/settings/gotify', dependencies=[Depends(authenticate), Depends(csrf)])
async def save_gotify_settings(url: str = Form('', max_length=2048), token: str = Form('', max_length=256),
                               enabled: bool = Form(False)):
    try:
        url = validate_gotify_url(url)
        validate_gotify_token(token)
        store.save_gotify(url, token, enabled)
    except ValueError as exc:
        return settings_redirect(str(exc))
    return settings_redirect('Configuração Gotify salva.')


@app.post('/settings/gotify/clear', dependencies=[Depends(authenticate), Depends(csrf)])
async def clear_gotify_settings():
    store.clear_gotify()
    return settings_redirect('Configuração Gotify removida.')


@app.post('/settings/gotify/test', dependencies=[Depends(authenticate), Depends(csrf)])
async def test_gotify_settings():
    config = store.gotify_settings()
    if not config['url'] or not config['token']:
        return settings_redirect('Salve a URL e o token Gotify antes de testar.', error=True)
    sent, detail = await asyncio.to_thread(send_gotify, config['url'], config['token'],
                                           'Teste · MurkTelegot', 'As notificações Gotify estão configuradas.')
    if not sent:
        logging.getLogger(__name__).warning('Teste Gotify falhou: %s', detail)
        return settings_redirect('Não foi possível enviar o teste. ' + detail, error=True)
    return settings_redirect('Notificação de teste enviada.')


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
async def add_rule(request: Request, background_tasks: BackgroundTasks,
                   keyword: str = Form(..., max_length=100)):
    term = keyword.strip()
    valid = bool(term and ',' not in term)
    matched = 0
    if valid:
        matched, alerts = store.add_rule(term, return_alerts=True)
        for alert in alerts:
            background_tasks.add_task(telegram.notify_alert, alert)
    message = (f'Regra criada. Correspondências retroativas: {matched}; mensagens e edições futuras também serão verificadas.' if valid
               else 'Informe uma palavra ou expressão sem vírgulas.')
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'ok': valid, 'message': message, 'matched': matched},
                            status_code=200 if valid else 400, background=background_tasks)
    return RedirectResponse('/rules-page?notice=' + message.replace(' ', '+'), status_code=303,
                            background=background_tasks)


@app.get('/rules-page', dependencies=[Depends(authenticate)])
async def rules_page(request: Request, notice: str = ''):
    return templates.TemplateResponse(request, 'rules.html', {'csrf': csrf_token, 'notice': notice,
        'rules': store.rows('SELECT id,keywords,created_at FROM rules ORDER BY created_at DESC,id DESC')})


@app.post('/rules/{rule_id}/delete', dependencies=[Depends(authenticate), Depends(csrf)])
async def delete_rule(rule_id: int):
    store.remove_rule(rule_id)
    return RedirectResponse('/rules-page?notice=Regra+removida.', status_code=303)


@app.get('/ignored', dependencies=[Depends(authenticate)])
async def ignored_page(request: Request, notice: str = '', q: str = '', page: int = 1):
    if len(q) > 100 or page < 1:
        raise HTTPException(400, 'Filtro inválido.')
    ignored_words, total, page, pages = store.ignored_words_page(q, page)
    return templates.TemplateResponse(request, 'ignored.html', {
        'csrf': csrf_token, 'notice': notice,
        'ignored_words': ignored_words, 'q': q, 'page': page, 'pages': pages, 'total': total,
    })


def ignored_redirect(message):
    from urllib.parse import urlencode
    return RedirectResponse('/ignored?' + urlencode({'notice': message}), status_code=303)


@app.post('/ignored', dependencies=[Depends(authenticate), Depends(csrf)])
async def add_ignored(request: Request, word: str = Form(..., max_length=100),
                      auto_delete: bool = Form(False)):
    try:
        added = store.add_ignored(word, auto_delete=auto_delete)
        message = ('Palavra salva no filtro com autoexclusão permanente.' if auto_delete else
                   'Palavra salva no filtro.') if added else 'Esta palavra já está no filtro.'
    except ValueError as exc:
        added, message = False, str(exc)
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'ok': added, 'message': message}, status_code=200 if added else 400)
    return ignored_redirect(message)


@app.post('/ignored/{word_id}/auto-delete', dependencies=[Depends(authenticate), Depends(csrf)])
async def set_ignored_auto_delete(request: Request, word_id: int, enabled: bool = Form(...),
                                  q: str = Form(''), page: int = Form(1)):
    deleted = store.set_ignored_auto_delete(word_id, enabled)
    if deleted is None:
        raise HTTPException(404, 'Palavra ignorada não encontrada.')
    message = ('Autoexclusão permanente ativada; ofertas correspondentes apagadas: ' + str(deleted) + '.'
               if enabled else 'Autoexclusão permanente desativada.')
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'ok': True, 'message': message, 'deleted': deleted})
    from urllib.parse import urlencode
    return RedirectResponse('/ignored?' + urlencode({'q': q, 'page': page, 'notice': message}), status_code=303)


@app.post('/ignored/{word_id}/delete', dependencies=[Depends(authenticate), Depends(csrf)])
async def delete_ignored(request: Request, word_id: int):
    store.remove_ignored(word_id)
    if 'application/json' in request.headers.get('accept', ''):
        return {'ok': True, 'message': 'Palavra removida do filtro.'}
    from urllib.parse import urlencode
    form = await request.form()
    return RedirectResponse('/ignored?' + urlencode({'q': form.get('q', ''), 'page': form.get('page', 1),
                                                      'notice': 'Palavra removida do filtro.'}), status_code=303)


@app.get('/terms', dependencies=[Depends(authenticate)])
def terms_page(request: Request, page: int = 1, notice: str = ''):
    terms = store.frequent_terms()
    pages = max(1, (len(terms) + 49) // 50)
    page = max(1, min(page, pages))
    return templates.TemplateResponse(request, 'terms.html', {
        'csrf': csrf_token, 'notice': notice, 'terms': terms[(page - 1) * 50:page * 50],
        'page': page, 'pages': pages, 'total': len(terms),
        'hidden_terms': store.rows('SELECT id,word FROM hidden_suggestions ORDER BY word COLLATE NOCASE'),
    })


@app.get('/terms/offers', dependencies=[Depends(authenticate)])
def term_offers_page(request: Request, word: str = '', page: int = 1):
    if not 1 <= len(word) <= 100 or page < 1:
        raise HTTPException(400, 'Filtro inválido.')
    offers, total = store.term_offers(word, page)
    prepare_offers(offers)
    return templates.TemplateResponse(request, 'term_offers.html', {
        'csrf': csrf_token, 'word': word, 'offers': offers, 'total': total,
        'page': page, 'pages': max(1, (total + 19) // 20), 'q': '', 'alerts': False,
    })


def term_reply(request, message, page):
    if 'application/json' in request.headers.get('accept', ''):
        return {'ok': True, 'message': message}
    from urllib.parse import urlencode
    return RedirectResponse('/terms?' + urlencode({'page': max(1, page), 'notice': message}), status_code=303)


@app.post('/terms/batch', dependencies=[Depends(authenticate), Depends(csrf)])
def term_batch(request: Request, action: str = Form(...), words: list[str] = Form(default=[]), page: int = Form(1),
               auto_delete: bool = Form(False)):
    try:
        count = store.add_terms_batch(action, words, auto_delete=auto_delete)
    except ValueError as exc:
        if 'application/json' in request.headers.get('accept', ''):
            return JSONResponse({'ok': False, 'message': str(exc)}, status_code=400)
        return term_reply(request, str(exc), page)
    target = 'ao filtro de ofertas' if action == 'ignore' else 'às sugestões ocultas'
    if action == 'ignore':
        message = f'{count} {"termo salvo" if count == 1 else "termos salvos"} {target}.'
        if auto_delete:
            message = f'{count} {"termo salvo" if count == 1 else "termos salvos"} ao filtro com autoexclusão permanente.'
    else:
        message = f'{count} {"termo adicionado" if count == 1 else "termos adicionados"} {target}.'
    return term_reply(request, message, page)


@app.post('/terms/{action}', dependencies=[Depends(authenticate), Depends(csrf)])
def term_action(request: Request, action: str, word: str = Form(..., max_length=100), page: int = Form(1),
                auto_delete: bool = Form(False)):
    try:
        if action == 'ignore':
            added = store.add_ignored(word, auto_delete=auto_delete)
            message = ('Palavra salva no filtro de ofertas com autoexclusão permanente.' if auto_delete else
                       'Palavra salva no filtro de ofertas.') if added else 'Esta palavra já está no filtro.'
        elif action == 'hide':
            added = store.hide_suggestion(word)
            message = 'Sugestão ocultada desta lista.' if added else 'Esta sugestão já está oculta.'
        else:
            raise HTTPException(404)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return term_reply(request, message, page)


@app.post('/terms/restore/{term_id}', dependencies=[Depends(authenticate), Depends(csrf)])
def restore_term(request: Request, term_id: int, page: int = Form(1)):
    store.execute('DELETE FROM hidden_suggestions WHERE id=?', (term_id,))
    return term_reply(request, 'Sugestão restaurada.', page)


@app.post('/offers/{offer_id}/seen', dependencies=[Depends(authenticate), Depends(csrf)])
async def seen(request: Request, offer_id: int, q: str = Form('', max_length=200), alerts: bool = Form(False)):
    store.mark_seen(offer_id)
    if 'application/json' in request.headers.get('accept', ''):
        return {'ok': True, 'message': 'Alerta marcado como lido.', 'unread': store.unread()}
    return redirect('Alerta marcado como lido.', q=q, alerts=alerts)


@app.post('/offers/{offer_id}/seen/undo', dependencies=[Depends(authenticate), Depends(csrf)])
async def undo_seen(offer_id: int):
    store.mark_unseen(offer_id)
    return {'ok': True, 'message': 'Alerta voltou para não lido.', 'unread': store.unread()}


@app.post('/offers/{offer_id}/delete', dependencies=[Depends(authenticate), Depends(csrf)])
async def delete_offer(request: Request, offer_id: int, q: str = Form('', max_length=200), alerts: bool = Form(False)):
    if not store.delete_offer(offer_id):
        raise HTTPException(404, 'Alerta não encontrado.')
    if 'application/json' in request.headers.get('accept', ''):
        return {'ok': True, 'message': 'Oferta excluída.', 'unread': store.unread()}
    return redirect('Oferta removida.', q=q, alerts=alerts)


@app.post('/offers/{offer_id}/delete/undo', dependencies=[Depends(authenticate), Depends(csrf)])
async def undo_delete_offer(offer_id: int):
    if not store.restore_deleted_offer(offer_id):
        raise HTTPException(404, 'Oferta não encontrada ou exclusão já finalizada.')
    return {'ok': True, 'message': 'Oferta restaurada.', 'unread': store.unread()}


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


@app.get('/public-media/{offer_id}/{expiry}/{signature}')
async def signed_offer_media(offer_id: int, expiry: int, signature: str):
    rows = store.rows('SELECT * FROM offers WHERE id=? AND deleted_at IS NULL', (offer_id,))
    if not rows or expiry <= int(time.time()) or expiry > int(time.time()) + 24 * 60 * 60:
        raise HTTPException(404)
    offer = rows[0]
    identity = f"{offer['chat_id']}:{offer['message_id']}:{expiry}"
    expected = hmac.new(store.media_signing_key().encode(), identity.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(404)
    info = media_info(source_data(offer))
    if not info or info['kind'] != 'photo' or info['spoiler'] or not info['thumbnail']:
        raise HTTPException(404)
    try:
        path = await telegram.download(offer, thumbnail=True)
    except (ValueError, errors.RPCError, OSError, asyncio.TimeoutError):
        raise HTTPException(404)
    response = FileResponse(path, media_type='image/jpeg', filename='miniatura.jpg', content_disposition_type='inline')
    response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
    return response


@app.post('/offers/{offer_id}/refresh', dependencies=[Depends(authenticate), Depends(csrf)])
async def refresh_offer(offer_id: int, q: str = Form('', max_length=200), alerts: bool = Form(False)):
    rows = store.rows('SELECT * FROM offers WHERE id=? AND deleted_at IS NULL', (offer_id,))
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
