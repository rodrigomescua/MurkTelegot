import json, os, socket, subprocess, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright

os.chdir(Path(__file__).resolve().parents[1])

with tempfile.TemporaryDirectory() as directory:
    env = dict(os.environ, DATA_DIR=directory, APP_PASSWORD='test-password-long-enough', TELEGRAM_API_ID='', TELEGRAM_API_HASH='')
    setup = """from app.store import Store
import json, os
s=Store(os.path.join(os.environ['DATA_DIR'],'offers.db'))
s.execute('INSERT INTO chats VALUES(?,?)',(1,'Grupo teste'))
s.ingest(1,1,'Nintendo Switch em oferta','2026-11-04',None)
s.ingest(1,2,'Notebook segredo','2026-11-04',None,source_json=json.dumps({'entities':[{'_':'MessageEntitySpoiler','offset':9,'length':7}]}))
"""
    subprocess.run([sys.executable,'-c',setup],env=env,check=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
            page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            errors=[]; page.on('pageerror',lambda error: errors.append(str(error)))
            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' and 'Content Security Policy' in msg.text else None)
            page.goto(f'http://127.0.0.1:{port}/')
            page.locator('#username').fill('admin'); page.locator('#panel-password').fill('test-password-long-enough'); page.get_by_role('button',name='Entrar').tap()
            page.locator('#name').fill('rascunho preservado')
            page.evaluate('window.testSentinel = 123')
            def select(locator, text):
                locator.scroll_into_view_if_needed()
                locator.evaluate('''(el, text) => { const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let node; while ((node = walker.nextNode())) { const at = node.textContent.indexOf(text); if (at >= 0) { const r=document.createRange(); r.setStart(node,at); r.setEnd(node,at+text.length); const s=window.getSelection(); s.removeAllRanges(); s.addRange(r); return; } } throw Error('Texto não encontrado'); }''',text)
                page.locator('.selection-actions').wait_for(state='visible')
                rect=page.locator('.selection-actions').bounding_box()
                assert rect['x'] >= 0 and rect['x']+rect['width'] <= 390 and rect['y'] >= 0 and rect['y']+rect['height'] <= 844
            select(page.locator('.offer-card').filter(has_text='Nintendo').locator('.offer-preview'),'Nintendo')
            page.locator('.selection-actions [data-selection-action=rule]').tap()
            page.get_by_text('Regra criada.',exact=False).wait_for()
            page.locator('#rules-list strong').filter(has_text='Nintendo').wait_for()
            assert page.locator('#name').input_value() == 'rascunho preservado'
            assert page.evaluate('window.testSentinel') == 123
            page.locator('.offer-card').filter(has_text='Nintendo').locator('.offer-summary').tap()
            assert page.locator('.offer-modal').evaluate('(el)=>el.open')
            select(page.locator('.offer-modal .message-text'),'Switch')
            assert page.locator('.offer-modal .selection-actions').count() == 1
            page.locator('.selection-actions [data-selection-action=ignore]').tap()
            page.get_by_text('Palavra adicionada ao filtro.').wait_for()
            assert page.locator('.offer-modal #action-status').is_visible()
            page.locator('.offer-modal .modal-close').tap()
            page.locator('.offer-card').filter(has_text='Nintendo').wait_for(state='detached')
            assert page.locator('#name').input_value() == 'rascunho preservado'
            page.locator('.offer-card').filter(has_text='Notebook').locator('.offer-summary').tap()
            text=page.locator('.offer-modal .message-text')
            text.evaluate('''el => {const r=document.createRange();r.selectNodeContents(el);const s=window.getSelection();s.removeAllRanges();s.addRange(r)}''')
            page.wait_for_timeout(300)
            assert not page.locator('.selection-actions').is_visible()
            page.locator('.offer-modal .modal-close').tap()
            page.get_by_role('link',name='Configurações',exact=True).tap()
            page.locator('#gotify-token').fill('valor-sensível-sintético')
            page.locator('#gotify-token').select_text()
            page.wait_for_timeout(300)
            assert not page.locator('.selection-actions').is_visible()
            select(page.locator('#gotify-title'),'Notificações')
            page.route('**/ignored', lambda route: route.fulfill(status=500, json={'detail':'Falha simulada'}), times=1)
            page.locator('.selection-actions [data-selection-action=ignore]').tap()
            page.get_by_text('Falha simulada').wait_for()
            assert page.locator('.selection-actions').is_visible()
            assert page.locator('.selection-actions [data-selection-action=ignore]').is_enabled()
            page.locator('.selection-actions [data-selection-action=rule]').tap()
            page.get_by_text('Regra criada.',exact=False).wait_for()
            assert page.locator('#gotify-token').input_value() == 'valor-sensível-sintético'
            page.evaluate('''() => { const p=document.createElement('p'); p.id='synthetic-selection'; p.textContent='ps5, ps4'; document.querySelector('main').append(p) }''')
            select(page.locator('#synthetic-selection'),'ps5, ps4')
            assert page.locator('.selection-actions [data-selection-action=rule]').is_disabled()
            assert page.locator('.selection-actions [data-selection-action=ignore]').is_enabled()
            assert page.get_by_text('Para criar alerta, selecione um trecho sem vírgula.').is_visible()
            page.locator('#synthetic-selection').evaluate("el => { el.textContent = 'x'.repeat(101) }")
            select(page.locator('#synthetic-selection'),'x' * 101)
            page.get_by_text('Selecione até 100 caracteres.').wait_for()
            assert page.locator('.selection-actions [data-selection-action=rule]').is_disabled()
            assert page.locator('.selection-actions [data-selection-action=ignore]').is_disabled()
            assert not errors, errors
            print('Chromium móvel: criar, ignorar no modal, spoilers, campos sensíveis e rascunhos aprovados')
            browser.close()
    finally:
        server.terminate(); server.wait()
