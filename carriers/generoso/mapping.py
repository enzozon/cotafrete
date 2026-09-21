"""As empresas do grupo no portal da Generoso, e a regra do CIF/FOB.

Camada PURA: nada aqui abre navegador. Serve a dois propósitos que nasceram
juntos —

1. Escolher a empresa certa no "Alterar empresa" do site. Até 25/08/2026 toda
   cotação saía com o CNPJ da conta, qualquer que fosse o que o vendedor
   digitou no formulário.

2. Barrar, antes de gastar 40 segundos de navegador, a cotação em que o
   CIF/FOB está trocado.

Sobre (2): a Generoso PRENDE uma das pontas no CNPJ cadastrado — no CIF a
origem, no FOB o destino — e não deixa mexer no CEP dela. Marcar CIF com uma
empresa do grupo no DESTINO faz as duas pontas virarem a mesma casa. O site
recusa com "CEP de coleta não pode ser o mesmo de destino", mas essa frase
mora só no `aria-invalid` do campo: quem lê a tela não acha nada, e o
vendedor recebia "a etapa do destino não avançou. O site diz: (nenhuma
mensagem visível)".

Levantado no histórico inteiro em 25/08/2026: as três ocorrências dessa falha
(#5 e #20 de produção, #53 de desenvolvimento) têm a MESMA forma — CIF com
empresa do grupo no destino. Nenhuma outra falha da Generoso tem.
"""

from __future__ import annotations

import re
from datetime import date
from typing import NamedTuple

from core.models import CotacaoRequest, TipoFrete, limpa_doc

# A Generoso dizendo que não tem o CNPJ cadastrado.
#
# Ela diz isso na RESPOSTA, nunca na tela — por isso a cotação #56 registrou
# "O site diz: (nenhuma mensagem visível)" e foi repetida três vezes. Medido
# em 28/08/2026 por recon/recon_generoso_cnpj.py:
#
#   conhecido    {"erro":false,"mensagem":"OK","nome":"UNIAO INFO LTDA - ME",…}
#   desconhecido {"status":400,"message":"Cliente 41747639000112 nao
#                 cadastrado","error":true}
#
# Casa com acento e sem, porque a frase vem do backend deles e não há por que
# apostar em como vão escrevê-la amanhã.
RE_CLIENTE_NAO_CADASTRADO = re.compile(
    r'"message"\s*:\s*"Cliente\s+(\d+)\s+n[ãa]o\s+cadastrad', re.IGNORECASE)


def cliente_nao_cadastrado(corpo: str) -> str | None:
    """O CNPJ que a Generoso disse não conhecer, ou None.

    FUNÇÃO PURA. `corpo` é o texto das respostas do portal durante o
    preenchimento da ponta.

    None quer dizer "ela não disse isso" — o que inclui não ter respondido
    nada. Essa distinção é o motivo de o recon existir: sem ela, campo de
    endereço vazio viraria recusa, e uma falha de rede de verdade deixaria de
    ser repetida."""
    achado = RE_CLIENTE_NAO_CADASTRADO.search(corpo or "")
    return achado.group(1) if achado else None


def recusa_cliente_nao_cadastrado(cnpj: str, lado: str) -> str:
    """Mensagem para o vendedor. `lado` é "origem" ou "destino".

    Escrita para ele RESOLVER sozinho, como recusa_cep_nao_atendido: numa
    cotação existem dois CNPJs, e não dizer qual deixa quem lê procurando no
    escuro. Não é defeito do robô nem carga inválida — é a regra comercial da
    Generoso, que só cota para quem tem cadastro."""
    return (
        f"A Generoso não tem o CNPJ de {lado} {cnpj} cadastrado como cliente, "
        f"e só cota para CNPJ cadastrado. Peça o cadastro a ela, use outro "
        f"CNPJ nessa ponta, ou fale com a Generoso pelo WhatsApp, no botão "
        f"aqui embaixo.")


# Aviso vermelho embaixo do campo de CEP quando a praça está fora da malha.
# NÃO aparece em _erros_da_tela (o filtro lá só pega "obrigat/inválid/erro")
# — por isso 4 das 6 cotações reais que caíram no genérico "a etapa do
# destino não avançou. O site diz: (nenhuma mensagem visível)" entre 24/08 e
# 31/08/2026 (#40, #43, #78, #79) eram na verdade isto. O CEP É resolvido
# (cidade e rua vêm preenchidas) — só o "Próximo" trava, sem dizer por quê
# na tela. As outras duas (#5, #20) são AVISO_MESMO_CEP, logo abaixo — mesmo
# sintoma na tela, causa diferente.
AVISO_CEP_NAO_ATENDIDO = "não atendemos essa"


def recusa_cep_nao_atendido(cep: str, lado: str) -> str:
    """Mensagem para o vendedor. `lado` é "origem" ou "destino".

    Numa cotação existem dois CEPs, e não dizer qual deixa quem lê
    procurando no escuro — mesmo raciocínio de recusa_cliente_nao_cadastrado."""
    return (
        f"A Generoso não atende o CEP de {lado} {cep} — praça fora da malha "
        f"dela. Cote com outra transportadora, ou fale com a Generoso pelo "
        f"WhatsApp, no botão aqui embaixo.")


# O outro aviso vermelho que pode aparecer no mesmo lugar: "CEP de destino
# não pode ser o mesmo de coleta" (ou a ordem invertida, "CEP de coleta não
# pode ser o mesmo de destino" — o site usa as duas conforme qual lado está
# validando). "não pode ser o mesmo de" casa as duas por igual.
#
# Medido em 2 cotações reais (#5 e #20, 24-25/08/2026): as duas tinham o
# CNPJ do lado livre batendo com uma empresa do grupo Ventura já cadastrada
# no MESMO endereço da ponta travada — Ventura, Aliança e União Info
# compartilham a mesma sede em Vila Velha no cadastro da Generoso. A conta
# resolve os dois lados para o mesmo CEP, e o site recusa.
AVISO_MESMO_CEP = "não pode ser o mesmo de"


def recusa_mesmo_cep() -> str:
    """Origem e destino colidiram no mesmo CEP dentro do cadastro da
    Generoso — normalmente porque o CNPJ do lado livre é (ou coincide com)
    uma empresa do grupo Ventura cadastrada no mesmo endereço da ponta
    travada. Sem `lado`, ao contrário de recusa_cep_nao_atendido: o site usa
    as duas ordens ("destino... coleta" e "coleta... destino") e não dá pra
    saber de qual lado ele está reclamando desta vez."""
    return (
        "A Generoso recusou: origem e destino caíram no mesmo CEP dentro do "
        "cadastro dela — normalmente porque o CNPJ do lado livre é uma "
        "empresa do grupo Ventura com o mesmo endereço da ponta travada. "
        "Confira os CNPJs de remetente e destinatário, ou fale com a "
        "Generoso pelo WhatsApp, no botão aqui embaixo.")


class Empresa(NamedTuple):
    cnpj: str
    nome: str          # como o SITE escreve, para casar no menu


# As três do "Alterar empresa". O nome é o rótulo do menu; o CNPJ é o que
# manda. Casar por CNPJ e não por nome é de propósito: nome o site pode
# abreviar ("Alianca Comercio de Produto...") e um dia mudar.
EMPRESAS = (
    Empresa("08.310.365/0001-24", "Ventura Inf Ltda me"),
    Empresa("05.954.058/0001-98", "Alianca Comercio de Produtos"),
    Empresa("20.837.281/0001-49", "Uniao Info Ltda - me"),
)


def empresa_de(cnpj: str | None) -> Empresa | None:
    """A empresa do grupo com este CNPJ, ou None. Ignora máscara e espaço."""
    digitos = limpa_doc(cnpj or "")
    if not digitos:
        return None
    return next((e for e in EMPRESAS if limpa_doc(e.cnpj) == digitos), None)


def lado_do_grupo(req: CotacaoRequest) -> str | None:
    """Em que ponta da carga está o grupo: "origem", "destino", "ambos"
    ou None.

    É o fato físico, lido dos CNPJs — independe do que o vendedor marcou.
    O CIF/FOB é a opinião dele sobre esse fato, e é a comparação entre os
    dois que revela o engano."""
    na_origem = empresa_de(req.remetente.cnpj) is not None
    no_destino = empresa_de(req.destinatario.cnpj) is not None
    if na_origem and no_destino:
        return "ambos"
    if na_origem:
        return "origem"
    if no_destino:
        return "destino"
    return None


# O que cada modo AFIRMA sobre onde o grupo está.
#   CIF  o grupo despacha  -> grupo na origem
#   FOB  o grupo recebe    -> grupo no destino
_LADO_ESPERADO = {TipoFrete.CIF: "origem", TipoFrete.FOB: "destino"}


def conflito_cif_fob(req: CotacaoRequest) -> str | None:
    """A frase para o vendedor quando o CIF/FOB contradiz os CNPJs, ou None.

    Só acusa o caso comprovado — grupo numa ponta e o modo apontando para a
    outra. Cotação sem o grupo em ponta nenhuma, ou com ele nas duas, passa:
    barrar cotação boa é pior que o bug, porque tira o preço do vendedor e
    ainda não diz o que fazer."""
    lado = lado_do_grupo(req)
    esperado = _LADO_ESPERADO.get(req.tipo_frete)
    if lado is None or lado == "ambos" or lado == esperado:
        return None

    marcado, correto = ("CIF", "FOB") if lado == "destino" else ("FOB", "CIF")
    empresa = empresa_de(req.destinatario.cnpj if lado == "destino"
                         else req.remetente.cnpj)
    quem = "recebe" if lado == "destino" else "despacha"
    return (
        f"Esta cotação está marcada como {marcado}, mas quem {quem} é a "
        f"{empresa.nome} — uma empresa do grupo. Carga que "
        f"{'chega para' if lado == 'destino' else 'sai do'} o grupo é "
        f"{correto}. A Generoso prende o endereço da empresa do grupo no "
        f"CNPJ cadastrado e não deixa trocar o CEP, então do jeito que está "
        f"a cotação sairia e chegaria no mesmo lugar — e o site trava sem "
        f"dizer por quê. Marque {correto} e cote de novo."
    )


def empresa_alvo(req: CotacaoRequest) -> Empresa | None:
    """A empresa que precisa estar selecionada no site, ou None.

    É a ponta que a Generoso TRAVA: no CIF a origem, no FOB o destino. Até
    25/08/2026 o robô nunca trocava, e toda cotação saía com o CNPJ da conta
    — mesmo quando o vendedor digitava outra das três empresas do grupo. A
    tela final avisava disso; agora não precisa mais avisar, porque o robô
    troca.

    None quando a ponta travada não é do grupo. Aí não há o que escolher: o
    site fica com o que já estava, que é o comportamento de sempre."""
    ponta = (req.remetente if req.tipo_frete is TipoFrete.CIF
             else req.destinatario)
    return empresa_de(ponta.cnpj)


def ponta_travada_sem_o_grupo(req: CotacaoRequest) -> str | None:
    """A frase para quando a Ventura não está na ponta que a Generoso TRAVA.

    O portal cota LOGADO e preenche cada ponta pelo CNPJ, nunca pelo CEP (ver
    o cabeçalho do adapter). A ponta travada é sempre a da conta: no CIF a
    origem, no FOB o destino. Sem a Ventura ali, o site escreve o endereço
    DELA naquela ponta — e a cotação sai por outra rota, sem nada na tela
    dizendo isso.

    Medido na cotação #154 (10/09/2026), FOB, ADECIL COMERCIAL -> INSTITUTO
    AMBIENTAL, com a Ventura em ponta nenhuma. A tela de conferência da
    Generoso, no dry-run, mostrava:

        origem   ADECIL,  CEP 13.211-377, Jundiaí/SP
                 (a ficha diz São Paulo/SP, 05117-002)
        destino  VENTURA, CEP 29.105-770, Vila Velha/ES
                 (a ficha diz Linhares/ES, 29911-080)

    Ou seja: o preço que voltaria dali é de Jundiaí -> Vila Velha, e o
    vendedor mostraria ao cliente como se fosse São Paulo -> Linhares.

    Quando a busca da ponta travada nem responde, o MESMO caso vira o
    RuntimeError "a conta da Generoso nao trouxe o endereco de destino" —
    classificado como ERRO, que a retentativa repete três vezes.

    Barrar aqui não tira preço de ninguém, e isso foi conferido ANTES de
    escrever a regra: nos 143 resultados da Generoso em produção (19/08 a
    09/09/2026), as 83 que voltaram COM preço tinham todas o grupo na ponta
    travada. Com o grupo fora dela nunca saiu preço — só 2 erros e 7
    recusas.

    Dispara SÓ com o grupo em ponta nenhuma. Grupo na ponta errada já tem
    dono — `conflito_cif_fob`, que ainda diz qual marcar ("Marque FOB e cote
    de novo"); duas regras acusando o mesmo engano dariam ao vendedor dois
    parágrafos concorrentes para ler."""
    if lado_do_grupo(req) is not None:
        return None

    lado, quem = (("origem", "remetente") if req.tipo_frete is TipoFrete.CIF
                  else ("destino", "destinatário"))
    return (
        f"A Generoso cota logada na conta da Ventura, e o portal dela trava "
        f"uma das pontas no CNPJ da conta: no CIF a origem, no FOB o destino. "
        f"Nesta cotação o {quem} não é a Ventura, então o {lado} sairia com o "
        f"endereço da Ventura no lugar do endereço real — o preço seria de "
        f"outra rota. Cote esta carga com outra transportadora, ou corrija o "
        f"CIF/FOB se a Ventura for mesmo uma das pontas.")


# ===================================================================
# AGENDAMENTO DE COLETA — aceitar a cotação pelo site
# ===================================================================
#
# Tudo abaixo saiu de `recon/recon_generoso_agendar.py`, rodado na conta real
# em 21/09/2026. Nada foi deduzido dos prints: eles mostram O QUE a tela tem,
# e é o DOM que diz o que ela ACEITA.
#
# A validação mora aqui, longe do navegador, porque a célula bloqueada do
# calendário não recusa o clique com mensagem nenhuma — ela simplesmente não
# faz nada. O painel fica parado, com cara de travado, e o vendedor recebe um
# timeout de 45 segundos em vez de "sábado não tem coleta".

# Hora limite da coleta: 08:00 às 18:00, de 30 em 30 minutos (21 opções).
# ESCRITAS, e não geradas por range: se a Generoso mexer na grade, um teste
# falha e alguém vai olhar. Uma lista gerada continuaria "certa" em silêncio
# enquanto o site recusava.
HORARIOS_COLETA = (
    "08:00", "08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30",
    "16:00", "16:30", "17:00", "17:30", "18:00",
)

# O almoço tem grade PRÓPRIA e menor: 10:00 às 14:30. Reaproveitar a de cima
# ofereceria 08:00 para o começo do almoço, e esse item não existe no select.
HORARIOS_ALMOCO = (
    "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
    "14:00", "14:30",
)

# O coletador lê isto num aplicativo de celular. Campo de texto sem limite
# visível no site é convite para colar um e-mail inteiro.
LIMITE_OBSERVACAO = 500


class Agendamento(NamedTuple):
    """O que o vendedor escolhe para a coleta.

    `almoco_inicio`/`almoco_fim` são None quando o local NÃO fecha para
    almoço — ausência, não "das 00:00 às 00:00". Com o checkbox desmarcado
    os dois selects nem existem no DOM."""

    data: date
    hora_limite: str
    almoco_inicio: str | None = None
    almoco_fim: str | None = None
    observacao: str = ""

    @property
    def fecha_para_almoco(self) -> bool:
        return bool(self.almoco_inicio and self.almoco_fim)


def validar_agendamento(ag: Agendamento,
                        hoje: date | None = None) -> list[str]:
    """Devolve TODAS as frases de erro, não só a primeira.

    Quem preencheu errado merece ver tudo de uma vez, e não descobrir um
    problema por vez a cada ida ao portal — cada tentativa custa um login e
    meio minuto de navegador.

    As frases são escritas para o vendedor ler na tela, não para o log."""
    hoje = hoje or date.today()
    erros: list[str] = []

    # ------------------------------------------------------------- a data
    # O site bloqueia o PRÓPRIO dia: medido em 21/09, o dia 21/09 veio
    # `data-disabled`. Não existe coleta no mesmo dia.
    if ag.data <= hoje:
        erros.append(
            "A coleta não pode ser hoje nem em data passada: a Generoso só "
            "abre o calendário a partir de amanhã.")
    # segunda=0 ... sábado=5, domingo=6
    elif ag.data.weekday() >= 5:
        erros.append(
            f"{ag.data:%d/%m} cai em fim de semana, e a Generoso só coleta em "
            f"dia útil. Escolha outro dia.")

    # ------------------------------------------------------------- a hora
    if ag.hora_limite not in HORARIOS_COLETA:
        erros.append(
            f"A Generoso não tem o horário {ag.hora_limite}. Ela coleta das "
            f"{HORARIOS_COLETA[0]} às {HORARIOS_COLETA[-1]}, de meia em meia "
            f"hora.")

    # ----------------------------------------------------------- o almoço
    # Os dois selects andam juntos no site. Meia informação aqui viraria um
    # horário que ninguém escolheu.
    if bool(ag.almoco_inicio) != bool(ag.almoco_fim):
        erros.append(
            "Para avisar o almoço, preencha a hora de começar E a de "
            "terminar.")
    elif ag.fecha_para_almoco:
        for rotulo, valor in (("começa", ag.almoco_inicio),
                              ("termina", ag.almoco_fim)):
            if valor not in HORARIOS_ALMOCO:
                erros.append(
                    f"O almoço {rotulo} num horário que a Generoso não "
                    f"oferece ({valor}). São de {HORARIOS_ALMOCO[0]} a "
                    f"{HORARIOS_ALMOCO[-1]}.")
        # O site deixa escolher os dois livremente — nada impede 13:00 às
        # 12:00 lá. Aqui impede: é um almoço que não existe, e o coletador
        # leria uma janela invertida.
        if ag.almoco_inicio >= ag.almoco_fim:
            erros.append(
                f"O almoço termina antes de começar ({ag.almoco_inicio} às "
                f"{ag.almoco_fim}).")

    # ------------------------------------------------------- a observação
    if len(ag.observacao or "") > LIMITE_OBSERVACAO:
        erros.append(
            f"A observação para o coletador passou de {LIMITE_OBSERVACAO} "
            f"letras. Ele lê isso no celular — escreva o essencial.")

    return erros
