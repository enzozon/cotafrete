"""Interpretação do relatório DAV; texto livre só sai para o administrador."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable

# Ligada por web/app.py: id do envio → planilha guardada. Com ela, as células indicadas saem no
# endereço daquela planilha (Nº na coluna A, mais ou menos itens); sem ela, no do modelo antigo.
PLANILHA: Callable[[int], Path] | None = None


@lru_cache(maxsize=256)
def _layout(caminho: str, _mtime: int) -> tuple[int, int]:
    from orcamento.planilha import layout
    return layout(Path(caminho))


def _tradutor(dav: dict) -> Callable[[str], str]:
    """Só abre a planilha se houver célula a indicar (o painel diagnostica todos os envios)."""
    def real(celula: str) -> str:
        try:
            p = PLANILHA(int(dav["id"]))
            desloc, rodape = _layout(str(p), p.stat().st_mtime_ns)
        except Exception:  # noqa: BLE001 — sem hook, sem arquivo ou arquivo ilegível: endereço do modelo
            return celula
        from orcamento.planilha import traduzir
        return traduzir(celula, desloc, rodape)
    return real


def _normal(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold())
                   if not unicodedata.combining(c))


def _financeiro(texto: str) -> bool:
    texto = " ".join(_normal(texto).split())
    return (any(t in texto for t in ("pendencia financeira", "cliente bloqueado", "pendencia cliente",
                                     "setor financeiro", "titulo vencido", "titulos vencidos"))
            or bool(re.search(r"\bdf\d+\b.*(?:venc|valor)", texto)))


def _origem(mensagens: list[str], rejeitado: bool, real: Callable[[str], str] = lambda c: c) -> dict:
    """`real` leva uma célula do modelo antigo (24 itens, sem o Nº) ao endereço na planilha do envio."""
    campos, origens = [], set()
    comparar = False
    for mensagem in mensagens:
        if _financeiro(mensagem):
            continue
        t = _normal(mensagem).strip().removeprefix("erro: ").removeprefix("falha durante a criacao no hse: ")
        origem, referencias, da_mensagem = "desconhecida", [], False
        if re.match(r"^(?:o )?(?:hse esta fora|hse fora do ar|hse recusou o login|hse sem login|"
                    r"robo do hse sem login|login recusado \(confira hse_usuario/hse_senha)", t):
            origem = "acesso_hse"
        elif re.match(r"^(?:item \d+: tela ficou com qtd/preco |nao consegui manter forma '|"
                      r"tela abriu na filial \d+, esperado \d+)", t):
            origem = "automacao"
        elif (t.startswith("nao foi possivel abrir a planilha:") or
              (rejeitado and t in ("envie um arquivo .xlsx (a planilha-base v3).", "o arquivo passa de 5 mb."))):
            origem = "planilha"
        elif t.startswith("cliente sem endereco cadastrado no hse"):
            origem, referencias = "cadastro_hse", ["B30"]
        elif t.startswith("local de entrega"):
            referencias, comparar = ["B30"], True
        elif re.match(r"^(cliente|vendedor)\b", t) and any(s in t for s in (
                "nao encontrado no hse", "corresponde a varios cadastros")):
            referencias = ["B31" if t.startswith("cliente") else "B33"]
            comparar = True
        else:
            item = re.match(r"item (\d+):\s*(.*)", t)
            if item and int(item[1]) >= 1:
                detalhe = item[2]
                # O campo vem antes do valor interpolado; palavras dentro do valor não são estrutura.
                for padrao, coluna in ((r"^quantidade (?:invalido|invalida|deve)", "B"),
                        (r"^(?:valor unitario|valor de venda unitario|preco) ", "J"),
                        (r"^codigo ", "K"), (r"^ncm ", "L"), (r"^origem (?:invalido|invalida|deve)", "M"),
                        (r"^icms (?:invalido|invalida|deve)", "N"), (r"^grupo ", "P"),
                        (r"^descricao no dav com \d+ caracteres", "R"), (r"^descricao deve ser diferente", "O")):
                    if re.match(padrao, detalhe):
                        referencias = [f"{coluna}{int(item[1]) + 1}"]
                        break
                faltantes = re.match(r"^produto novo sem ((?:ncm|custo|grupo|marca)(?:, (?:ncm|custo|grupo|marca))*)", detalhe)
                if faltantes:
                    referencias = [f"{coluna}{int(item[1]) + 1}" for campo, coluna in (("ncm", "L"), ("grupo", "P"))
                                   if campo in faltantes[1].split(", ")]
                estrutura = re.sub(r"^valor unitario \(coluna [a-z]+\) ", "valor unitario ", detalhe).partition(" (")[0]
                if referencias and any(s in estrutura for s in ("invalido", "invalida", "deve", "sem ",
                        "abaixo do minimo", "caracteres", "nao encontrado", "nao existe", "inativo",
                        "preencha")):
                    origem = "planilha"
                    if any(s in estrutura for s in ("nao encontrado", "nao existe", "inativo")):
                        origem, comparar = "desconhecida", True
                else:
                    referencias = []
            else:
                # a célula real vem na mensagem: o rodapé anda com o número de itens e com o Nº
                for padrao in (r"^cliente \(([a-z]+\d+)\).*obrigatorio", r"^vendedor \(([a-z]+\d+)\).*obrigatorio",
                               r"^prazo de entrega \(([a-z]+\d+)\).*(invalido|obrigatorio)",
                               r"^forma de pagamento \(([a-z]+\d+)\).*desconhecida",
                               r"^frete \(([a-z]+\d+)\).*deve", r"^filial \(([a-z]+\d+)\) invalida"):
                    if m := re.search(padrao, t):
                        origem, referencias, da_mensagem = "planilha", [m[1].upper()], True
                        break
                else:
                    if t.startswith("filial invalida"):   # mensagem antiga, sem a célula
                        origem, referencias = "planilha", ["B37"]
        origens.add(origem)
        referencias = referencias if da_mensagem else [real(c) for c in referencias]
        campos.extend(c for c in referencias if c not in campos)
    origem = next(iter(origens)) if len(origens) == 1 else "desconhecida"
    if not mensagens and rejeitado:
        origem = "planilha"
    rotulo, onde, como = {
        "planilha": ("Preenchimento da planilha", "PLANILHA-BASE v3",
                     "Corrija os campos indicados na planilha e confira novamente."),
        "cadastro_hse": ("Cadastro no HSE", "Cadastro do cliente no HSE",
                         "Peça a correção do cadastro no HSE e confira novamente a planilha."),
        "acesso_hse": ("Acesso ao HSE", "Disponibilidade e login do HSE",
                       "Peça a Enzo, Allan ou Lucas para conferir o acesso ao HSE, informando o número do envio."),
        "automacao": ("Falha reconhecida da automação", "Detalhes técnicos deste envio",
                      "Procure Enzo, Allan ou Lucas, levando o número do envio."),
        "desconhecida": ("Causa não identificada", "Detalhes do envio e resultado no HSE",
                         "Procure Enzo, Allan ou Lucas, levando o número do envio; confira o resultado no HSE antes de reenviar."),
    }[origem]
    if origem == "planilha" and rejeitado and not campos:
        como = "Envie a PLANILHA-BASE v3 em .xlsx, com até 5 MB."
    if comparar:
        if origem == "desconhecida":
            rotulo = "Conferir planilha e cadastro HSE"
        onde = "Compare a planilha com o cadastro correspondente no HSE"
        como = "Compare os campos indicados com o cadastro no HSE e corrija o dado divergente antes de conferir novamente."
    return dict(origem=origem, origem_rotulo=rotulo, onde_conferir=onde, como_corrigir=como, campos=campos)


def diagnostico(dav: dict, *, administrador: bool) -> dict:
    rel = dav.get("relatorio") or ""
    erro = dav.get("erro") or ""
    erros_conferencia = []
    if dav.get("estado") == "rascunho" and dav.get("conferencia") == "erros":
        from orcamento.processador import Conferencia
        try:
            conf = Conferencia.de_json(dav.get("conferencia_relatorio") or "")
            erros_conferencia = [e for e in conf.erros if isinstance(e, str)]
        except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
            pass  # conferência legada sem formato conhecido não expõe texto livre
    original = rel + ("\nErro registrado: " + erro if erro and erro not in rel else "")
    texto = _normal(original)
    erros_rel = rel.partition("\nErros:\n")[2]
    falha = _normal(erro + "\n" + erros_rel + "\n" + "\n".join(erros_conferencia))
    # Só as linhas "ERRO:" que o próprio robô escreve: é com elas que o vendedor corrige a planilha
    # (desconto, vendedor, endereços). Continuações e trechos financeiros ficam para o administrador.
    erros_robo = [linha[6:].strip() for linha in erros_rel.splitlines()
                  if linha.startswith("ERRO: ") and not _financeiro(linha)]
    completo = all(t in rel for t in ("Robô de Orçamentos HSE", "\nResultado:", "\nItens:"))
    # pendência financeira é normal (ex.: VALE): o DAV criado fica Pronto, sem aviso
    avisos_hse = [l for l in texto.splitlines() if "o hse avisou:" in l and not _financeiro(l)]
    aviso = True if avisos_hse else (False if completo else None)
    estado = dav.get("estado", "")
    resultado = _normal("\n".join(l for l in rel.splitlines() if l.startswith("Resultado:")) + "\n" + erro)
    simulacao = estado == "simulado" or bool(re.search(r"^Modo: DRY_RUN", rel, re.M))
    salvo = not simulacao and (bool(re.search(r"\borcamento \S+ foi salvo no hse", resultado))
                               or "salvar foi clicado" in resultado or "nao reenvie a planilha" in resultado)
    incerto = (estado == "incerto" or (estado == "erro" and bool(dav.get("numero")))
               or (estado == "erro" and salvo))
    salvamento = ("confirmado" if estado == "pronto" else "incerto" if incerto else
                  "nao_criado" if simulacao or "orcamento nao criado" in resultado or "nada foi criado" in resultado
                                  or estado == "rejeitado" else "desconhecido")
    categoria, etapa = "desconhecido", None
    motivo = "Motivo não identificado; consulte os detalhes disponíveis ou o responsável pelo robô."
    orientacao = "Consulte o responsável pelo robô antes de reenviar se houver dúvida sobre o salvamento."
    if "local de entrega" in falha:
        categoria, etapa = "endereco", "Local de entrega"
        motivo = "O local de entrega informado não foi aceito pelo HSE."
        orientacao = "Compare o local de entrega da planilha com o cadastro do cliente no HSE e corrija o arquivo."
    elif any(t in falha for t in ("hse esta fora", "hse fora do ar", "hse recusou o login", "hse sem login")):
        categoria, etapa = "acesso_hse", "Acesso ao HSE"
        motivo = "Não foi possível acessar o HSE para concluir esta tentativa."
        orientacao = "Peça ao responsável para conferir a disponibilidade e o acesso ao HSE."
    elif estado == "rejeitado":
        categoria, etapa = "planilha", "Validação da planilha"
        motivo = "A planilha não foi aceita e não foi enviada ao HSE."
        orientacao = "Use a PLANILHA-BASE v3 em .xlsx, até 5 MB, corrija os dados e confira novamente."
    if categoria == "desconhecido" and erros_robo:
        motivo = "; ".join(erros_robo)
    novos = _origem(erro.splitlines() + erros_robo + erros_conferencia, estado == "rejeitado", _tradutor(dav))
    if categoria == "desconhecido" and not erros_robo and estado in ("erro", "rejeitado"):
        # Motivo pela origem reconhecida; nunca o texto livre do erro (allowlist do vendedor).
        motivo = {"automacao": "A automação falhou ao preencher o HSE; a planilha não indica erro.",
                  "cadastro_hse": "O cliente está sem endereço cadastrado no HSE.",
                  "planilha": "A planilha tem dados que precisam de correção.",
                  }.get(novos["origem"], "Um dado da planilha não confere com o cadastro do HSE."
                        if novos["campos"] else motivo)
        if novos["origem"] != "desconhecida" or novos["campos"]:
            orientacao = novos["como_corrigir"]
    if salvamento == "nao_criado" and categoria == "desconhecido" and not simulacao:
        orientacao = ("Nada foi criado no HSE. Corrija a planilha e envie de novo."
                      if novos["origem"] == "planilha" else novos["como_corrigir"])
    if estado == "rascunho" and erros_conferencia and novos["origem"] == "planilha":
        categoria, etapa = "planilha", "Validação da planilha"
        motivo = "A conferência encontrou dados da planilha que precisam de correção."
    elif estado == "rascunho" and erros_conferencia:  # a conferência já disse a causa (#105, #117)
        motivo = "; ".join(t for t in erros_conferencia if not _financeiro(t)) or motivo
    if salvamento == "incerto":
        motivo = "O orçamento pode já existir no HSE; a conclusão não foi confirmada."
        try:
            data = datetime.fromisoformat(dav.get("iniciado_em") or dav.get("criado_em") or "").strftime("%d/%m/%Y")
        except ValueError:
            data = ""
        orientacao = (f"Confira no HSE o orçamento {dav['numero']} e não gere de novo."
                      if dav.get("numero") else
                      f"Confira no HSE os orçamentos deste cliente{' de ' + data if data else ''} antes de gerar de novo.")
        novos.update(origem="sem_confirmacao", origem_rotulo="Resultado sem confirmação",
                     onde_conferir="Orçamentos deste cliente no HSE", como_corrigir=orientacao)
    titulos = {"pronto": "Seu DAV está pronto", "fila": "Na fila", "gerando": "Gerando no HSE",
               "rascunho": "Confira os dados antes de gerar", "simulado": "Simulação: nada salvo",
               "rejeitado": "Planilha não aceita"}
    titulo = ("Confira no HSE" if incerto else titulos.get(estado,
              "O DAV não foi criado" if salvamento == "nao_criado" else "Falha registrada"))
    if administrador and (erro or erros_rel):
        motivo_admin = "\n".join(dict.fromkeys(t.strip() for t in (erro, erros_rel) if t.strip()))
    else:
        motivo_admin = motivo
    # Allowlist: um formato novo nunca torna texto livre visível ao vendedor.
    trecho_itens = rel.partition("\nItens:\n")[2].split("\nDetalhes:\n")[0].split("\nErros:\n")[0]
    itens = [linha for linha in trecho_itens.splitlines()
             if re.fullmatch(r"Item \d+: usou produto existente \d+ - .+ \((pelo código informado|encontrado pela descrição)\)", linha)
             and not _financeiro(linha)]
    mostrar_erros = estado in ("erro", "incerto", "rejeitado")
    erros_extra = [e for e in erros_robo if e != motivo] if mostrar_erros else []
    permitido = "\n".join(filter(None, (titulo, "\n".join(itens), motivo if mostrar_erros else "",
                                       "\n".join(erros_extra),
                                       orientacao if incerto else "",
                                       "Detalhes técnicos adicionais disponíveis ao administrador." if original else "")))
    return {"categoria": categoria, "titulo": titulo,
            "motivo": motivo_admin if administrador else motivo, "etapa": etapa,
            "orientacao": orientacao, "tem_aviso": aviso,
            "relatorio_visivel": original if administrador else permitido,
            "diagnostico_copiavel": (original if administrador else permitido),
            "salvamento": salvamento, "itens": itens, **novos}
