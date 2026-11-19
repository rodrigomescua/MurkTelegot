import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

with tempfile.TemporaryDirectory() as directory:
    env = dict(os.environ, DATA_DIR=directory, APP_PASSWORD='test-password-long-enough', TELEGRAM_API_ID='', TELEGRAM_API_HASH='')
    setup = """import os
from datetime import UTC, datetime
from app.store import Store
s = Store(os.path.join(os.environ['DATA_DIR'], 'offers.db'))
s.execute('INSERT INTO chats VALUES(?,?)', (1, 'Grupo teste'))
s.execute('INSERT INTO rules(id,name,keywords) VALUES(1,?,?)', ('Alerta PS5', 'ps5'))
date = datetime.now(UTC).isoformat()
for number in range(1, 22):
    s.ingest(1, number, f'Cafeteira premium PS5 oferta sintética {number}', date, None)
for number in (22, 23):
    s.ingest(1, number, f'Cafeteira premium oferta sintética {number}', date, None)
"""
    subprocess.run([sys.executable, '-c', setup], env=env, check=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
            context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}/login')
            page.locator('#username').fill('admin')
            page.locator('#panel-password').fill('test-password-long-enough')
            page.get_by_role('button', name='Entrar').tap()
            page.wait_for_url(f'http://127.0.0.1:{port}/')
            assert page.locator('.offer-card').count() == 2
            page.goto(f'http://127.0.0.1:{port}/alerts')
            unread_cards = page.locator('section[aria-labelledby="unread-title"] .offer-card')
            unread_card = unread_cards.first
            card_id = unread_card.get_attribute('id')
            unread_card.locator('[data-mark-seen] button').tap()
            read_card = page.locator(f'section[aria-labelledby="read-title"] #{card_id}')
            delete_button = read_card.get_by_role('button', name='Excluir oferta')
            delete_button.wait_for()
            assert read_card.get_by_text('Lido · Alerta PS5', exact=True).is_visible()
            assert read_card.locator('.offer-action-overlay').is_hidden()
            assert read_card.get_by_role('button', name='Desfazer').is_hidden()
            assert page.locator('[data-global-undo]').is_hidden()
            assert unread_cards.count() == 20
            delete_button.tap()
            read_card.get_by_text('Oferta excluída.').wait_for()
            assert page.locator('[data-global-undo]').is_visible()
            page.locator('[data-global-undo]').tap()
            read_card.locator('.offer-action-overlay').wait_for(state='hidden')
            page.reload()
            assert delete_button.is_visible()
            assert read_card.get_by_text('Lido · Alerta PS5', exact=True).is_visible()
            csrf = read_card.locator('[data-delete-offer] input[name="csrf"]').get_attribute('value')
            delete_button.tap()
            read_card.get_by_text('Oferta excluída.').wait_for()
            page.reload()
            assert read_card.count() == 0
            restored = page.request.post(f'http://127.0.0.1:{port}/offers/{card_id.removeprefix("offer-")}/delete/undo',
                                         form={'csrf': csrf})
            assert restored.ok
            page.goto(f'http://127.0.0.1:{port}/')
            home_card = page.locator(f'#{card_id}')
            assert home_card.count() == 0

            page.locator('.nav-toggle').tap()
            page.get_by_role('link', name='Termos frequentes').tap()
            page.wait_for_url('**/terms')
            trigger = page.get_by_role('link', name='Ver ofertas com cafeteira', exact=True)
            assert trigger.get_attribute('href') == '/?q=cafeteira'
            trigger.tap()
            page.wait_for_url('**/?q=cafeteira')
            assert page.locator('.term-offers-modal').count() == 0
            assert page.locator('.offer-card').count() == 2

            # Sem JavaScript, o mesmo link abre a Home com o termo como filtro.
            fallback_context = browser.new_context(viewport={'width': 390, 'height': 844}, java_script_enabled=False)
            nojs = fallback_context.new_page()
            nojs.goto(f'http://127.0.0.1:{port}/login')
            nojs.locator('#username').fill('admin')
            nojs.locator('#panel-password').fill('test-password-long-enough')
            with nojs.expect_navigation():
                nojs.locator('button').click()
            nojs.get_by_role('link', name='Termos frequentes').click()
            nojs.wait_for_url('**/terms')
            nojs.get_by_role('link', name='Ver ofertas com cafeteira', exact=True).click()
            nojs.wait_for_url('**/?q=cafeteira')
            assert nojs.locator('.offer-card').count() == 2
            fallback_context.close()

            assert not errors, errors
            print('Chromium móvel: alertas lidos, exclusão e desfazer; navegação filtrada com e sem JavaScript')

            desktop = browser.new_context(viewport={'width': 1365, 'height': 900})
            desktop_page = desktop.new_page()
            desktop_page.on('pageerror', lambda error: errors.append(str(error)))
            desktop_page.goto(f'http://127.0.0.1:{port}/login')
            desktop_page.locator('#username').fill('admin')
            desktop_page.locator('#panel-password').fill('test-password-long-enough')
            desktop_page.get_by_role('button', name='Entrar').click()
            desktop_page.goto(f'http://127.0.0.1:{port}/alerts')
            desktop_card = desktop_page.locator('section[aria-labelledby="read-title"] .offer-card').first
            desktop_card.locator('[data-delete-offer] button').click()
            desktop_card.get_by_text('Oferta excluída.').wait_for()
            desktop_card.get_by_role('button', name='Desfazer').click()
            desktop_card.locator('.offer-action-overlay').wait_for(state='hidden')
            assert desktop_page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors, errors
            print('Chromium desktop: exclusão/desfazer sem overflow')
            desktop.close()
            browser.close()
    finally:
        server.terminate()
        server.wait()
