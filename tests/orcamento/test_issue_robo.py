import json
from datetime import datetime

from orcamento import issue_robo
from orcamento.fila_diagnostico import FilaDiagnostico

DAV = {"id": 91, "cliente": "1061 - VALE S/A/VALE S.A.",
       "erro": "Item 1: o HSE recusou o produto 76817 a 8300,94 (Margem atualizada) MAQUINA FONTE PLASMA ESAB"}
DIAG = {"culpa": "robo", "confianca": "alta", "causa": "O robô leu o número cedo para VALE a R$ 8.300,94",
        "conserto": "Esperar a linha do item aparecer antes de ler o número."}
AGORA = datetime(2026, 11, 5, 10)


class Github:
    def __init__(self):
        self.chamadas, self.n = [], 0

    def __call__(self, url, headers, json, timeout):
        self.chamadas.append((url, json))
        self.n += 1
        dados = {"number": 200 + self.n, "html_url": f"https://github.com/enzozon/cotafrete/issues/{200 + self.n}"}

        class R:
            def raise_for_status(self): pass
            def json(self): return dados
        return R()


def test_issue_publica_nao_leva_cliente_produto_preco_nem_numeros(tmp_path):
    gh = Github()
    url = issue_robo.registrar_issue(DAV, DIAG, tmp_path, "tok", post=gh, agora=AGORA)
    assert url == "https://github.com/enzozon/cotafrete/issues/201"
    corpo = json.dumps(gh.chamadas[0][1], ensure_ascii=False)
    for proibido in ("VALE", "76817", "8300", "8.300", "MAQUINA", "ESAB", "1061"):
        assert proibido not in corpo, proibido
    assert "Esperar a linha do item" in corpo and "/adm/dav/91" in corpo
    assert gh.chamadas[0][1]["labels"] == ["robo-dav"]


def test_mesmo_erro_comenta_uma_vez_por_envio(tmp_path):
    gh = Github()
    issue_robo.registrar_issue(DAV, DIAG, tmp_path, "tok", post=gh, agora=AGORA)
    issue_robo.registrar_issue(DAV, DIAG, tmp_path, "tok", post=gh, agora=AGORA)   # Diagnosticar de novo
    outro = {**DAV, "id": 93, "erro": DAV["erro"].replace("76817", "11111")}
    assert issue_robo.registrar_issue(outro, DIAG, tmp_path, "tok", post=gh, agora=AGORA).endswith("/201")
    assert [u.rsplit("/", 1)[-1] for u, _ in gh.chamadas] == ["issues", "comments"]


def test_limite_de_issues_novas_por_dia(tmp_path):
    gh = Github()
    urls = [issue_robo.registrar_issue({**DAV, "id": i, "erro": f"erro tipo {chr(97 + i)}"}, DIAG, tmp_path, "tok",
                                       post=gh, agora=AGORA) for i in range(7)]
    assert urls[5:] == [None, None] and len(gh.chamadas) == 5


def test_fila_so_abre_issue_com_token_e_culpa_do_robo(tmp_path, monkeypatch):
    chamadas = []
    monkeypatch.setattr(issue_robo, "registrar_issue", lambda *a, **k: chamadas.append(a) or "https://github.com/x/1")
    fila = FilaDiagnostico(banco=None, pasta=tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN_ISSUES", raising=False)
    fila._issue(DAV, res := dict(DIAG))
    assert chamadas == [] and "issue" not in res
    monkeypatch.setenv("GITHUB_TOKEN_ISSUES", "tok")
    fila._issue(DAV, res := {**DIAG, "confianca": "baixa"})
    assert chamadas == []
    fila._issue(DAV, res := dict(DIAG))
    assert res["issue"] == "https://github.com/x/1"


def test_assinatura_vem_do_relatorio_quando_a_coluna_erro_esta_vazia(tmp_path):
    rel = "Robô de Orçamentos HSE\nResultado: ERRO\nErros:\nERRO: Item 1: o HSE recusou o produto 76817 (Margem atualizada)\n"
    dav = {"id": 91, "cliente": "VALE", "erro": "", "relatorio": rel}
    gh = Github()
    for causa in ("O robô leu cedo.", "Leitura precoce do número."):   # a IA escreve diferente a cada vez
        issue_robo.registrar_issue({**dav, "id": 91 if causa.startswith("O") else 93}, {**DIAG, "causa": causa},
                                   tmp_path, "tok", post=gh, agora=AGORA)
    assert [u.rsplit("/", 1)[-1] for u, _ in gh.chamadas] == ["issues", "comments"]
    assert "Item <n>: o HSE recusou o produto <n>" in gh.chamadas[0][1]["title"]
    assert issue_robo.erro_do_dav({"relatorio": "Resultado: DRY_RUN ok"}) == "DRY_RUN ok"
    assert issue_robo.erro_do_dav({}) == ""


def test_nome_de_tipo_python_fica_e_texto_entre_aspas_sai():
    assert "'NoneType'" in issue_robo.limpar("TypeError: 'NoneType' object is not subscriptable")
    assert "'KeyError'" in issue_robo.limpar("recebi 'KeyError' aqui")
    for segredo in ("'VALE'", "'Rua das Flores'", "'33592510'"):
        assert segredo not in issue_robo.limpar(f"cliente {segredo} recusado")
