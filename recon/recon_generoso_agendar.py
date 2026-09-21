"""Mede a tela de AGENDAR COLETA do portal da Generoso. READ-ONLY.

    python recon/recon_generoso_agendar.py

Loga, abre a lista de cotações, entra na mais recente que ainda esteja
valida, clica em "Agendar coleta" e despeja o DOM do painel inteiro — campo
de data, horario limite, o checkbox do almoco (marcado e desmarcado) e a
observacao.

PARA ANTES de "Continuar para o agendamento". Nada e agendado, nada e
confirmado, nenhuma coleta e pedida. O unico clique que muda estado e o do
checkbox do almoco, que e estado de tela e volta ao normal ao fechar a aba.

Existe porque os prints do Enzo (21/09/2026) mostram o painel mas nao o DOM,
e neste projeto seletor deduzido de print ja quebrou duas vezes em silencio
— a Della Volpe e o popup de aviso do SSW/Camilo. Os prints dizem O QUE
existe; so o DOM diz COMO clicar. E aqui o campo de data nao e um
<input type="date">: e um popover com calendario proprio e um select de
horario de 30 em 30 minutos, entao `fill()` nao serve.

Saida em recon_out/generoso_agendar/ (pasta no .gitignore).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(override=False)

from carriers.generoso.adapter import GenerosoAdapter   # noqa: E402

SAIDA = RAIZ / "recon_out" / "generoso_agendar"

# A lista de cotacoes da conta. O nome sai de `_e_busca_de_cnpj` no adapter,
# que precisa EXCLUIR esta rota para nao confundi-la com a busca de CNPJ —
# ou seja, ela ja era conhecida, so nunca tinha sido visitada pelo robo.
URL_LISTA = "https://cliente.generoso.com.br/cotacao/listar"

# Candidatos ao botao que abre o agendamento, na tela da cotacao.
BOTOES_AGENDAR = ('button:has-text("Agendar coleta")',
                  'text="Agendar coleta"',
                  '[data-slot="button"]:has-text("Agendar")')

# Candidatos a cada peca do painel. Varios por peca de proposito: o recon
# existe para descobrir QUAL funciona, nao para confirmar um palpite.
PECAS = {
    "campo_data": ('input[name="collectDate"]', 'input[type="date"]',
                   'button:has-text(" às ")', '[data-slot="popover-trigger"]',
                   'input[placeholder*="/"]'),
    "checkbox_almoco": ('input[type="checkbox"]', '[role="checkbox"]',
                        '[data-slot="checkbox"]'),
    "selects": ('select', '[data-slot="select-trigger"]', '[role="combobox"]'),
    "observacao": ('textarea', 'input[name="observation"]',
                   '[placeholder*="bserva"]'),
    "continuar": ('button:has-text("Continuar")',
                  'button:has-text("Continuar para o agendamento")'),
}

# O painel inteiro, para ler com calma depois. Radix monta popover e menu num
# portal no fim do <body>, entao nao basta pegar o <form>.
JS_PAINEL = """() => {
  const alvos = [...document.querySelectorAll(
      '[role="dialog"], [data-slot="dialog-content"], [data-state="open"],'
      + ' [data-radix-popper-content-wrapper], form')];
  return alvos.map(e => e.outerHTML).filter(h => h.length < 200000);
}"""

# Todo campo do painel, com o que der para identificar. `name` e o ultimo
# recurso do adapter, mas e o unico que sobrevive a troca de texto do site.
JS_CAMPOS = """() => [...document.querySelectorAll(
    'input, textarea, select, button, [role="checkbox"], [role="combobox"]')]
  .filter(e => e.offsetParent !== null)
  .map(e => ({
      tag: e.tagName.toLowerCase(),
      type: e.getAttribute('type'),
      name: e.getAttribute('name'),
      id: e.id || null,
      slot: e.getAttribute('data-slot'),
      role: e.getAttribute('role'),
      placeholder: e.getAttribute('placeholder'),
      checked: e.getAttribute('aria-checked') ?? (e.checked ?? null),
      valor: (e.value ?? '').slice(0, 40),
      texto: (e.innerText || '').trim().slice(0, 60),
  }))"""


def _medir(page, achados: dict, etapa: str) -> None:
    """Fotografa o DOM inteiro numa etapa. Nunca levanta: um seletor que
    falha e um DADO do recon, nao uma falha do recon."""
    achados[etapa] = {"campos": page.evaluate(JS_CAMPOS), "pecas": {}}
    for peca, seletores in PECAS.items():
        achados[etapa]["pecas"][peca] = {}
        for sel in seletores:
            try:
                loc = page.locator(sel)
                n = loc.count()
                achados[etapa]["pecas"][peca][sel] = {
                    "quantos": n,
                    "textos": [t.strip()[:60]
                               for t in loc.all_inner_texts()][:8] if n else [],
                }
            except Exception as exc:
                achados[etapa]["pecas"][peca][sel] = {
                    "erro": f"{type(exc).__name__}: {exc}"[:200]}


def main() -> int:
    from playwright.sync_api import sync_playwright

    SAIDA.mkdir(parents=True, exist_ok=True)
    adapter = GenerosoAdapter()
    achados: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(**adapter.opcoes_do_navegador())
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1400, "height": 1400}).new_page()
        page.set_default_timeout(adapter.timeout_ms)
        try:
            adapter._entrar(page)

            # ------------------------------------------- 1. lista de cotacoes
            page.goto(URL_LISTA, wait_until="domcontentloaded")
            page.wait_for_timeout(4_000)
            page.screenshot(path=str(SAIDA / "1_lista.png"), full_page=True)
            (SAIDA / "lista.html").write_text(page.content(), encoding="utf-8")
            achados["lista"] = {
                "url": page.url,
                "texto": page.locator("body").inner_text()[:3000],
                "links": page.eval_on_selector_all(
                    "a[href]", "es => es.map(e => e.getAttribute('href'))"
                               ".filter(h => h && h.includes('cota')).slice(0,40)"),
            }

            # ------------------------------------------ 2. abrir uma cotacao
            # A lista NAO tem link por cotacao: medido em 21/09/2026, os
            # unicos <a> da pagina sao /cotacao e /cotacao/listar. Cada linha
            # e um <tr data-slot="context-menu-trigger"> com `cursor-pointer`,
            # e tem um botao "⋮" ("Open menu", aria-haspopup=menu) na ultima
            # celula. Ou seja: nao da para montar a URL da cotacao a partir do
            # numero — tem que clicar na linha.
            #
            # A PRIMEIRA linha e a mais recente, e portanto a com mais chance
            # de ainda estar dentro da validade.
            linha = page.locator('tr[data-slot="context-menu-trigger"]').first
            if not linha.count():
                achados["parou"] = ("nenhuma linha de cotacao na lista — "
                                    "ver lista.html")
                return 0

            achados["primeira_linha"] = linha.inner_text()[:300]
            antes = page.url

            # Primeiro o menu "⋮": se "Agendar coleta" estiver AQUI, o robo
            # nem precisa abrir a cotacao — e um passo a menos no portal.
            try:
                linha.locator('button[aria-haspopup="menu"]').first.click()
                page.wait_for_timeout(1_500)
                page.screenshot(path=str(SAIDA / "2a_menu_linha.png"))
                achados["menu_da_linha"] = page.locator(
                    '[role="menuitem"]').all_inner_texts()
                page.keyboard.press("Escape")
                page.wait_for_timeout(800)
            except Exception as exc:
                achados["menu_da_linha"] = f"{type(exc).__name__}: {exc}"[:200]

            linha.click()
            page.wait_for_timeout(4_000)
            achados["clicar_na_linha_navegou"] = page.url != antes
            page.screenshot(path=str(SAIDA / "2_cotacao.png"), full_page=True)
            (SAIDA / "cotacao.html").write_text(page.content(), encoding="utf-8")
            achados["cotacao"] = {"url": page.url,
                                  "texto": page.locator("body").inner_text()[:3000]}

            # --------------------------------------- 3. abrir o agendamento
            gatilho = None
            for sel in BOTOES_AGENDAR:
                try:
                    if page.locator(sel).first.is_visible(timeout=2_000):
                        gatilho = sel
                        break
                except Exception:
                    continue
            if gatilho is None:
                achados["parou"] = ("nenhum botao 'Agendar coleta' visivel — "
                                    "ver cotacao.png. Pode ser cotacao vencida.")
                return 0

            achados["gatilho_agendar"] = gatilho
            page.locator(gatilho).first.click()
            page.wait_for_timeout(3_000)
            page.screenshot(path=str(SAIDA / "3_painel.png"), full_page=True)
            _medir(page, achados, "painel_fechado_almoco")
            (SAIDA / "painel.html").write_text(
                "\n\n<!-- ===== -->\n\n".join(page.evaluate(JS_PAINEL) or []),
                encoding="utf-8")

            # ------------------------------- 4. o calendario e o horario
            # O campo de data NAO e <input type="date">: e um popover com
            # calendario proprio. Abrir para medir o que aparece.
            for sel in PECAS["campo_data"]:
                try:
                    alvo = page.locator(sel).first
                    if alvo.is_visible(timeout=1_500):
                        alvo.click()
                        page.wait_for_timeout(2_000)
                        page.screenshot(path=str(SAIDA / "4_calendario.png"),
                                        full_page=True)
                        _medir(page, achados, "calendario_aberto")
                        (SAIDA / "calendario.html").write_text(
                            "\n\n<!-- ===== -->\n\n".join(
                                page.evaluate(JS_PAINEL) or []),
                            encoding="utf-8")
                        achados["campo_data_usado"] = sel

                        # QUAIS dias o calendario deixa escolher. `data-day`
                        # vem em ISO na propria celula (medido:
                        # td[role="gridcell"][data-day="2026-09-23"]), e os
                        # indisponiveis carregam data-disabled="true". Sem
                        # saber disso o robo clicaria num sabado e o painel
                        # nao sairia do lugar — sem erro nenhum na tela.
                        achados["dias"] = page.evaluate(
                            """() => [...document.querySelectorAll(
                                 'td[role="gridcell"][data-day]')]
                               .map(td => ({
                                   dia: td.getAttribute('data-day'),
                                   bloqueado: td.getAttribute('data-disabled')
                                              === 'true'
                                     || !!td.querySelector('button[disabled]'),
                                   fora_do_mes:
                                     td.getAttribute('data-outside') === 'true',
                               }))""")

                        # O "Coletar ate as" NAO tem <select> nativo por tras
                        # (os do almoco tem). E Radix puro: as opcoes so
                        # existem no DOM depois do clique, num portal.
                        try:
                            page.locator(
                                '[data-slot="select-trigger"]:has-text('
                                '"Coletar")').first.click()
                            page.wait_for_timeout(1_500)
                            page.screenshot(
                                path=str(SAIDA / "4b_horarios.png"))
                            achados["horarios"] = page.locator(
                                '[role="option"]').all_inner_texts()
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(800)
                        except Exception as exc:
                            achados["horarios"] = \
                                f"{type(exc).__name__}: {exc}"[:200]

                        page.keyboard.press("Escape")
                        page.wait_for_timeout(1_000)
                        break
                except Exception:
                    continue

            # ------------------------------ 5. o almoco, que revela 2 selects
            # Com o checkbox desmarcado os dois selects NAO EXISTEM no DOM —
            # e a diferenca entre as duas medicoes que prova isso.
            for sel in PECAS["checkbox_almoco"]:
                try:
                    caixa = page.locator(sel).first
                    if caixa.is_visible(timeout=1_500):
                        caixa.click()
                        page.wait_for_timeout(2_000)
                        page.screenshot(path=str(SAIDA / "5_almoco.png"),
                                        full_page=True)
                        _medir(page, achados, "almoco_marcado")
                        (SAIDA / "almoco.html").write_text(
                            "\n\n<!-- ===== -->\n\n".join(
                                page.evaluate(JS_PAINEL) or []),
                            encoding="utf-8")
                        achados["checkbox_usado"] = sel
                        break
                except Exception:
                    continue

            achados["parou"] = ("de proposito, ANTES de 'Continuar para o "
                                "agendamento'. Nenhuma coleta foi pedida.")
        except Exception as exc:
            achados["erro"] = f"{type(exc).__name__}: {exc}"
            try:
                page.screenshot(path=str(SAIDA / "erro.png"), full_page=True)
            except Exception:
                pass
        finally:
            (SAIDA / "achados.json").write_text(
                json.dumps(achados, ensure_ascii=False, indent=2),
                encoding="utf-8")
            browser.close()

    print(json.dumps({k: v for k, v in achados.items() if k != "lista"},
                     ensure_ascii=False, indent=2)[:3000])
    print(f"\nsaida em {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
