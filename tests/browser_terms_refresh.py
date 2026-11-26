import os, socket, subprocess, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright

os.chdir(Path(__file__).resolve().parents[1])

with tempfile.TemporaryDirectory() as directory:
    env = dict(os.environ, DATA_DIR=directory, APP_PASSWORD='test-password-long-enough', TELEGRAM_API_ID='', TELEGRAM_API_HASH='')
    setup = """from app.store import Store
from datetime import datetime, timezone
import os
s=Store(os.path.join(os.environ['DATA_DIR'],'offers.db'))
s.execute('INSERT INTO chats VALUES(?,?)',(1,'Grupo teste'))
date=datetime.now(timezone.utc).isoformat()
s.ingest(1,1,'Cafeteira em oferta',date,None)
s.ingest(1,2,'Cafeteira promoção',date,None)
"""
    subprocess.run([sys.executable, '-c', setup], env=env, check=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{port}/')
            page.locator('#username').fill('admin')
            page.locator('#panel-password').fill('test-password-long-enough')
            page.get_by_role('button', name='Entrar').click()
            page.goto(f'http://127.0.0.1:{port}/terms')
            term = page.locator('.terms-list .term-label strong').first
            term.evaluate('''el => { const range=document.createRange(); range.selectNodeContents(el); const selection=getSelection(); selection.removeAllRanges(); selection.addRange(range); }''')
            page.locator('.selection-actions [data-selection-action="rule"]').wait_for(state='visible')
            page.locator('.selection-actions [data-selection-action="rule"]').click()
            page.get_by_text('Regra criada.', exact=False).wait_for()
            assert 'não foi possível atualizar' not in page.locator('#action-status').inner_text().lower()
            page.get_by_role('button', name='Ignorar ofertas com cafeteira').click()
            page.get_by_text('Palavra salva no filtro de ofertas.', exact=True).wait_for()
            assert page.locator('#action-status').inner_text() == 'Palavra salva no filtro de ofertas.'
            assert page.get_by_role('button', name='Ignorar ofertas com cafeteira').count() == 0
            assert 'Alteração salva, mas não foi possível atualizar' not in page.locator('body').inner_text()
            browser.close()
    finally:
        server.terminate(); server.wait()
print('Chromium: alerta criado pelo termo e ação em /terms atualizam sem toast de erro')
