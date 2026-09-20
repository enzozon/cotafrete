"""Capturas e verificações locais; nenhum servidor ou integração externa.

Execute da raiz: python docs/rebranding/validar.py
"""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['COTAFRETE_ADM_SENHA'] = 'senha-sintetica-local'
OUT = ROOT / 'docs' / 'rebranding'
TEMP = ROOT / '.tmp-rebranding' / uuid4().hex
TEMP.mkdir(parents=True)

from core.banco import Banco
from decimal import Decimal

# Intercepta também os efeitos de importação: nunca abre o banco padrão,
# nunca lê .env e nunca executa limpeza de evidências reais.
with patch('dotenv.load_dotenv'), patch('core.evidencias.limpar_antigas'), \
     patch('core.banco.Banco', side_effect=lambda: Banco(TEMP / 'sintetico.db')):
    from web import app as web, adm

if '--tests' in sys.argv:
    import pytest
    raise SystemExit(pytest.main(sys.argv[sys.argv.index('--tests') + 1:]))

from fastapi.testclient import TestClient

carga = dict(cep_origem='29010-000', cep_destino='01310-100',
             cidade_origem='Vitória', uf_origem='ES', cidade_destino='São Paulo',
             uf_destino='SP', peso_kg='12', quantidade=3, comprimento_cm=80,
             largura_cm=60, altura_cm=50, valor_nf='1500.00',
             material='Equipamento demonstrativo', nome_remetente='Empresa exemplo',
             nome_destinatario='Cliente sintético', tipo_frete='cif',
             email='exemplo@example.invalid')
for i in range(12):
    cid = web.banco.salvar_cotacao('Demo', carga)
    for slug in web.AUTOMATICAS:
        web.banco.salvar_resultado(cid, slug, status='cotado',
                                  valor=Decimal('123.45') + i, prazo='3 dias')

client = TestClient(web.app)
client.cookies.set(web.COOKIE, 'Demo')
client.cookies.set(adm.COOKIE_ADM, adm.token_de(os.environ['COTAFRETE_ADM_SENHA']))
pages = {'login': '/login', 'login-adm': '/adm/entrar', 'formulario': '/',
         'resultado': f'/cotacao/{cid}', 'historico': '/historico',
         'ajuda': '/documentacao', 'email': f'/email/{cid}/dellavolpe',
         'della-volpe': f'/dellavolpe/{cid}', 'dashboard': '/adm',
         'detalhe-adm': f'/adm/cotacao/{cid}', 'whatsapp': '/whatsapp-local'}

# HTML de todas as telas fica disponível mesmo sem Chromium instalado.
htmls = {}
for name, path in pages.items():
    if name == 'whatsapp':
        html = (ROOT / 'web/cotacao_whatsapp.html').read_text(encoding='utf-8')
    else:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        html = response.text
    htmls[path] = html
    (OUT / f'{name}.html').write_text(html, encoding='utf-8')

if '--html-only' in sys.argv:
    print('11 telas renderizadas com banco sintético; nenhum navegador iniciado.')
    raise SystemExit(0)

if '--serve' in sys.argv:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Preview(BaseHTTPRequestHandler):
        def do_GET(self):
            from urllib.parse import urlsplit
            path = urlsplit(self.path).path
            if path == '/':
                body = '<html lang="pt-BR"><meta charset="utf-8"><h1>Cotafrete — demonstração sintética</h1>'
                body += ''.join(f'<p><a href="/{name}.html">{name}</a></p>' for name in pages)
                content, mime = body.encode(), 'text/html; charset=utf-8'
            elif path.endswith('.html') and path[1:-5] in pages:
                content, mime = htmls[pages[path[1:-5]]].encode(), 'text/html; charset=utf-8'
            elif path.startswith(('/marca/', '/logos/', '/ajuda/')):
                response = client.get(path)
                content, mime = response.content, response.headers.get('content-type', 'image/png')
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.end_headers()
            self.wfile.write(content)
    print('Prévia somente leitura: http://127.0.0.1:8765 — Ctrl+C para encerrar')
    ThreadingHTTPServer(('127.0.0.1', 8765), Preview).serve_forever()
    raise SystemExit(0)

from playwright.sync_api import sync_playwright

def serve(route):
    from urllib.parse import urlsplit
    url = urlsplit(route.request.url)
    assert route.request.method == 'GET', 'A validação não envia formulários'
    if url.hostname != 'cotafrete.test':
        route.fulfill(status=200, body='')  # Rede externa desativada.
    elif url.path in htmls:
        route.fulfill(status=200, content_type='text/html', body=htmls[url.path])
    else:
        response = client.get(url.path + ('?' + url.query if url.query else ''))
        route.fulfill(status=response.status_code, body=response.content,
                      content_type=response.headers.get('content-type', 'text/plain'))

report = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (390, 1440):
        for theme in ('claro', 'escuro'):
            context = browser.new_context(viewport={'width': width, 'height': 960},
                                          color_scheme='dark' if theme == 'escuro' else 'light',
                                          reduced_motion='reduce')
            context.add_init_script(f"localStorage.setItem('tema', '{theme}')")
            context.route('**/*', serve)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
            for name, path in pages.items():
                errors.clear()
                page.goto('http://cotafrete.test' + path)
                page.wait_for_timeout(100)
                overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
                assert not overflow, (name, width, theme, 'overflow horizontal')
                assert not errors, (name, errors)
                # Contraste computado dos elementos centrais do novo desenho.
                bad = page.evaluate('''() => {
                  const rgb = s => (s.match(/[\\d.]+/g)||[]).map(Number);
                  const lum = c => c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
                  return [...document.querySelectorAll('h1, .sobretitulo, label, .numero b, .numero span')].filter(e=>e.getClientRects().length && e.textContent.trim()).flatMap(e=>{
                    const s=getComputedStyle(e); let node=e, bg;
                    while(node){const c=rgb(getComputedStyle(node).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}node=node.parentElement;}
                    if(!bg) bg=[255,255,255];
                    const a=lum(rgb(s.color)),b=lum(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                    const large=parseFloat(s.fontSize)>=24||(parseFloat(s.fontSize)>=18.66&&parseInt(s.fontWeight)>=700);
                    return ratio < (large?3:4.5) ? [{text:e.textContent.trim().slice(0,60),ratio}] : [];
                  });
                }''')
                assert not bad, (name, width, theme, 'contraste', bad)
                if name != 'whatsapp':
                    assert page.locator('main').count() == 1
                    page.locator('.pular').focus()
                    assert page.locator('.pular').evaluate("e => getComputedStyle(e).outlineStyle") != 'none'
                    page.locator('[data-tema-troca]').click()
                    assert page.locator('html').get_attribute('data-tema') != theme
                    page.locator('[data-tema-troca]').click()
                if name == 'login':
                    assert page.locator('.caminho').evaluate("e => parseFloat(getComputedStyle(e).animationDuration)") < .01
                    page.get_by_label('Seu nome', exact=True).focus()
                    page.keyboard.press('Tab')
                    assert page.locator('button[type=submit]').evaluate('e => e === document.activeElement')
                if name == 'historico':
                    assert page.locator('.historico-vendedor a').count() == 12
                if name in ('login', 'formulario', 'dashboard', 'resultado', 'login-adm'):
                    page.screenshot(path=str(OUT / f'{name}-{width}-{theme}.png'), full_page=True)
                report.append({'tela': name, 'largura': width, 'tema': theme,
                               'overflow': overflow, 'erros': list(errors)})
            context.close()
    browser.close()
(OUT / 'validacao.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'{len(report)} combinações de tela/largura/tema verificadas; capturas em {OUT}')
