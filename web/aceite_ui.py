"""A tela de aceitar a cotação, e o botão que leva até ela.

TELA, e não popup. O site inteiro é HTML montado no servidor, sem framework
nenhum — um popup seria o primeiro pedaço de JavaScript de verdade do projeto,
e para ganhar o quê: a mesma pergunta, num retângulo menor. Uma página cabe no
celular, é testável pelos testes que já existem e ainda tem espaço para
mostrar o que está sendo aceito, que é a parte que importa.

Aceitar é o primeiro gesto deste sistema que combina algo com o mundo de fora
em nome da Ventura. O WhatsApp aqui do lado só ABRE a conversa e deixa a
pessoa apertar enviar; daqui sai caminhão na porta do cliente. Por isso a tela
mostra preço, prazo e validade ao lado do formulário: quem confirma precisa
ver o que está confirmando, sem voltar uma página para conferir.
"""

from __future__ import annotations

from datetime import date, timedelta
from html import escape as e

from carriers.generoso.mapping import (HORARIOS_ALMOCO, HORARIOS_COLETA,
                                       LIMITE_OBSERVACAO)
from core.aceite import rotulo_validade, vencida

# Só a Generoso, por enquanto. A tabela `aceite` e a rota já nascem genéricas
# (levam o slug), mas não vou inventar a abstração de transportadora com uma
# implementação só — quando a segunda chegar, o encaixe está pronto.
COM_ACEITE = ("generoso",)

# O padrão do campo de data. Dois dias à frente, empurrado para segunda se
# cair no fim de semana: o calendário da Generoso bloqueia hoje e fim de
# semana, e um default inválido faria a tela abrir já com erro na cara.
DIAS_A_FRENTE = 2

HORA_PADRAO = "18:00"
ALMOCO_PADRAO = ("12:00", "13:00")


def primeiro_dia_util(hoje: date | None = None) -> date:
    """A data que o campo já vem preenchido. Nunca hoje, nunca fim de semana."""
    d = (hoje or date.today()) + timedelta(days=DIAS_A_FRENTE)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _opcoes(valores, escolhido: str) -> str:
    return "".join(
        f'<option value="{e(v)}"{" selected" if v == escolhido else ""}>'
        f'{e(v)}</option>' for v in valores)


def celula_de_aceite(slug: str, valor, validade, aceite: dict | None,
                     cotacao_id: int) -> str:
    """O conteúdo da coluna "Validade" na tabela de resultados.

    Validade e ação moram na MESMA célula de propósito. Separadas, o vendedor
    lê "vence hoje" num canto da linha e aperta um botão no outro sem ligar
    uma coisa à outra — e o que decide se vale a pena aceitar é exatamente
    essa ligação.
    """
    texto = rotulo_validade(validade)
    expirou = vencida(validade)
    selo = (f'<span class="{"validade-vencida" if expirou else "validade-ok"}">'
            f'{e(texto)}</span>' if texto else "")

    if aceite:
        # Já pedida. O botão SOME — e não fica desabilitado: botão apagado
        # ainda parece que um dia funciona, e convida ao clique.
        estados = {
            "agendando": ('<span class="aceite-indo">'
                          '<span class="girando"></span>agendando…</span>'),
            "agendado": '<span class="aceite-feito">✓ coleta agendada</span>',
        }
        padrao = (f'<a class="aceite-refazer" '
                  f'href="/aceitar/{cotacao_id}/{e(slug)}">falhou — tentar de '
                  f'novo</a>')
        return selo + estados.get(aceite["status"], padrao)

    if slug not in COM_ACEITE or valor is None or expirou:
        # Sem preço não há o que aceitar; vencida, o que havia já passou. Em
        # nenhum dos dois casos existe botão — só o selo, que explica.
        return selo

    return (selo + f'<a class="aceite-botao" '
                   f'href="/aceitar/{cotacao_id}/{e(slug)}">Aceitar</a>')


def tela_aceite(c: dict, r: dict, nome_transportadora: str, *,
                erros: list[str] | None = None,
                enviado: dict | None = None) -> str:
    """O formulário de agendamento, com o que está sendo aceito ao lado.

    `enviado` traz de volta o que a pessoa preencheu quando a validação
    recusou: perder o formulário inteiro por causa de um sábado é o jeito mais
    rápido de fazer alguém desistir e ligar para a transportadora."""
    enviado = enviado or {}
    cid = c["id"]
    slug = r["transportadora"]

    data = enviado.get("data_coleta") or primeiro_dia_util().isoformat()
    hora = enviado.get("hora_limite") or HORA_PADRAO
    almoco = bool(enviado.get("almoco_inicio"))
    a_ini = enviado.get("almoco_inicio") or ALMOCO_PADRAO[0]
    a_fim = enviado.get("almoco_fim") or ALMOCO_PADRAO[1]
    obs = enviado.get("observacao") or ""

    avisos = "".join(f'<div class="alerta">{e(x)}</div>'
                     for x in (erros or []))

    prazo = f'{e(str(r["prazo"]))} dias' if r["prazo"] else "—"
    validade = rotulo_validade(r["validade"]) or "não informada"
    preco = str(r["valor"]).replace(".", ",")
    amanha = (date.today() + timedelta(days=1)).isoformat()

    return f"""
{avisos}
<h1>Aceitar a cotação da {e(nome_transportadora)}</h1>
<p class="sub">Cotação #{cid} · {e(c['cidade_origem'])}/{e(c['uf_origem'])} →
{e(c['cidade_destino'])}/{e(c['uf_destino'])}</p>

<div class="cartao resumo-aceite">
  <div><span class="rot">Frete</span><b>R$ {e(preco)}</b></div>
  <div><span class="rot">Prazo</span><b>{prazo}</b></div>
  <div><span class="rot">Validade</span><b>{e(validade)}</b></div>
  <div><span class="rot">Cotação nº</span><b>{e(r['protocolo'] or '—')}</b></div>
</div>

<form method="post" action="/aceitar/{cid}/{e(slug)}" class="cartao">
  <h2 style="font-size:15px;margin:0 0 4px">Quando podemos coletar?</h2>
  <p class="sub">A {e(nome_transportadora)} pode ajustar conforme a
  disponibilidade dela — o que você escolhe aqui é o limite.</p>

  <label class="campo">
    <span>Data da coleta</span>
    <input type="date" name="data_coleta" value="{e(data)}" required
           min="{e(amanha)}">
    <small>Dia útil, a partir de amanhã. A Generoso não coleta no mesmo dia
    nem em fim de semana.</small>
  </label>

  <label class="campo">
    <span>Coletar até às</span>
    <select name="hora_limite">{_opcoes(HORARIOS_COLETA, hora)}</select>
  </label>

  <label class="campo linha">
    <input type="checkbox" name="fecha_almoco" id="fecha_almoco"
           {"checked" if almoco else ""}>
    <span>O local fecha para almoço</span>
  </label>

  <div class="campo duplo" id="horas-almoco">
    <label><span>Começa às</span>
      <select name="almoco_inicio">{_opcoes(HORARIOS_ALMOCO, a_ini)}</select>
    </label>
    <label><span>Termina às</span>
      <select name="almoco_fim">{_opcoes(HORARIOS_ALMOCO, a_fim)}</select>
    </label>
  </div>

  <label class="campo">
    <span>Observação para o coletador <i>(opcional)</i></span>
    <textarea name="observacao" rows="3" maxlength="{LIMITE_OBSERVACAO}"
      placeholder="Ex.: procurar o Marcos na portaria">{e(obs)}</textarea>
  </label>

  <div class="alerta email" style="margin:14px 0">
    <b>Isto pede a coleta de verdade.</b> Ao confirmar, a
    {e(nome_transportadora)} recebe o pedido em nome da Ventura e manda o
    caminhão. Confira a data antes.
  </div>

  <button class="botao" type="submit">Confirmar e pedir a coleta</button>
  <a class="botao2" href="/cotacao/{cid}">Cancelar</a>
</form>

<script>
// Esconde os horarios quando o local nao fecha para almoco. So isso -- o
// servidor ignora os dois campos quando a caixa vem desmarcada, entao a tela
// continua correta com o JavaScript desligado.
(function () {{
  const caixa = document.getElementById("fecha_almoco");
  const horas = document.getElementById("horas-almoco");
  const mostrar = () => {{ horas.style.display = caixa.checked ? "" : "none"; }};
  caixa.addEventListener("change", mostrar);
  mostrar();
}})();
</script>
"""
