"""Robô que exporta o Excel de vendas do HSE (Venda (pedido) -> Excel).

Selenium + Chrome, como os outros robôs do gerenciador: o servidor é um
Windows Server 2012 R2, que só roda Chrome até a versão 109 (sem Playwright).

Telas, lidas em 01/10/2026:
- login: #usuario, #senha, botão #validarLogin (form #frmLogin);
- menu: Vendas -> Venda (pedido) = newTab('venda.php', 'Venda (pedido)'),
  que abre a tela num iframe;
- filtros: #idTipo (multiselect: "Vendas"), #cdFilial (multiselect: as 3
  empresas — abre só com a matriz marcada), #layout ("Por Pedido"),
  #dtEmissaoIni / #dtEmissaoFim (dd/mm/aaaa, a inicial é obrigatória);
- #btConsultar; resultado em #listaPedidos; com muitas linhas aparece
  "A busca resultou em N registros ... clique aqui para continuar";
- #btExcel: exportToExcel('#filtroAjax', 'excel') -> baixa o arquivo.

Login: com HSE_USUARIO e HSE_SENHA no ambiente (o .env do gerenciador), entra
sozinho. Sem eles, abre a janela e espera alguém entrar (uso à mão/teste).
A senha nunca é gravada em arquivo nem em log.

Compatível com Python 3.8.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

URL_HSE = "https://app.hsesistemas.com.br/"
ESPERA_LOGIN_MANUAL_S = 15 * 60
ESPERA_CONSULTA_S = 180          # um período grande demora
ESPERA_DOWNLOAD_S = 180
EXTENSOES_EXCEL = (".xls", ".xlsx")

# Roda DENTRO do iframe da tela de vendas. Devolve a linha "Filtros:" de antes
# da consulta, para o Python esperar ela mudar.
JS_FILTRAR = r"""
const de = arguments[0], ate = arguments[1];
const d = document, $ = window.jQuery;
const marcar = (id, regra) => {
  const s = d.getElementById(id);
  [...s.options].forEach(o => { o.selected = regra(o.text.trim()); });
  try { $(s).multiselect('refresh'); } catch (e) {}
};
marcar('idTipo', t => t === 'Vendas');
marcar('cdFilial', () => true);
const lay = d.getElementById('layout');
const pp = [...lay.options].find(o => o.text.trim() === 'Por Pedido');
if (pp) lay.value = pp.value;
d.getElementById('dtEmissaoIni').value = de;
d.getElementById('dtEmissaoFim').value = ate;
try { $('.datepicker').hide(); } catch (e) {}
const antes = (d.body.innerText.match(/Filtros:[^\n]*/) || [''])[0];
d.getElementById('btConsultar').click();
return antes;
"""

JS_RESULTADO = r"""
const d = document;
const filtros = (d.body.innerText.match(/Filtros:[^\n]*/) || [''])[0];
const aviso = d.body.innerText.match(/A busca resultou em\s+([\d.]+)\s+registros/);
const t = d.getElementById('listaPedidos');
let linhas = null;
if (t) {
  linhas = [...t.tBodies].flatMap(b => [...b.rows]).filter(r => {
    const c = r.cells[3];
    return r.cells.length > 5 && c && /^\d+$/.test(c.innerText.trim());
  }).length;
}
return {filtros: filtros, aviso: aviso ? aviso[1] : null, linhas: linhas};
"""


class ErroHSE(RuntimeError):
    pass


def ler_quantidade_do_aviso(texto: Optional[str]) -> Optional[int]:
    """'A busca resultou em 4.066 registros' -> 4066."""
    m = re.search(r"A busca resultou em\s+([\d.]+)\s+registros", texto or "")
    return int(m.group(1).replace(".", "")) if m else None


class RoboHSE:
    def __init__(self, pasta_download: "str | Path", usuario: Optional[str] = None,
                 senha: Optional[str] = None, perfil: Optional[str] = None, headless: bool = False,
                 progresso: Callable[[str], None] = print):
        self.pasta_download = Path(pasta_download)
        self.usuario, self.senha = usuario, senha
        self.perfil, self.headless = perfil, headless
        self.progresso = progresso
        self.driver: Any = None

    # -- navegador --------------------------------------------------------
    def abrir(self) -> None:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        self.pasta_download.mkdir(parents=True, exist_ok=True)
        ops = Options()
        ops.add_argument("--no-sandbox")
        ops.add_argument("--disable-dev-shm-usage")
        ops.add_argument("--window-size=1600,900")
        if self.headless:
            ops.add_argument("--headless")
        if self.perfil:
            ops.add_argument(f"--user-data-dir={self.perfil}")
        ops.add_experimental_option("prefs", {
            "download.default_directory": str(self.pasta_download),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        })
        self.driver = webdriver.Chrome(options=ops)
        self.driver.set_page_load_timeout(60)
        try:   # sem janela, o Chrome só baixa com essa permissão explícita
            self.driver.execute_cdp_cmd("Page.setDownloadBehavior",
                                        {"behavior": "allow", "downloadPath": str(self.pasta_download)})
        except Exception:
            pass

    def fechar(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            finally:
                self.driver = None

    # -- telas ------------------------------------------------------------
    def _tem(self, seletor: str) -> bool:
        from selenium.webdriver.common.by import By
        return bool(self.driver.find_elements(By.CSS_SELECTOR, seletor))

    def entrar(self) -> None:
        self.driver.switch_to.default_content()
        self.driver.get(URL_HSE)
        time.sleep(2)
        if not self._tem("#frmLogin"):
            return                                   # sessão do perfil ainda vale
        if self.usuario and self.senha:
            self.progresso("Entrando no HSE...")
            from selenium.webdriver.common.by import By
            campo_u = self.driver.find_element(By.ID, "usuario")
            campo_s = self.driver.find_element(By.ID, "senha")
            campo_u.clear()
            campo_u.send_keys(self.usuario)
            campo_s.clear()
            campo_s.send_keys(self.senha)
            self.driver.find_element(By.ID, "validarLogin").click()
            limite = time.time() + 60
        else:
            self.progresso("Faça o login no HSE na janela do robô...")
            limite = time.time() + ESPERA_LOGIN_MANUAL_S
        while time.time() < limite:
            time.sleep(2)
            if not self._tem("#frmLogin") and self._tem("iframe"):
                return
        if self.usuario and self.senha:
            raise ErroHSE("O HSE não aceitou o login do robô: confira HSE_USUARIO e HSE_SENHA no .env.")
        raise ErroHSE(f"Ninguém fez o login no HSE em {ESPERA_LOGIN_MANUAL_S // 60} minutos.")

    def _frame_vendas(self) -> bool:
        from selenium.webdriver.common.by import By
        self.driver.switch_to.default_content()
        for frame in self.driver.find_elements(By.TAG_NAME, "iframe"):
            self.driver.switch_to.default_content()
            try:
                self.driver.switch_to.frame(frame)
                if self._tem("#idTipo") and self._tem("#btExcel") and self._tem("#dtEmissaoIni"):
                    return True
            except Exception:
                continue
        self.driver.switch_to.default_content()
        return False

    def abrir_vendas(self) -> None:
        if self._frame_vendas():
            return
        self.driver.switch_to.default_content()
        self.driver.execute_script("newTab('venda.php','Venda (pedido)');")
        limite = time.time() + 60
        while time.time() < limite:
            time.sleep(1)
            if self._frame_vendas():
                return
        raise ErroHSE("A tela Venda (pedido) não abriu.")

    def consultar(self, de: _dt.date, ate: _dt.date) -> Optional[int]:
        """Aplica os filtros e consulta. Devolve quantas vendas a tela mostrou."""
        de_txt, ate_txt = de.strftime("%d/%m/%Y"), ate.strftime("%d/%m/%Y")
        antes = self.driver.execute_script(JS_FILTRAR, de_txt, ate_txt)
        limite = time.time() + ESPERA_CONSULTA_S
        while time.time() < limite:
            time.sleep(1)
            r = self.driver.execute_script(JS_RESULTADO)
            if r["filtros"] and r["filtros"] != antes and de_txt in r["filtros"]:
                if r["aviso"]:     # "A busca resultou em 4.066 registros": a lista nem abre
                    return ler_quantidade_do_aviso(f"A busca resultou em {r['aviso']} registros")
                if r["linhas"] is not None:
                    time.sleep(1)
                    return self.driver.execute_script(JS_RESULTADO)["linhas"]
        raise ErroHSE(f"A consulta de {de_txt} a {ate_txt} não terminou em {ESPERA_CONSULTA_S}s.")

    def baixar_excel(self) -> Path:
        antes = {p.name for p in self.pasta_download.iterdir()}
        self.driver.execute_script("document.getElementById('btExcel').click();")
        limite = time.time() + ESPERA_DOWNLOAD_S
        while time.time() < limite:
            time.sleep(1)
            novos = [p for p in self.pasta_download.iterdir()
                     if p.name not in antes and p.suffix.lower() in EXTENSOES_EXCEL]
            baixando = [p for p in self.pasta_download.iterdir() if p.suffix.lower() in (".crdownload", ".tmp")]
            if novos and not baixando:
                return max(novos, key=lambda p: p.stat().st_mtime)
        raise ErroHSE("O Excel não terminou de baixar.")

    # -- tudo -------------------------------------------------------------
    def exportar(self, de: _dt.date, ate: _dt.date) -> Dict[str, Any]:
        self.abrir()
        try:
            self.entrar()
            self.progresso("Abrindo Venda (pedido)...")
            self.abrir_vendas()
            self.progresso(f"Consultando {de:%d/%m/%Y} a {ate:%d/%m/%Y}...")
            linhas = self.consultar(de, ate)
            self.progresso(f"A tela do HSE mostrou {linhas} vendas. Baixando o Excel...")
            arquivo = self.baixar_excel()
            return {"arquivo": str(arquivo), "linhas_tela": linhas}
        finally:
            self.fechar()


def main(argv: Optional[list] = None) -> int:
    """Teste do robô à mão: python -m cruzar_nf.hse_robo --de 29/09/2026 --ate 01/10/2026

    Lê HSE_USUARIO/HSE_SENHA do .env (sem eles, espera o login na janela),
    exporta o período, lê o Excel e mostra o resumo. Não grava nada no Maestro.
    """
    import argparse
    import json
    import sys

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(prog="cruzar_nf.hse_robo", description="Teste do robô do HSE")
    hoje = _dt.date.today()
    ap.add_argument("--de", default=(hoje - _dt.timedelta(days=2)).strftime("%d/%m/%Y"))
    ap.add_argument("--ate", default=hoje.strftime("%d/%m/%Y"))
    a = ap.parse_args(argv)
    de = _dt.datetime.strptime(a.de, "%d/%m/%Y").date()
    ate = _dt.datetime.strptime(a.ate, "%d/%m/%Y").date()
    try:
        res = exportador_do_config({})(de, ate, lambda m: print(m, flush=True))
    except ErroHSE as e:
        print(f"[ERRO] {e}", file=sys.stderr)
        return 1
    from cruzar_nf.vendas_excel import ler_excel_vendas, resumo_excel
    vendas = ler_excel_vendas(res["arquivo"])
    resumo = resumo_excel(vendas)
    print(json.dumps({"arquivo": res["arquivo"], "linhas_na_tela": res["linhas_tela"], "excel": resumo,
                      "bate": res["linhas_tela"] == len(vendas)}, ensure_ascii=False, indent=1))
    for v in vendas[:10]:
        print(f"  {v.get('Filial')} | venda {v.get('Código')} | OC {v.get('Ordem Compra')} | NF {v.get('NF')} | {v.get('Total Líq.')}")
    return 0


def exportador_do_config(config: Dict[str, Any]) -> Callable[..., Dict[str, Any]]:
    """Função exportar(de, ate, progresso) para o sincronizar, montada do ambiente.

    Variáveis (no .env do gerenciador): HSE_USUARIO, HSE_SENHA, HSE_HEADLESS
    (1 = sem janela), HSE_PASTA_DOWNLOAD, HSE_PERFIL.
    """
    pasta = (config.get("pasta_download_hse") or os.environ.get("HSE_PASTA_DOWNLOAD")
             or os.path.join(tempfile.gettempdir(), "cruzar_nf_hse"))
    perfil = config.get("perfil_hse") or os.environ.get("HSE_PERFIL") or None
    headless = str(os.environ.get("HSE_HEADLESS", "0")).strip().lower() in ("1", "true", "sim")

    def exportar(de: _dt.date, ate: _dt.date, progresso: Callable[[str], None] = print) -> Dict[str, Any]:
        robo = RoboHSE(pasta, os.environ.get("HSE_USUARIO"), os.environ.get("HSE_SENHA"),
                       perfil=perfil, headless=headless, progresso=progresso)
        return robo.exportar(de, ate)

    return exportar


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
