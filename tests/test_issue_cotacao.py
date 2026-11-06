import json
from datetime import datetime

from core import issue_cotacao
from orcamento.config import Config

AGORA = datetime(2026, 11, 5, 10)
ERRO = ("TimeoutError: Locator.click: Timeout 30000ms exceeded waiting for '#btnCalcular' "
        "CEP 29090-000 CNPJ 33.592.510/0220-42 VALE S.A. R$ 1.234,56")


def cfg(tmp_path, modo="api"):
    return Config(usuario="u", senha="s", client_id="v", pasta=tmp_path, dry_run=True, headless=True,
                  intervalo_min=5, pasta_programa=tmp_path, ia=modo)


def ia(**v):
    chamadas = []

    def chamar(system, texto):
        chamadas.append(texto)
        return json.dumps({"e_bug": True, "confianca": "alta", "causa": "O botão de calcular mudou de id.",
                           "conserto": "Atualizar o seletor do botão no adapter.", **v}), 500, 100
    chamar.chamadas = chamadas
    return chamar


class Github:
    def __init__(self):
        self.chamadas = []

    def __call__(self, url, headers, json, timeout):
        self.chamadas.append((url, json))
        n = len(self.chamadas)

        class R:
            def raise_for_status(self): pass
            def json(self): return {"number": n, "html_url": f"https://github.com/enzozon/cotafrete/issues/{n}"}
        return R()


def test_bug_com_confianca_alta_abre_issue_sem_dados(tmp_path):
    gh, chamar = Github(), ia()
    url = issue_cotacao.registrar(tmp_path, 501, "camilo", ERRO, "carriers/camilo/adapter.py:88 (cotar)", "tok",
                                  cfg(tmp_path), chamar, gh, AGORA)
    assert url.endswith("/issues/1")
    enviado = gh.chamadas[0][1]
    corpo = json.dumps(enviado, ensure_ascii=False)
    for proibido in ("29090", "33.592", "VALE", "1.234", "btnCalcular"):
        assert proibido not in corpo, proibido
    assert enviado["labels"] == ["robo-cotacao"] and "camilo" in enviado["title"]
    assert "Atualizar o seletor" in corpo and "carriers/camilo/adapter.py:88" in corpo and "/adm/cotacao/501" in corpo
    assert (tmp_path / "ia_uso.csv").exists()


def test_cada_tipo_de_erro_e_analisado_uma_vez_e_repeticao_vira_comentario(tmp_path):
    gh, chamar = Github(), ia()
    for cid in (501, 502, 502):
        issue_cotacao.registrar(tmp_path, cid, "camilo", ERRO.replace("29090", str(cid)), "", "tok",
                                cfg(tmp_path), chamar, gh, AGORA)
    assert len(chamar.chamadas) == 1
    assert [u.rsplit("/", 1)[-1] for u, _ in gh.chamadas] == ["issues", "comments"]


def test_site_fora_ou_confianca_baixa_nao_abre_issue_e_nao_pergunta_de_novo(tmp_path):
    gh = Github()
    chamar = ia(e_bug=False, causa="Site lento.")
    for _ in range(2):
        assert issue_cotacao.registrar(tmp_path, 1, "jadlog", "erro x", "", "tok", cfg(tmp_path), chamar, gh, AGORA) is None
    assert len(chamar.chamadas) == 1 and gh.chamadas == []
    assert issue_cotacao.registrar(tmp_path, 1, "jadlog", "erro y", "", "tok", cfg(tmp_path),
                                   ia(confianca="baixa"), gh, AGORA) is None
    assert gh.chamadas == []


def test_bug_com_confianca_media_abre_issue_e_diz_a_confianca(tmp_path):
    gh = Github()
    assert issue_cotacao.registrar(tmp_path, 1, "jadlog", "erro y", "", "tok", cfg(tmp_path),
                                   ia(confianca="media"), gh, AGORA)
    assert len(gh.chamadas) == 1 and "Confiança da IA: media" in gh.chamadas[0][1]["body"]


def test_sem_ia_nao_registra_veredito(tmp_path):
    gh = Github()
    assert issue_cotacao.registrar(tmp_path, 1, "camilo", ERRO, "", "tok", cfg(tmp_path, "desligada"), ia(), gh, AGORA) is None
    assert not (tmp_path / "erros_cotacao.json").exists() and gh.chamadas == []


def test_onde_aponta_o_nosso_codigo():
    try:
        issue_cotacao.onde.__globals__["json"].loads("{")
    except ValueError as e:
        assert issue_cotacao.onde(e).startswith("core/issue_cotacao.py") or issue_cotacao.onde(e) == ""
    try:
        {}["x"]
    except KeyError as e:
        assert issue_cotacao.onde(e).startswith("tests/") is False


def test_rodar_so_chama_issue_para_erro_sem_frase(monkeypatch):
    from web import app
    chamadas = []
    monkeypatch.setattr(app.issue_cotacao, "em_fundo", lambda *a: chamadas.append(a))
    app._issue_se_novo(1, "generoso", "verificar seu navegador")   # erro conhecido
    app._issue_se_novo(1, "camilo", None)
    assert chamadas == []
    app._issue_se_novo(1, "camilo", "KeyError: 'preco'", "carriers/camilo/adapter.py:9 (ler)")
    assert chamadas and chamadas[0][1:] == (1, "camilo", "KeyError: 'preco'", "carriers/camilo/adapter.py:9 (ler)")


def test_ia_ve_o_call_log_e_duvida_nao_fica_guardada(tmp_path):
    erro = ("TimeoutError: Locator.click: Timeout 45000ms exceeded.\nCall log:\n  - waiting for button\n"
            "  - <div class=\"oferta\">...</div> intercepts pointer events")
    gh = Github()
    chamar = ia(e_bug=False, confianca="baixa", causa="Timeout sem detalhe.")
    assert issue_cotacao.registrar(tmp_path, 1, "jadlog", erro, "", "tok", cfg(tmp_path), chamar, gh, AGORA) is None
    assert "intercepts pointer events" in chamar.chamadas[0]
    assert not (tmp_path / "erros_cotacao.json").exists()   # a próxima ocorrência pergunta de novo
    assert issue_cotacao.registrar(tmp_path, 2, "jadlog", erro, "", "tok", cfg(tmp_path), ia(confianca="alta"), gh, AGORA)
    assert len(gh.chamadas) == 1


def test_duvida_que_ja_estava_no_arquivo_pergunta_de_novo(tmp_path):
    erro = "TimeoutError: Locator.click: Timeout 45000ms exceeded."
    sig = f"jadlog: {issue_cotacao.issue_robo.assinatura(erro)}"
    (tmp_path / "erros_cotacao.json").write_text(json.dumps({issue_cotacao.issue_robo.codigo_de(sig): {
        "e_bug": False, "confianca": "baixa", "causa": "x", "conserto": ""}}), encoding="utf-8")
    gh = Github()
    assert issue_cotacao.registrar(tmp_path, 1, "jadlog", erro, "", "tok", cfg(tmp_path), ia(), gh, AGORA)
