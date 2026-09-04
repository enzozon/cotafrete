"""A ficha da cotação: os dados que geraram aquele preço, desenhados UMA vez.

Morava dentro de `web/app.py` e saiu de lá em 04/09/2026, quando o painel
ganhou a tela de uma cotação (`/adm/cotacao/N`): passaram a ser DUAS telas
mostrando a mesma ficha — a do vendedor e a de quem administra — e
`web/adm.py` não pode importar `web/app.py`, porque é o app que registra as
rotas do adm e o import de volta seria circular.

Uma cópia em cada arquivo funcionaria hoje e mentiria no primeiro dia em que
alguém corrigisse um rótulo de um lado só: as duas telas passariam a descrever
cargas diferentes a partir da MESMA linha do banco — divergência que ninguém
percebe olhando uma tela de cada vez.

Tudo aqui é FUNÇÃO PURA: entra o dicionário da cotação (como o banco devolve),
sai string. Nenhuma consulta, nenhuma requisição.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from web.layout import e, moeda


def kg(valor) -> str:
    """Peso do jeito que se lê aqui: vírgula, sem zeros à toa.

    4,000 vira "4" e 3,333333… vira "3,333". `:f` em vez de str() porque
    normalize() devolve Decimal('1E+2') para 100, e "1E+2 kg" não quer dizer
    nada para quem está conferindo a carga.

    Aceita o que vier do banco (str ou Decimal) e devolve o original se não
    for número: uma linha da ficha com o valor cru ainda informa; uma tela
    que estoura no meio, não."""
    try:
        redondo = Decimal(str(valor)).quantize(Decimal("0.001"),
                                               rounding=ROUND_HALF_UP)
    except (ArithmeticError, TypeError, ValueError):
        return str(valor)
    return f"{redondo.normalize():f}".replace(".", ",")


def peso_por_volume(c: dict) -> Decimal | None:
    """Peso de UM volume. O banco guarda o TOTAL (ver /cotar).

    São grandezas diferentes com o mesmo nome, e é isso que torna o erro
    perigoso: o formulário pede "Peso de UM volume", a coluna peso_kg guarda
    qtd × unitário, e 36 kg é um peso tão válido quanto 12. Nada na tela
    denuncia — a cotação sai com o triplo da carga e o preço vem junto."""
    try:
        qtd = int(c["quantidade"])
        return Decimal(str(c["peso_kg"])) / qtd if qtd > 0 else None
    except (ArithmeticError, TypeError, ValueError):
        return None


def quem_e(nome: str | None, cnpj: str | None) -> str:
    """Nome da empresa quando a busca por CNPJ funcionou; senão só o CNPJ."""
    return f"{nome}\nCNPJ: {cnpj}" if nome else f"CNPJ: {cnpj}"


def pagador_da_cotacao(c: dict) -> tuple[str, str, str]:
    """Sigla, lado e quem é — tudo derivado do tipo de frete.

    A salvaguarda no fim existe para as cotações anteriores a 20/08/2026, que
    não têm `tipo_frete` guardado: elas caem em CIF, que é como o formulário
    vinha preenchido, e o CNPJ sai da ponta certa em vez de virar "None"."""
    fob = (c.get("tipo_frete") or "cif") == "fob"
    sigla, lado = ("FOB", "DESTINATÁRIO") if fob else ("CIF", "REMETENTE")
    ponta = "destinatario" if fob else "remetente"
    nome = c.get("nome_pagador") or c.get(f"nome_{ponta}")
    cnpj = c.get("cnpj_pagador") or c.get(f"cnpj_{ponta}")
    return sigla, lado, quem_e(nome, cnpj)


def frete_por_extenso(c: dict) -> str:
    """"CIF — paga o remetente". A sigla sozinha nao diz nada para quem esta
    conferindo dois orcamentos parecidos na mesa."""
    sigla, lado, _ = pagador_da_cotacao(c)
    return f"{sigla} — paga o {lado.lower()}"


def quando(iso: str | None) -> str:
    return _formata_data(iso, "%d/%m/%Y às %H:%M")


def hora(iso: str | None) -> str:
    """Só o relógio. Para a linha do tempo, onde o dia já está no cabeçalho e
    repeti-lo em cada linha só empurraria o número para fora da tela."""
    return _formata_data(iso, "%H:%M:%S")


def _formata_data(iso: str | None, molde: str) -> str:
    """`criado_em` e `respondido_em` são TEXTO no banco. Uma linha torta sai
    como veio, em vez de derrubar a tela inteira."""
    try:
        return datetime.fromisoformat(iso).strftime(molde)
    except (TypeError, ValueError):
        return iso or ""


def dado(rotulo: str, valor, detalhe: str = "") -> str:
    """Um par rótulo/valor da ficha.

    Campo vazio vira travessão em vez de sumir: uma linha que desaparece faz
    o vendedor achar que aquele dado não existe no sistema."""
    extra = f'<span class="pouco">{e(detalhe)}</span>' if detalhe else ""
    return (f'<div><label>{e(rotulo)}</label>'
            f'<div class="val">{e(valor) or "—"}{extra}</div></div>')


def lugar(cidade: str | None, uf: str | None) -> str:
    return f"{cidade}/{uf}" if cidade and uf else (cidade or uf or "")


def parte(rotulo: str, nome: str | None, cnpj: str | None) -> str:
    """Razão social em cima, CNPJ embaixo. Sem a razão social, o CNPJ sobe —
    repetir o mesmo número duas vezes só ocupa espaço."""
    return dado(rotulo, nome or cnpj, cnpj if nome else "")


def ficha_da_cotacao(c: dict, *, casco: bool = True) -> str:
    """Os dados que geraram esta cotação, com os rótulos do formulário.

    Pedido do Enzo em 19/08/2026. Resolve o caso de dois orçamentos parecidos
    na mesa: sem a ficha, conferir para qual CEP cada preço foi cotado exigia
    abrir o histórico e comparar de cabeça — e o preço certo no cliente
    errado é um prejuízo que ninguém percebe na hora.

    `casco=False` devolve só os campos, sem o cartão nem o título em volta: o
    painel do adm põe a ficha dentro do cartão dele, que já tem cabeçalho
    próprio, e dois títulos empilhados dizendo a mesma coisa é ruído."""
    unitario = peso_por_volume(c)
    detalhe_peso = (f"{c['quantidade']} × {kg(unitario)} kg cada"
                    if unitario is not None else "")

    campos = f"""
  <fieldset><legend>Rota</legend><div class="grid">
    {dado("CEP de origem", c["cep_origem"],
          lugar(c.get("cidade_origem"), c.get("uf_origem")))}
    {dado("CEP de destino", c["cep_destino"],
          lugar(c.get("cidade_destino"), c.get("uf_destino")))}
  </div></fieldset>

  <fieldset><legend>Documentos</legend><div class="grid">
    {parte("Remetente (quem envia)", c.get("nome_remetente"),
           c.get("cnpj_remetente"))}
    {parte("Destinatário (quem recebe)", c.get("nome_destinatario"),
           c.get("cnpj_destinatario"))}
    {dado("Tipo de frete", frete_por_extenso(c))}
    {parte("Quem paga o frete", c.get("nome_pagador"),
           c.get("cnpj_pagador"))}
  </div></fieldset>

  <fieldset><legend>Carga</legend><div class="grid">
    {dado("Quantidade de volumes", c["quantidade"])}
    {dado("Peso total", f"{kg(c['peso_kg'])} kg", detalhe_peso)}
    {dado("Comprimento", f"{c['comprimento_cm']} cm")}
    {dado("Largura", f"{c['largura_cm']} cm")}
    {dado("Altura", f"{c['altura_cm']} cm")}
    {dado("Valor da nota fiscal", moeda(c["valor_nf"]))}
    {dado("Material", c.get("material"))}
  </div></fieldset>"""

    if not casco:
        return f'<div class="ficha">{campos}</div>'

    return f"""<div class="cartao ficha">
  <h2 style="font-size:15px;margin:0 0 4px">Dados desta cotação</h2>
  <p class="sub">Foi com estes valores que os sites cotaram e que a mensagem
  do WhatsApp foi escrita. Cotada em {e(quando(c.get("criado_em")))}.</p>
{campos}
</div>"""
