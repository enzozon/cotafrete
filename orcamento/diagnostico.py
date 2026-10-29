"""Interpretação do relatório DAV; texto livre só sai para o administrador."""
from __future__ import annotations

import re
import unicodedata


def _normal(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold())
                   if not unicodedata.combining(c))


def diagnostico(dav: dict, *, administrador: bool) -> dict:
    rel = dav.get("relatorio") or ""
    erro = dav.get("erro") or ""
    original = rel + ("\nErro registrado: " + erro if erro and erro not in rel else "")
    texto = _normal(original)
    erros_rel = rel.partition("\nErros:\n")[2]
    falha = _normal(erro + "\n" + erros_rel)
    financeiro = any(t in texto for t in ("financeir", "cliente bloqueado", "pendencia cliente", "titulo vencido"))
    completo = all(t in rel for t in ("Robô de Orçamentos HSE", "\nResultado:", "\nItens:"))
    aviso = True if financeiro or "o hse avisou:" in texto else (False if completo else None)
    estado = dav.get("estado", "")
    incerto = (estado == "incerto" or (estado == "erro" and bool(dav.get("numero")))
               or (estado != "pronto" and any(t in texto for t in (
                   "foi salvo no hse", "salvar foi clicado", "nao reenvie a planilha"))))
    salvamento = ("confirmado" if estado == "pronto" else "incerto" if incerto else
                  "nao_criado" if "orcamento nao criado" in texto or estado == "rejeitado" else "desconhecido")
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
    if salvamento == "incerto":
        motivo = "O orçamento pode já existir no HSE; a conclusão não foi confirmada."
        orientacao = (f"Confira no HSE o orçamento {dav['numero']} e não gere de novo."
                      if dav.get("numero") else
                      "Confira no HSE os orçamentos deste cliente de hoje antes de gerar de novo.")
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
    permitido = "\n".join(filter(None, (titulo, motivo if estado in ("erro", "incerto", "rejeitado") else "",
                                       orientacao if incerto else "",
                                       "Aviso financeiro: consulte o financeiro." if financeiro else "",
                                       "Detalhes técnicos adicionais disponíveis ao administrador." if original else "")))
    return {"categoria": categoria, "titulo": titulo,
            "motivo": motivo_admin if administrador else motivo, "etapa": etapa,
            "orientacao": orientacao, "aviso_financeiro": financeiro, "tem_aviso": aviso,
            "relatorio_visivel": original if administrador else permitido,
            "diagnostico_copiavel": (original if administrador else permitido),
            "salvamento": salvamento}
