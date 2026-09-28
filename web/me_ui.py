"""A tela do Mercado Eletrônico: /me (lista) e /me/{id} (responder).

Fica fora de web/app.py pelo mesmo motivo do /adm: aquele arquivo passou de
2000 linhas, e esta é outra tela, com outro assunto.

O que a tela faz (docs/MERCADO_ELETRONICO.md tem o porquê de cada coisa):

- Lista as cotações pendentes dos logins de `mercado_eletronico.logins`, com o prazo contando e o
  status do NOSSO lado (Pendente → Salva no ME → Enviada, ou Erro/Vencida).
  A lista vem do ME a cada `INTERVALO` e no botão "Atualizar agora".
- Numa cotação: lê os itens do ME, o usuário preenche só o que muda (preço,
  NCM, prazo, marca, obs, origem), a tela mostra o que o robô VAI digitar
  (impostos e data calculados por `regras`) com os erros e avisos na linha, e
  um botão manda o robô SALVAR no ME.
- O envio é sempre humano. Esta tela não tem, e não deve ganhar, um botão de
  enviar. O "Marcar como enviada" só grava no nosso banco que alguém enviou
  pelo site do ME.

Quem fala com o ME: `mercado_eletronico.ponte.pendencias(conta)` e
`ponte.ler_paginas(conta, numero)` (leitura, pelas travas do robô) e
`mercado_eletronico.robo.salvar_cotacao(...)`. Entram por `FONTE`, `LEITOR` e
`ROBO`, trocáveis — o teste troca por falsos e nunca abre navegador.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core import ia
from core.banco import Banco
from core.retentativa import VAGA_NAVEGADOR
from mercado_eletronico import logins as L
from mercado_eletronico import ncm as sugestor_ncm
from mercado_eletronico import pagina as pg
from mercado_eletronico import painel as pn
from mercado_eletronico import regras as rg
from mercado_eletronico import revisao as rv
from mercado_eletronico.painel import Status
from web.layout import cabecalho, e, pagina

# Injetados por web/app.py (mesmo esquema do /adm: importar web.app daqui
# seria circular).
banco: Banco | None = None
vendedor: Callable[[str | None], str | None] | None = None
COOKIE = "cotafrete_usuario"

CONTAS = L.ROTULOS
INTERVALO_S = 60       # o vigia acorda a cada minuto e lê só os logins vencidos
# Três falhas seguidas no mesmo login e ele passa a ser tentado de meia em meia
# hora: um login quebrado não atrasa os outros, nem enche o resumo de erros
# (28/09/2026: 91 falhas seguidas por conta numa madrugada).
FALHAS_ATE_ESPERAR = 3
ESPERA_APOS_FALHAS_S = 30 * 60
# Quando chega cotação nova e em qual login. Para descobrir de quanto em quanto
# tempo cada login recebe e afinar o intervalo (pedido do Enzo, 28/09/2026).
# None = não grava: só o servidor de verdade liga (web/app.py, no lifespan),
# para os testes não escreverem no log real.
LOG_CHEGADAS: "Path | None" = None
MAX_OBS = 100          # maxlength do Observacao{N} no ME (recon 23/09/2026)
agora: Callable[[], datetime] = datetime.now

router = APIRouter(prefix="/me", include_in_schema=False)


# ------------------------------------------------------ quem fala com o ME
# Import tardio: o Playwright só carrega quando alguém fala com o ME.
def _fonte_padrao(conta: str) -> list:
    from mercado_eletronico import ponte
    return ponte.pendencias(conta)


def _leitor_padrao(conta: str, numero: int) -> list[str]:
    from mercado_eletronico import ponte
    return ponte.ler_paginas(conta, numero)


def _robo_padrao(conta: str, numero: int, itens: list[rg.EntradaItem],
                 validade_dias: int, dry_run: bool, frete: str = "FOB"):
    from mercado_eletronico import robo
    return robo.salvar_cotacao(conta, numero, itens, validade_dias, dry_run=dry_run,
                               frete=frete)


def _limpador_padrao(conta: str, numero: int, dry_run: bool):
    from mercado_eletronico import robo
    return robo.limpar_cotacao(conta, numero, dry_run=dry_run)


def _em_thread(fn: Callable, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


# Como o trabalho demorado sai do pedido HTTP. O teste troca por chamada
# direta para conferir o resultado sem esperar thread.
DISPARAR: Callable[..., None] = _em_thread

FONTE: Callable[[str], list] = _fonte_padrao
REVISOR: Callable[..., rv.Revisao] = rv.revisar
REVISANDO: set[int] = set()   # cotações com a IA trabalhando agora
LEITOR: Callable[[str, int], list[str]] = _leitor_padrao
ROBO: Callable[..., Any] = _robo_padrao
LIMPADOR: Callable[..., Any] = _limpador_padrao


def contas_configuradas() -> list[str]:
    """Só as contas com login e senha no ambiente. Sem nenhuma, a tela diz
    isso em vez de tentar e falhar a cada volta."""
    return [l.chave for l in L.configurados()]


# ------------------------------------------------------------- varredura
@dataclass
class EstadoVarredura:
    rodando: bool = False
    ultima: datetime | None = None
    erros: dict[str, str] = field(default_factory=dict)
    trava: threading.Lock = field(default_factory=threading.Lock)
    falhas: dict[str, int] = field(default_factory=dict)       # seguidas, por login
    proxima: dict[str, float] = field(default_factory=dict)    # time.monotonic()


VARREDURA = EstadoVarredura()


def _campo(obj, nome: str, padrao=None):
    return obj.get(nome, padrao) if isinstance(obj, dict) else getattr(obj, nome, padrao)


def sincronizar(conta: str, pendentes: list, momento: datetime | None = None) -> None:
    """Aplica UMA leitura bem-sucedida da lista do ME ao banco.

    Só chamar com a lista que VEIO: se a leitura falhou, nada de sincronizar
    com lista vazia — isso daria todas as cotações como enviadas."""
    momento = momento or agora()
    carimbo = momento.isoformat(timespec="seconds")
    primeira = not banco.me_cotacoes(conta=conta)
    vistos = set()
    for p in pendentes:
        numero = int(_campo(p, "numero"))
        vistos.add(numero)
        limite = pn.hora_de_brasilia(_campo(p, "data_limite"))
        cid = banco.me_criar(conta, numero, visto_em=carimbo)
        antes = banco.me_cotacao(cid)
        novo = pn.status_apos_varredura(
            Status(antes["status"]), status_resposta=_campo(p, "status_resposta"),
            na_lista=True, data_limite=limite, agora=momento)
        banco.me_atualizar(
            cid, empresa=_campo(p, "empresa"), comprador=_campo(p, "comprador"),
            codigo=_campo(p, "codigo"),
            data_limite=limite.isoformat(timespec="minutes") if limite else None,
            status_resposta=_campo(p, "status_resposta"), na_lista=1,
            atualizado_em=carimbo, status=novo.value,
            **({"enviada_em": carimbo} if novo is Status.ENVIADA and antes["status"] != "enviada" else {}))
        if antes["visto_em"] == carimbo and antes["atualizado_em"] is None:
            banco.me_registrar(cid, "apareceu no ME", _campo(p, "status_resposta") or "")
            _anotar_chegada(momento, conta, numero, _campo(p, "empresa"), limite, primeira)
        if novo.value != antes["status"]:
            banco.me_registrar(cid, f"status: {pn.ROTULO[novo]}", "pela lista do ME")

    for c in banco.me_cotacoes(conta=conta):
        if c["numero"] in vistos or not c["na_lista"]:
            continue
        limite = pn.hora_de_brasilia(c["data_limite"])
        novo = pn.status_apos_varredura(
            Status(c["status"]), status_resposta=None, na_lista=False,
            data_limite=limite, agora=momento)
        extra = {"enviada_em": carimbo} if novo is Status.ENVIADA and c["status"] != "enviada" else {}
        banco.me_atualizar(c["id"], na_lista=0, atualizado_em=carimbo, status=novo.value, **extra)
        banco.me_registrar(c["id"], "saiu de Oportunidades a Responder",
                           f"status: {pn.ROTULO[novo]}")


def _anotar_chegada(momento: datetime, conta: str, numero: int, empresa, limite,
                    primeira: bool) -> None:
    if LOG_CHEGADAS is None:
        return
    linha = " | ".join((
        f"{momento:%Y-%m-%d %H:%M:%S}", f"{CONTAS.get(conta, conta)} ({conta})",
        f"cotação {numero}", str(empresa or "—"),
        f"limite {limite:%d/%m %H:%M}" if limite else "sem limite",
    )) + (" | já estava lá na 1ª leitura deste login" if primeira else "")
    try:
        LOG_CHEGADAS.parent.mkdir(parents=True, exist_ok=True)
        with LOG_CHEGADAS.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass  # anotar é estatística; nunca derruba a leitura


def devidas(relogio: Callable[[], float] = time.monotonic) -> list[str]:
    """Os logins configurados cuja vez de ler já chegou."""
    t = relogio()
    return [k for k in contas_configuradas() if VARREDURA.proxima.get(k, 0) <= t]


def _agendar(conta: str, ok: bool, relogio: Callable[[], float] = time.monotonic) -> None:
    falhas = 0 if ok else VARREDURA.falhas.get(conta, 0) + 1
    VARREDURA.falhas[conta] = falhas
    espera = (ESPERA_APOS_FALHAS_S if falhas >= FALHAS_ATE_ESPERAR
              else L.de(conta).intervalo_s)
    VARREDURA.proxima[conta] = relogio() + espera


def atualizar(contas: list[str] | None = None) -> None:
    """Lê a lista do ME de cada conta e sincroniza. Uma de cada vez, e cada
    uma pegando vaga de navegador como as transportadoras: com o frete usando
    as duas vagas, o ME espera — cotação de frete tem cliente esperando."""
    if not VARREDURA.trava.acquire(blocking=False):
        return  # já tem uma rodando
    VARREDURA.rodando = True
    try:
        for conta in contas if contas is not None else contas_configuradas():
            inicio = time.monotonic()
            try:
                with VAGA_NAVEGADOR:
                    pendentes = FONTE(conta)
                sincronizar(conta, pendentes)
                VARREDURA.erros.pop(conta, None)
                _agendar(conta, ok=True)
                banco.me_registrar_varredura(conta, ok=True, cotacoes=len(pendentes),
                                             duracao_s=round(time.monotonic() - inicio, 1))
            except Exception as exc:  # a outra conta ainda roda
                VARREDURA.erros[conta] = f"{type(exc).__name__}: {exc}"[:300]
                _agendar(conta, ok=False)
                banco.me_registrar_varredura(conta, ok=False, erro=VARREDURA.erros[conta],
                                             duracao_s=round(time.monotonic() - inicio, 1))
        VARREDURA.ultima = agora()
    finally:
        VARREDURA.rodando = False
        VARREDURA.trava.release()


def atualizar_em_segundo_plano() -> None:
    DISPARAR(atualizar)


def iniciar_vigia() -> threading.Event | None:
    """Varredura a cada INTERVALO_S. Chamado no LIFESPAN do app (mesmo motivo
    do ingestor da Della Volpe: pytest e scripts soltos não podem sair
    logando no ME). Sem conta configurada, não sobe."""
    if not contas_configuradas():
        return None
    parar = threading.Event()

    def laco():
        while not parar.is_set():
            # Cada volta numa thread NOVA: se uma leitura deixar o Playwright
            # meio aberto, a sujeira morre com ela e não derruba as próximas
            # (28/09/2026: uma volta envenenou a thread e 91 seguidas falharam
            # com "Sync API inside the asyncio loop"; ver robo.Sessao).
            volta = threading.Thread(target=atualizar, args=(devidas(),),
                                     name="me-vigia-volta", daemon=True)
            volta.start()
            volta.join()
            parar.wait(INTERVALO_S)

    threading.Thread(target=laco, name="me-vigia", daemon=True).start()
    return parar


# --------------------------------------------------------- itens e robô
def carregar_itens(cid: int) -> int:
    """Lê as páginas da cotação no ME e grava os itens. Devolve quantos."""
    c = banco.me_cotacao(cid)
    paginas = [pg.ler(h) for h in LEITOR(c["conta"], c["numero"])]
    if any(p.numero != c["numero"] for p in paginas):
        raise ValueError("O ME devolveu a página de outra cotação.")
    itens = [_item_para_banco(i, p.pagina) for p in paginas for i in p.itens]
    return _gravar_lidos(cid, c, pg.juntar(paginas), itens)


def _item_para_banco(item: pg.ItemDaPagina, pagina_n: int) -> dict:
    return {
        "numero": item.numero, "pagina": pagina_n, "indice": item.indice,
        "produto_id": item.produto_id, "descricao": item.descricao,
        "quantidade": item.quantidade, "unidade": item.unidade,
        "obs_comprador": item.obs_comprador,
        "campos_adicionais": item.campos_adicionais,
        "uf_destino": item.pedido.uf_destino,
        "origem_pedida": item.pedido.origem,
        "data_remessa": item.pedido.data_remessa.isoformat() if item.pedido.data_remessa else None,
        "ncm_pedido": rg.ncm_do_comprador(item.campos_adicionais),
        "local_entrega": item.local_entrega or None,
    }


def _gravar_lidos(cid: int, c: dict, lidas: pg.PaginaDaCotacao, itens: list[dict]) -> int:
    banco.me_gravar_itens_do_me(cid, itens)
    # Preenche só o que o usuário ainda não digitou. NCM: o que o COMPRADOR
    # escreveu vem antes da memória (é o que ele vai conferir); marca e
    # origem, da memória do material.
    for item in banco.me_cotacao(cid)["itens"]:
        campos = {}
        if not item["ncm"] and item["ncm_pedido"]:
            campos |= {"ncm": item["ncm_pedido"], "ncm_origem": "comprador", "ncm_nota": None}
        lembrado = banco.me_material(pn.chave_material(item["descricao"]))
        if lembrado:
            for k in ("ncm", "marca", "origem"):
                if item[k] in (None, "") and k not in campos and lembrado[k] not in (None, ""):
                    campos[k] = lembrado[k]
                    if k == "ncm":
                        campos["ncm_origem"] = "memoria"
        if campos:
            banco.me_gravar_entrada(cid, item["numero"], **campos)
    extra = {}
    if lidas.data_limite and not c["data_limite"]:
        extra["data_limite"] = lidas.data_limite.isoformat(timespec="minutes")
    if lidas.comprador and not c["comprador"]:
        extra["comprador"] = lidas.comprador
    if lidas.titulo and not c["codigo"]:
        extra["codigo"] = lidas.titulo
    if lidas.obs_comprador:
        extra["obs_comprador"] = lidas.obs_comprador
    extra["avisos_comprador"] = json.dumps(
        {"avisos": lidas.avisos, "frete_formulario": lidas.frete_formulario}, ensure_ascii=False)
    banco.me_atualizar(cid, itens_lidos_em=agora().isoformat(timespec="seconds"), **extra)
    return len(itens)


def _int(texto) -> int | None:
    try:
        return int(str(texto).strip())
    except (TypeError, ValueError):
        return None


def gravar_formulario(cid: int, form: dict) -> None:
    """Grava no banco o que veio da tela. Não valida: guardar o rascunho
    pela metade é justamente o que deixa a pessoa voltar depois."""
    c = banco.me_cotacao(cid)
    if "validade_dias" in form:
        banco.me_atualizar(cid, validade_dias=_int(form["validade_dias"]))
    for item in c["itens"]:
        n = item["numero"]
        if f"preco_{n}" not in form:
            continue
        origem = _int(form.get(f"origem_{n}"))
        campos = {
            "preco": (form.get(f"preco_{n}") or "").strip(),
            "ncm": (form.get(f"ncm_{n}") or "").strip(),
            "prazo_dias": _int(form.get(f"prazo_{n}")),
            "marca": (form.get(f"marca_{n}") or "").strip()[:rg.MAX_MARCA],
            "obs": (form.get(f"obs_{n}") or "").strip()[:MAX_OBS],
            "origem": origem,
        }
        if campos["ncm"] != (item["ncm"] or ""):
            # Mexeu no NCM: agora é dele — sai a etiqueta "sugerido pela IA".
            campos |= {"ncm_origem": None, "ncm_nota": None}
        banco.me_gravar_entrada(cid, n, **campos)
        # NCM sugerido pela IA e ainda não conferido não vira memória do
        # material: um palpite errado voltaria sozinho em toda cotação.
        palpite = campos["ncm"] == (item["ncm"] or "") and item.get("ncm_origem") == "ia"
        ncm_lembrar = None if palpite else campos["ncm"] or None
        if ncm_lembrar or campos["marca"] or origem is not None:
            banco.me_lembrar_material(pn.chave_material(item["descricao"]),
                                      ncm=ncm_lembrar,
                                      marca=campos["marca"] or None, origem=origem)


def _lido_da_pagina(c: dict) -> dict:
    """`avisos_comprador`: {"avisos": [...], "frete_formulario": "CIF" | ""}."""
    try:
        dados = json.loads(c.get("avisos_comprador") or "{}")
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def avisos_de(c: dict) -> list[str]:
    return [str(a) for a in _lido_da_pagina(c).get("avisos") or []]


def frete_de(c: dict) -> tuple[str, str]:
    """CIF/FOB desta cotação e o porquê (regras.tipo_frete)."""
    return rg.tipo_frete(avisos_de(c), c.get("empresa"),
                         _lido_da_pagina(c).get("frete_formulario") or "")


def _entrada(i: dict) -> rg.EntradaItem:
    return rg.EntradaItem(
        numero=i["numero"], preco=i["preco"] or "", ncm=i["ncm"] or "",
        prazo_dias=i["prazo_dias"], marca=i["marca"] or "", obs=i["obs"] or "",
        origem=i["origem"],
        pedido=rg.PedidoDoComprador(
            i["uf_destino"], i["origem_pedida"],
            date.fromisoformat(i["data_remessa"]) if i["data_remessa"] else None),
    )


def entradas(c: dict) -> list[rg.EntradaItem]:
    return [_entrada(i) for i in c["itens"]]


_ORIGENS = {0: "0 - Nacional", 2: "2 - Estrangeira (merc. interno)"}


def linha_previa(c: dict, i: dict, hoje: date) -> str:
    """O item como o robô vai digitar, montado conforme o usuário preenche.

    Com a origem escolhida já saem os impostos (só dependem dela, da empresa
    e da UF de entrega); prazo, preço e NCM completam o resto. Mesmo cálculo
    do robô (`regras`), para a tela nunca mostrar um número e o robô digitar
    outro. `data-pronta="1"` quando o item passa na validação."""
    item = _entrada(i)
    val = rg.validar_item(item, hoje)
    pronta = ' data-pronta="1"' if not val.erros else ' data-pronta="0"'
    if item.sem_cotacao and not item.obs.strip():
        # Sem preço a validação só reclama do preço; na tela vale mostrar
        # tudo o que ainda falta de uma vez.
        resto = rg.validar_item(replace(item, preco="1"), hoje)
        val = rg.Resultado(val.erros + resto.erros, resto.avisos)
    if item.sem_cotacao and item.obs.strip():
        return (f'<div class="me-linha"{pronta}>Sem preço: será <b>recusado no ME</b> ("Recusar '
                f'item"), com a justificativa "{e(" ".join(item.obs.split()))}".</div>')
    if item.origem is None:
        return (f'<div class="me-linha"{pronta}><span class="me-falta">Escolha a origem '
                f'(0 ou 2) e este item se completa aqui.</span></div>')
    partes: list[tuple[str, str]] = [("origem", _ORIGENS.get(item.origem, str(item.origem)))]
    try:
        imp = rg.impostos(L.de(c["conta"]).empresa, item.origem,
                          item.pedido.uf_destino).como_campos()
        partes += [("ICMS", f"{imp['icms']}% ({imp['icms_incluso']})"),
                   ("PIS", f"{imp['pis']}% ({imp['pis_incluso']})"),
                   ("COFINS", f"{imp['cofins']}% ({imp['cofins_incluso']})")]
    except rg.RegraDesconhecida:
        pass  # o motivo vem nos erros da validação, logo abaixo
    fixo = rg.CAMPOS_FIXOS_ITEM
    partes += [("IPI", f"{fixo['ipi']} ({fixo['ipi_incluso']})"),
               ("ST", fixo["substituicao_tributaria"]),
               ("base ICMS", f"{fixo['base_calculo_icms']}%"), ("unidade", fixo["unidade"])]
    if item.prazo_dias and item.prazo_dias >= 1:
        partes.append(("entrega", f"{rg.data_entrega(item.prazo_dias, hoje):%d/%m/%Y} "
                                  f"({item.prazo_dias} dias corridos)"))
    if len(rg.normalizar_ncm(item.ncm)) == 8:
        partes.append(("NCM", rg.formatar_ncm(item.ncm)))
    if item.marca.strip():
        partes.append(("marca", item.marca.strip()))
    preco, qtd = rg.ler_decimal(item.preco), rg.ler_decimal(i.get("quantidade"))
    if preco and preco > 0:
        partes.append(("preço", f"R$ {rg.formatar_decimal(preco)}"))
        if qtd:
            partes.append(("total", f"R$ {rg.formatar_decimal(preco * qtd)} "
                                    f"({rg.formatar_decimal(qtd)} × {rg.formatar_decimal(preco)})"))
    campos = "".join(f"<span><small>{e(k)}</small> {e(v)}</span>" for k, v in partes)
    msgs = "".join(f'<div class="me-err">{e(m)}</div>' for m in val.erros)
    msgs += "".join(f'<div class="me-av">{e(m)}</div>' for m in val.avisos)
    return f'<div class="me-linha"{pronta}><div class="me-campos">{campos}</div>{msgs}</div>'


def _quadro_cotacao(c: dict, hoje: date) -> str:
    """Tudo o que vale para a cotação inteira, num lugar só: o frete (com o
    porquê), o que o robô preenche no cabeçalho, os avisos e a observação do
    comprador, e quantos itens já estão prontos."""
    frete, motivo = frete_de(c)
    login = L.de(c["conta"])
    fixo = rg.CAMPOS_FIXOS_COTACAO
    validade = (f"{c['validade_dias']} dias (até {rg.validade_proposta(c['validade_dias'], hoje):%d/%m/%Y})"
                if c["validade_dias"] else "—")
    dados = (("login", login.rotulo), ("condição de pagamento", fixo["condicao_pagamento"]),
             ("telefone", fixo["telefone_contato"]), ("moeda", fixo["moeda"]),
             ("validade da proposta", validade))
    prontos = sum(not rg.validar_item(_entrada(i), hoje).erros for i in c["itens"])
    avisos = avisos_de(c)
    robo = ("" if login.robo_liberado else
            '<p class="me-err">O robô ainda não preenche este login: o formulário deste '
            'comprador não foi conferido. Use estas informações para responder pelo site do ME.</p>')
    return f"""<div class="cartao me-quadro">
<div class="me-frete me-frete-{frete.lower()}">Frete {frete}</div><small>{e(motivo)}</small>
<p><b id="me-prontos">{prontos}</b> de {len(c['itens'])} itens prontos</p>
<dl class="me-dados">{''.join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in dados)}</dl>
{robo}
{('<h3>Avisos do comprador</h3><ul class="me-avisos">'
  + ''.join(f'<li>{e(a)}</li>' for a in avisos) + '</ul>') if avisos else ''}
{f'<h3>Observação do comprador</h3><p class="me-obs">{e(c["obs_comprador"])}</p>' if c.get("obs_comprador") else ''}
</div>"""


def conferir(c: dict, hoje: date) -> tuple[rg.Resultado, dict[int, dict[str, str]]]:
    """Validação de `regras` + o que o robô vai digitar em cada item que passa."""
    itens = entradas(c)
    resultado = rg.validar_cotacao(itens, c["validade_dias"], hoje)
    conta = L.de(c["conta"]).empresa
    previa = {}
    for item in itens:
        if item.sem_cotacao or rg.validar_item(item, hoje).erros:
            continue
        previa[item.numero] = rg.campos_do_item(conta, item, hoje)
    return resultado, previa


def rodar_revisao(cid: int, usuario: str) -> None:
    """Uma chamada à IA com o preenchimento atual. Nunca levanta."""
    try:
        c = banco.me_cotacao(cid)
        resultado, previa = conferir(c, agora().date())
        rev = REVISOR(c, previa, resultado.erros, resultado.avisos,
                      obs_geral=c["obs_comprador"] or "")
        banco.me_atualizar(cid, revisao_ia=rev.como_json(),
                           revisao_em=agora().isoformat(timespec="seconds"),
                           revisao_assinatura=rv.assinatura(c))
        if rev.indisponivel:
            banco.me_registrar(cid, "revisão IA indisponível", rev.erro, usuario)
        else:
            por_nivel = {n: sum(a.nivel == n for a in rev.alertas) for n in rv.NIVEIS}
            banco.me_registrar(cid, f"revisão IA: {len(rev.alertas)} alertas",
                               " · ".join(x for x in (
                                   ", ".join(f"{v} {rv.ROTULO_NIVEL[n].lower()}"
                                             for n, v in por_nivel.items() if v),
                                   rev.modelo or "") if x),
                               usuario)
    finally:
        REVISANDO.discard(cid)


SUGERIR_NCM: Callable[..., Any] = sugestor_ncm.sugerir   # os testes trocam


def sugerir_ncm(cid: int, usuario: str) -> str:
    """IA nos itens que continuam SEM NCM (nem digitado, nem do comprador,
    nem lembrado). Preenche e etiqueta "sugerido pela IA"; nunca sobrescreve.
    Devolve a mensagem para a tela."""
    c = banco.me_cotacao(cid)
    vazios = [i for i in c["itens"] if not (i["ncm"] or "").strip()]
    if not vazios:
        return "Todos os itens já têm NCM."
    try:
        sugestoes, modelo = SUGERIR_NCM(vazios)
    except ia.IAIndisponivel:
        banco.me_registrar(cid, "sugestão de NCM indisponível", "nenhum modelo de IA respondeu", usuario)
        return "A IA está indisponível agora. Preencha o NCM à mão ou tente em alguns minutos."
    for numero, s in sugestoes.items():
        banco.me_gravar_entrada(cid, numero, ncm=s.ncm, ncm_origem="ia", ncm_nota=s.nota())
    faltam = len(vazios) - len(sugestoes)
    banco.me_registrar(cid, f"NCM sugerido pela IA: {len(sugestoes)} itens",
                       f"{modelo}" + (f" · {faltam} sem sugestão" if faltam else ""), usuario)
    return (f"A IA sugeriu o NCM de {len(sugestoes)} de {len(vazios)} itens. Confira cada um "
            "(etiqueta \"IA\" embaixo do campo) antes de salvar.")


def _lembrar_ncm_conferido(c: dict) -> None:
    """Salvou no ME com o NCM que a IA sugeriu: agora é resposta dada, vira
    memória do material (antes disso era palpite e não entrava)."""
    for i in c["itens"]:
        if i.get("ncm_origem") == "ia" and i["ncm"]:
            banco.me_lembrar_material(pn.chave_material(i["descricao"]), ncm=i["ncm"],
                                      marca=None, origem=None)


def _rodar_robo(cid: int, usuario: str, dry_run: bool, status_antes: str) -> None:
    c = banco.me_cotacao(cid)
    try:
        r = ROBO(c["conta"], c["numero"], entradas(c), c["validade_dias"], dry_run,
                 frete=frete_de(c)[0])
    except Exception as exc:
        r = None
        erro = f"{type(exc).__name__}: {exc}"[:500]
    else:
        erro = _campo(r, "erro")
    prints = list(_campo(r, "prints", []) or []) if r is not None else []
    divergencias = list(_campo(r, "divergencias", []) or []) if r is not None else []
    for aviso in (_campo(r, "avisos", []) or []) if r is not None else []:
        banco.me_registrar(cid, "aviso do robô", str(aviso), usuario)
    ok = r is not None and _campo(r, "ok", False) and not divergencias
    carimbo = agora().isoformat(timespec="seconds")
    evidencia = json.dumps([str(p) for p in prints]) if prints else None

    if dry_run:
        banco.me_trocar_status(cid, (Status.SALVANDO.value,), status_antes,
                               **({"evidencia": evidencia} if evidencia else {}))
        banco.me_registrar(cid, "teste sem salvar: " + ("ok" if ok else "falhou"),
                           "; ".join(divergencias) or erro or "", usuario)
    elif ok:
        banco.me_trocar_status(cid, (Status.SALVANDO.value,), Status.SALVA.value,
                               salvo_por=usuario, salvo_em=carimbo, erro=None,
                               evidencia=evidencia)
        banco.me_registrar(cid, "salva no ME", "conferida campo a campo depois de salvar", usuario)
        _lembrar_ncm_conferido(c)
    else:
        motivo = erro or ("divergência depois de salvar: " + "; ".join(divergencias))
        banco.me_trocar_status(cid, (Status.SALVANDO.value,), Status.ERRO.value,
                               erro=motivo, evidencia=evidencia)
        banco.me_registrar(cid, "erro do robô", motivo, usuario)


NAO_LIBERADO = ("O robô ainda não foi liberado para este login: o formulário do ME muda "
                "com o comprador e este ainda não foi conferido. Preencha pelo site do ME.")


def mandar_robo(cid: int, usuario: str, dry_run: bool) -> str | None:
    """Solta o robô numa thread. Devolve o motivo se não soltou."""
    c = banco.me_cotacao(cid)
    if not L.de(c["conta"]).robo_liberado:
        return NAO_LIBERADO
    resultado, _ = conferir(c, agora().date())
    if resultado.erros:
        return "Corrija os erros antes: " + " ".join(resultado.erros[:3])
    abertos = (Status.PENDENTE.value, Status.SALVA.value, Status.ERRO.value)
    if not banco.me_trocar_status(cid, abertos, Status.SALVANDO.value):
        return "Esta cotação não está aberta para salvar (ou o robô já está nela)."
    banco.me_registrar(cid, "robô: teste sem salvar" if dry_run else "robô: salvar no ME",
                       f"{len([i for i in c['itens'] if i['preco']])} itens com preço", usuario)
    DISPARAR(_rodar_robo, cid, usuario, dry_run, c["status"])
    return None


def _rodar_limpeza(cid: int, usuario: str, status_antes: str) -> None:
    c = banco.me_cotacao(cid)
    try:
        r = LIMPADOR(c["conta"], c["numero"], False)
    except Exception as exc:
        r, erro = None, f"{type(exc).__name__}: {exc}"[:500]
    else:
        erro = _campo(r, "erro")
    divergencias = list(_campo(r, "divergencias", []) or []) if r is not None else []
    prints = list(_campo(r, "prints", []) or []) if r is not None else []
    evidencia = {"evidencia": json.dumps([str(p) for p in prints])} if prints else {}
    if r is not None and _campo(r, "ok", False) and not divergencias:
        # O rascunho do ME voltou a ser cotação nova: para nós, pendente de
        # novo. O preenchimento desta tela fica, para salvar outra vez.
        banco.me_trocar_status(cid, (Status.SALVANDO.value,), Status.PENDENTE.value,
                               salvo_por=None, salvo_em=None, erro=None, **evidencia)
        banco.me_registrar(cid, "limpa no ME",
                           "rascunho apagado (itens, recusas e obs geral) e conferido", usuario)
        return
    salvou = r is not None and _campo(r, "salvo", False)
    motivo = "limpeza: " + (erro or "divergência depois de limpar: " + "; ".join(divergencias))
    if not salvou:
        motivo += " (nada foi gravado no ME)"
    banco.me_trocar_status(cid, (Status.SALVANDO.value,),
                           Status.ERRO.value if salvou or status_antes == Status.ERRO.value
                           else status_antes, erro=motivo[:500], **evidencia)
    banco.me_registrar(cid, "erro do robô", motivo[:500], usuario)


def mandar_limpeza(cid: int, usuario: str) -> str | None:
    """Solta o robô para apagar do rascunho do ME o que ele escreveu."""
    c = banco.me_cotacao(cid)
    if not L.de(c["conta"]).robo_liberado:
        return NAO_LIBERADO
    abertos = (Status.PENDENTE.value, Status.SALVA.value, Status.ERRO.value)
    if not banco.me_trocar_status(cid, abertos, Status.SALVANDO.value):
        return "Esta cotação não está aberta (ou o robô já está nela)."
    banco.me_registrar(cid, "robô: limpar no ME", "", usuario)
    DISPARAR(_rodar_limpeza, cid, usuario, c["status"])
    return None


# ------------------------------------------------------------------ telas
def _usuario(request: Request) -> str | None:
    return vendedor(request.cookies.get(COOKIE)) if vendedor else None


def _hora(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except ValueError:
        return iso


def _selo(status: str) -> str:
    s = Status(status)
    return f'<span class="me-selo me-{s.value}">{e(pn.ROTULO[s])}</span>'


CSS_ME = """<style>
.me-selo{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;
 font-weight:700;background:var(--tom-neutro-fraco);color:var(--tom-neutro)}
.me-pendente{background:var(--tom-marca-fraco);color:var(--tom-marca)}
.me-salvando{background:var(--tom-roxo-fraco);color:var(--tom-roxo)}
.me-salva{background:var(--tom-atencao-fraco);color:var(--tom-atencao)}
.me-erro,.me-vencida{background:var(--tom-erro-fraco);color:var(--tom-erro)}
.me-enviada{background:var(--tom-ok-fraco);color:var(--tom-ok)}
tr.me-urgente td{background:var(--alerta-fundo)}
.me-alerta{color:var(--tom-erro);font-weight:700;font-size:12px}
.me-filtros{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px}
.me-filtros a{padding:4px 10px;border:1px solid var(--borda);border-radius:99px;
 text-decoration:none;color:var(--tinta2);font-size:13px}
.me-filtros a.ativo{background:var(--marca);border-color:var(--marca);color:var(--sobre-marca)}
.me-itens input,.me-itens select{width:100%;min-width:0;padding:4px 6px}
.me-itens td{vertical-align:top}
.me-itens .me-desc{max-width:280px}
.me-itens details{font-size:12px;color:var(--fraco)}
.me-prev{font-family:var(--mono,monospace);font-size:12px;color:var(--tinta2)}
.me-err{color:var(--erro);font-size:12px}.me-av{color:var(--atencao);font-size:12px}
.me-acoes{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.me-mini{font-size:11px;padding:2px 6px;margin-top:4px}
.me-ncm{display:block;font-size:11px;color:var(--fraco);margin-top:3px;line-height:1.3}
.me-ncm-ia{color:var(--tom-roxo)}
.me-painel-ia{padding:12px 16px;margin:0 0 12px}
.me-ia{font-size:12px;font-weight:600}
.me-ia-critico{color:var(--tom-erro)}.me-ia-atencao{color:var(--tom-atencao)}
.me-ia-info{color:var(--tom-marca)}
.me-quadro{padding:12px 16px;margin:0 0 12px}
.me-frete{display:inline-block;padding:4px 12px;border-radius:99px;font-weight:800;font-size:15px;margin-right:8px}
.me-frete-cif{background:var(--tom-roxo-fraco);color:var(--tom-roxo)}
.me-frete-fob{background:var(--tom-marca-fraco);color:var(--tom-marca)}
.me-dados{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:8px 0;font-size:13px}
.me-dados dt{color:var(--fraco)}.me-dados dd{margin:0}
.me-avisos{margin:4px 0;padding-left:18px;font-size:13px}
.me-obs{white-space:pre-line;font-size:13px}
.me-linha{font-size:12px}
.me-campos{display:flex;flex-wrap:wrap;gap:4px 14px;font-family:var(--mono,monospace)}
.me-campos small{color:var(--fraco);font-family:inherit}
.me-falta{color:var(--fraco);font-style:italic}
.me-local{display:block;font-size:11px;color:var(--fraco)}
</style>"""


@router.get("", response_class=HTMLResponse)
def lista(request: Request, conta: str = "", status: str = "", msg: str = ""):
    usuario = _usuario(request)
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    conta = conta if conta in CONTAS else ""
    status = status if status in {s.value for s in Status} else ""
    momento = agora()
    linhas = ""
    for c in banco.me_cotacoes(conta or None, status or None):
        limite = pn.hora_de_brasilia(c["data_limite"])
        st = Status(c["status"])
        pz = pn.prazo(limite, momento) if st in pn.ABERTOS else None
        aviso = pn.alerta(st, limite, momento)
        classe = ' class="me-urgente"' if aviso else ""
        linhas += (
            f'<tr{classe}><td><a href="/me/{c["id"]}">{c["numero"]}</a></td>'
            f'<td>{e(CONTAS.get(c["conta"], c["conta"]))}</td>'
            f'<td>{e(c["empresa"] or "")}<br><small>{e(c["comprador"] or "")}</small></td>'
            f'<td>{e(c["codigo"] or "")}</td>'
            f'<td>{e(_hora(c["data_limite"]))}'
            + (f'<br><small>{e(pz.texto)}</small>' if pz else "") + "</td>"
            f'<td>{_selo(c["status"])}'
            + (f'<div class="me-alerta">{e(aviso)}</div>' if aviso else "") + "</td>"
            f'<td>{c["n_com_preco"]}/{c["n_itens"]}</td></tr>')

    def filtro(rotulo, **q):
        """Um link de filtro. Troca só a chave dele e mantém a outra."""
        alvo = {"conta": conta, "status": status, **q}
        url = "/me?" + "&".join(f"{k}={v}" for k, v in alvo.items() if v)
        chave, valor = next(iter(q.items()))
        ativo = {"conta": conta, "status": status}[chave] == valor
        classe = ' class="ativo"' if ativo else ""
        return f'<a href="{e(url)}"{classe}>{e(rotulo)}</a>'

    contas_html = filtro("Todas as contas", conta="") + "".join(
        filtro(n, conta=k) for k, n in CONTAS.items())
    status_html = filtro("Todos os status", status="") + "".join(
        filtro(pn.ROTULO[s], status=s.value) for s in Status if s is not Status.SALVANDO)

    configuradas = contas_configuradas()
    situacao = ("atualizando agora…" if VARREDURA.rodando else
                f"última leitura do ME: {VARREDURA.ultima:%d/%m %H:%M}" if VARREDURA.ultima
                else "ainda não leu o ME desde que o servidor subiu")
    erros = "".join(f'<p class="alerta">Falha ao ler {e(CONTAS.get(k, k))}: {e(v)}</p>'
                    for k, v in VARREDURA.erros.items())
    sem_conta = ("" if configuradas else
                 '<p class="alerta">Nenhuma conta do ME configurada: faltam '
                 'os LOGIN/SENHA de mercado_eletronico/logins.py no .env.</p>')
    acoes = ('<form method="post" action="/me/atualizar" style="margin:0">'
             '<button type="submit">Atualizar agora</button></form>')
    corpo = f"""{CSS_ME}
{cabecalho("Mercado Eletrônico", tarja="Cotações a responder",
           sub=f"O robô preenche e salva no ME; <b>quem envia é você</b>, pelo site do ME. {e(situacao)}.",
           acoes=acoes)}
{f'<p class="aviso">{e(msg)}</p>' if msg else ""}{sem_conta}{erros}
<div class="me-filtros">{contas_html}</div><div class="me-filtros">{status_html}</div>
<div class="cartao"><div class="rolagem-r"><table>
<thead><tr><th>cotação</th><th>conta</th><th>empresa / comprador</th><th>título</th>
<th>data limite</th><th>status</th><th>itens c/ preço</th></tr></thead>
<tbody>{linhas or '<tr><td colspan="7" class="sub">Nenhuma cotação aqui.</td></tr>'}</tbody>
</table></div></div>
<script>setTimeout(() => location.reload(), 5 * 60 * 1000);</script>"""
    return HTMLResponse(pagina("Mercado Eletrônico", corpo, usuario))


@router.post("/atualizar")
def botao_atualizar(request: Request):
    if not _usuario(request):
        return RedirectResponse("/login", status_code=303)
    if not contas_configuradas():
        return RedirectResponse("/me?msg=Nenhuma+conta+do+ME+configurada.", status_code=303)
    atualizar_em_segundo_plano()
    return RedirectResponse("/me?msg=Lendo+o+ME+agora.+Recarregue+em+alguns+segundos.",
                            status_code=303)


def _cotacao_ou_404(cid: int) -> dict:
    c = banco.me_cotacao(cid)
    if not c:
        from fastapi import HTTPException
        raise HTTPException(404, "Cotação do ME não encontrada.")
    return c


def _etiqueta_ncm(i: dict) -> str:
    """De onde veio o NCM do campo, embaixo dele. E o alerta que não precisa
    de IA: o comprador escreveu um NCM e o campo tem outro."""
    rg_ncm = rg.normalizar_ncm
    partes = []
    if i.get("ncm_origem") == "comprador":
        partes.append('<small class="me-ncm">do comprador</small>')
    elif i.get("ncm_origem") == "memoria":
        partes.append('<small class="me-ncm">lembrado deste material</small>')
    elif i.get("ncm_origem") == "ia":
        partes.append(f'<small class="me-ncm me-ncm-ia" title="{e(i.get("ncm_nota") or "")}">'
                      f'IA · {e(i.get("ncm_nota") or "")} — confira</small>')
    if (i.get("ncm_pedido") and i.get("ncm")
            and rg_ncm(i["ncm"]) != rg_ncm(i["ncm_pedido"])):
        partes.append(f'<small class="me-av">o comprador pediu {e(i["ncm_pedido"])}</small>')
    return "".join(partes)


def _opcoes_origem(valor) -> str:
    return "".join(
        f'<option value="{v}"{" selected" if str(valor) == v else ""}>{r}</option>'
        for v, r in (("", "—"), ("0", "0 - Nacional"), ("2", "2 - Estrangeira (merc. interno)")))


@router.get("/{cid}", response_class=HTMLResponse)
def ver(cid: int, request: Request, msg: str = ""):
    usuario = _usuario(request)
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = _cotacao_ou_404(cid)
    st = Status(c["status"])
    momento = agora()
    limite = pn.hora_de_brasilia(c["data_limite"])
    pz = pn.prazo(limite, momento)
    aviso = pn.alerta(st, limite, momento)
    editavel = st in (Status.PENDENTE, Status.SALVA, Status.ERRO)
    trava = "" if editavel else " disabled"
    # Login sem robô liberado: a tela serve para ler e preencher pelo site do ME.
    trava_robo = trava if L.de(c["conta"]).robo_liberado else f' disabled title="{e(NAO_LIBERADO)}"'

    resultado, _ = conferir(c, momento.date()) if c["itens"] else (rg.Resultado(), {})
    por_item: dict[int, list[str]] = {}
    # Os de cada item saem na prévia da linha (linha_previa); aqui só os da
    # cotação inteira.
    for tipo, lista_msgs in (("err", resultado.erros), ("av", resultado.avisos)):
        for m in lista_msgs:
            if not m.startswith("Item "):
                por_item.setdefault(None, []).append(f'<div class="me-{tipo}">{e(m)}</div>')

    rev = rv.Revisao.de_json(c["revisao_ia"])
    # Os da cotação inteira (item None) ficam só no quadro da revisão.
    for a in (a for a in (rev.alertas if rev else []) if a.item is not None):
        por_item.setdefault(a.item, []).append(
            f'<div class="me-ia me-ia-{a.nivel}">IA · {e(rv.ROTULO_NIVEL[a.nivel])}: {e(a.mensagem)}</div>')
    painel_ia = _painel_ia(c, rev, cid in REVISANDO)

    linhas = ""
    for i in c["itens"]:
        n = i["numero"]
        pedido = " · ".join(x for x in (
            f"entrega {i['uf_destino']}" if i["uf_destino"] else "UF de entrega não achada",
            f"origem pedida {i['origem_pedida']}" if i["origem_pedida"] is not None else "",
            f"remessa {date.fromisoformat(i['data_remessa']):%d/%m/%Y}" if i["data_remessa"] else "",
        ) if x)
        prev = f'<div id="linha-{n}">{linha_previa(c, i, momento.date())}</div>'
        local = (f'<span class="me-local">entrega em {e(i["local_entrega"])}</span>'
                 if i.get("local_entrega") else "")
        linhas += f"""<tr data-item="{n}">
<td><b>{n}</b></td>
<td class="me-desc"><b>{e(i['descricao'])}</b><br><small>{e(i['quantidade'])} {e(i['unidade'])} · {e(pedido)}</small>{local}
<details><summary>pedido do comprador</summary>{e(i['obs_comprador'])}<br><i>{e(i['campos_adicionais'])}</i></details></td>
<td><input name="preco_{n}" value="{e(i['preco'] or '')}" inputmode="decimal" placeholder="0,00"{trava}></td>
<td><input name="ncm_{n}" value="{e(i['ncm'] or '')}" maxlength="10" placeholder="8 dígitos"{trava}>{_etiqueta_ncm(i)}</td>
<td><input name="prazo_{n}" value="{e(i['prazo_dias'] or '')}" inputmode="numeric" data-copiar="prazo"{trava}></td>
<td><input name="marca_{n}" value="{e(i['marca'] or '')}" maxlength="{rg.MAX_MARCA}" data-copiar="marca"{trava}></td>
<td><input name="obs_{n}" value="{e(i['obs'] or '')}" maxlength="{MAX_OBS}"{trava}></td>
<td><select name="origem_{n}" data-copiar="origem"{trava}>{_opcoes_origem(i['origem'])}</select>
<button type="button" class="botao2 me-mini" data-anterior{trava}>↑ copiar anterior</button></td>
</tr><tr><td></td><td colspan="7">{prev}{''.join(por_item.get(n, []))}</td></tr>"""

    gerais = "".join(por_item.get(None, []))
    historico = "".join(
        f"<li><small>{e(_hora(h['quando']))}</small> <b>{e(h['evento'])}</b>"
        f"{' — ' + e(h['detalhe']) if h['detalhe'] else ''}"
        f"{' (' + e(h['usuario']) + ')' if h['usuario'] else ''}</li>"
        for h in reversed(banco.me_historico(cid)))
    prints = ""
    if c["evidencia"]:
        try:
            prints = "".join(f"<li>{e(p)}</li>" for p in json.loads(c["evidencia"]))
        except ValueError:
            prints = ""

    sem_ncm = sum(not (i["ncm"] or "").strip() for i in c["itens"])
    botao_ncm = (f'<button type="submit" name="acao" value="ncm" class="botao2"{trava}'
                 f' title="A IA sugere o NCM dos {sem_ncm} itens sem NCM; você confere">'
                 f'Sugerir NCM com IA ({sem_ncm})</button>'
                 if sem_ncm and ia.configurada() else "")
    if not c["itens"]:
        itens_html = (f'<p class="sub">Os itens ainda não foram lidos do ME.</p>'
                      f'<form method="post" action="/me/{cid}/ler"><button type="submit">'
                      f'Ler itens do ME</button></form>')
    else:
        itens_html = f"""<form method="post" action="/me/{cid}" id="form-me">
<p><label>Validade da proposta (dias) <input name="validade_dias" value="{e(c['validade_dias'] or '')}"
 inputmode="numeric" style="width:6em"{trava}></label>
 <button type="button" class="botao2" data-aplicar="marca"{trava}>marca do 1º em todos</button>
 <button type="button" class="botao2" data-aplicar="origem"{trava}>origem do 1º em todos</button>
 <button type="button" class="botao2" data-aplicar="prazo"{trava}>prazo do 1º em todos</button>
 {botao_ncm}</p>
{_quadro_cotacao(c, momento.date())}{painel_ia}{gerais}
<div class="cartao"><div class="rolagem-r"><table class="me-itens">
<thead><tr><th>item</th><th>o que o comprador pediu</th><th>preço unit.</th><th>NCM</th>
<th>prazo (dias)</th><th>marca ({rg.MAX_MARCA})</th><th>obs ({MAX_OBS})</th><th>origem</th></tr></thead>
<tbody>{linhas}</tbody></table></div></div>
<div class="me-acoes">
<button type="submit" name="acao" value="conferir"{trava}>Guardar e conferir</button>
<button type="submit" name="acao" value="salvar"{trava_robo}
 onclick="return confirm('O robô vai preencher e SALVAR no ME. Ele não envia: depois alguém confere e envia pelo site do ME.')">Salvar no ME</button>
<button type="submit" name="acao" value="dry_run" class="botao2"{trava_robo}>Testar sem salvar</button>
<button type="submit" name="acao" value="revisar" class="botao2"{trava}>Revisar com IA</button>
</div></form>"""

    marcar = ("" if st in pn.FINAIS else
              f'<form method="post" action="/me/{cid}/enviada" style="margin:0" '
              f'onsubmit="return confirm(\'Confirma que esta cotação JÁ FOI ENVIADA pelo site do ME?\')">'
              f'<button type="submit" class="botao2">Marcar como enviada</button></form>')
    ler_de_novo = (f'<form method="post" action="/me/{cid}/ler" style="margin:0">'
                   f'<button type="submit" class="botao2">Reler itens do ME</button></form>'
                   if c["itens"] and editavel else "")
    limpar = (f'<form method="post" action="/me/{cid}/limpar" style="margin:0" '
              f'onsubmit="return confirm(\'O robô vai APAGAR no ME tudo o que ele escreve nesta cotação '
              f'(preços, impostos, NCM, prazo, marca, obs, recusas de item e a obs geral) e salvar. '
              f'Não envia nada. Continuar?\')">'
              f'<button type="submit" class="botao2">Limpar no ME</button></form>'
              if editavel and L.de(c["conta"]).robo_liberado else "")
    link_me = (f'<a class="botao2" target="_blank" rel="noopener" '
               f'href="https://www.me.com.br/RespostaCotaItem.asp?Cotacao={c["numero"]}&SuperCleanPage=">'
               f'Abrir no ME</a>')
    sub = (f'{_selo(c["status"])} '
           + (f'<span class="me-alerta">{e(aviso)}</span>' if aviso else "")
           + (f'<br>Erro: {e(c["erro"])}' if st is Status.ERRO and c["erro"] else "")
           + (f'<br>Salva por {e(c["salvo_por"])} em {e(_hora(c["salvo_em"]))}' if c["salvo_em"] else ""))
    corpo = f"""{CSS_ME}
{cabecalho(f"Cotação {c['numero']}", tarja=f"Mercado Eletrônico · {CONTAS.get(c['conta'], c['conta'])}",
           sub=sub, contexto=(("prazo", f"{_hora(c['data_limite'])} ({pz.texto})"),
                              ("empresa", c["empresa"] or "—"), ("comprador", c["comprador"] or "—"),
                              ("título", c["codigo"] or "—")),
           acoes=link_me + ler_de_novo + limpar + marcar)}
{f'<p class="aviso">{e(msg)}</p>' if msg else ""}
{'' if editavel else '<p class="aviso">Edição fechada neste status.</p>'}
{itens_html}
<h2>Histórico</h2><ul>{historico or '<li class="sub">nada ainda</li>'}</ul>
{f'<h2>Prints do robô</h2><ul>{prints}</ul>' if prints else ''}
<p><a href="/me">← voltar à lista</a></p>
<script>
// "marca do 1º em todos" e "copiar anterior": só copiam no formulário;
// nada vai para o ME sem os botões de baixo.
document.querySelectorAll("[data-aplicar]").forEach(b => b.addEventListener("click", () => {{
  const campos = [...document.querySelectorAll(`[data-copiar="${{b.dataset.aplicar}}"]`)];
  campos.slice(1).forEach(c => {{ c.value = campos[0].value; mudou(c); }});
}}));
document.querySelectorAll("[data-anterior]").forEach(b => b.addEventListener("click", () => {{
  const tr = b.closest("tr"); let ant = tr.previousElementSibling;
  while (ant && !ant.dataset.item) ant = ant.previousElementSibling;
  if (!ant) return;
  ["prazo", "marca", "origem"].forEach(k => {{
    const c = tr.querySelector(`[data-copiar="${{k}}"]`);
    c.value = ant.querySelector(`[data-copiar="${{k}}"]`).value; mudou(c);
  }});
  const ncm = [...ant.querySelectorAll("input")].find(i => i.name.startsWith("ncm_"));
  const meu = [...tr.querySelectorAll("input")].find(i => i.name.startsWith("ncm_"));
  if (ncm && meu) {{ meu.value = ncm.value; mudou(meu); }}
}}));
// A linha se completa enquanto o usuário preenche: a prévia vem do servidor
// (as mesmas regras do robô) e NÃO grava nada — gravar é "Guardar e conferir".
const esperando = {{}};
function previa(tr) {{
  const n = tr.dataset.item;
  clearTimeout(esperando[n]);
  esperando[n] = setTimeout(async () => {{
    const q = new URLSearchParams();
    tr.querySelectorAll("input[name], select[name]").forEach(c => q.set(c.name.replace(/_\\d+$/, ""), c.value));
    const r = await fetch(`/me/{cid}/linha/${{n}}?${{q}}`);
    if (!r.ok) return;
    document.getElementById(`linha-${{n}}`).innerHTML = await r.text();
    const p = document.getElementById("me-prontos");
    if (p) p.textContent = document.querySelectorAll('.me-linha[data-pronta="1"]').length;
  }}, 250);
}}
function mudou(campo) {{ const tr = campo.closest("tr[data-item]"); if (tr) previa(tr); }}
document.querySelectorAll("tr[data-item]").forEach(tr => {{
  tr.addEventListener("input", () => previa(tr));
  tr.addEventListener("change", () => previa(tr));
}});
{'setTimeout(() => location.reload(), 5000);' if st is Status.SALVANDO or cid in REVISANDO else ''}
</script>"""
    return HTMLResponse(pagina(f"ME {c['numero']}", corpo, usuario))


def _painel_ia(c: dict, rev: rv.Revisao | None, rodando: bool) -> str:
    """O quadro da revisão por IA, acima dos itens. Os alertas de item vão
    também na linha do item; aqui fica o resumo e os da cotação inteira."""
    if rodando:
        corpo = '<p class="sub">A IA está revisando… (a página recarrega sozinha)</p>'
    elif rev is None:
        corpo = ('<p class="sub">Ainda não revisada. "Revisar com IA" confere marca, '
                 'local de entrega, NCM e preço contra o que o comprador pediu. '
                 'Só aponta; não muda nada.</p>')
    elif rev.indisponivel:
        corpo = f'<p class="alerta">Revisão IA indisponível: {e(rev.erro)}. Pode salvar mesmo assim.</p>'
    else:
        contagem = " · ".join(
            f'<span class="me-ia-{n}">{sum(a.nivel == n for a in rev.alertas)} {rv.ROTULO_NIVEL[n].lower()}</span>'
            for n in rv.NIVEIS)
        velha = ("" if c["revisao_assinatura"] == rv.assinatura(c) else
                 '<p class="aviso">O preenchimento mudou depois desta revisão — revise de novo.</p>')
        gerais = "".join(f'<li class="me-ia-{a.nivel}">{e(rv.ROTULO_NIVEL[a.nivel])}: {e(a.mensagem)}</li>'
                         for a in rev.alertas if a.item is None)
        corpo = (f'<p>{contagem if rev.alertas else "Nenhum alerta."} '
                 f'<small>({e(_hora(c["revisao_em"]))}{", " + e(rev.modelo) if rev.modelo else ""})</small></p>'
                 f'{velha}' + (f"<ul>{gerais}</ul>" if gerais else ""))
    return f'<div class="cartao me-painel-ia"><b>Revisão por IA</b>{corpo}</div>'


def _voltar(cid: int, msg: str = "") -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(f"/me/{cid}" + (f"?msg={quote(msg)}" if msg else ""), status_code=303)


@router.get("/{cid}/linha/{numero}", response_class=HTMLResponse)
def previa_da_linha(cid: int, numero: int, request: Request, preco: str | None = None,
                    ncm: str | None = None, prazo: str | None = None, marca: str | None = None,
                    obs: str | None = None, origem: str | None = None):
    """A prévia de UM item com o que está na tela agora. Só calcula: não grava."""
    if not _usuario(request):
        return HTMLResponse("", status_code=401)
    c = _cotacao_ou_404(cid)
    item = next((i for i in c["itens"] if i["numero"] == numero), None)
    if item is None:
        return HTMLResponse("", status_code=404)
    tela = {"preco": preco, "ncm": ncm, "marca": marca, "obs": obs}
    mudou = {k: v.strip() for k, v in tela.items() if v is not None}
    if prazo is not None:
        mudou["prazo_dias"] = _int(prazo)
    if origem is not None:
        mudou["origem"] = _int(origem)
    return HTMLResponse(linha_previa(c, {**item, **mudou}, agora().date()))


@router.post("/{cid}")
async def guardar(cid: int, request: Request):
    usuario = _usuario(request)
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = _cotacao_ou_404(cid)
    if Status(c["status"]) not in (Status.PENDENTE, Status.SALVA, Status.ERRO):
        return _voltar(cid, "Edição fechada neste status.")
    form = dict(await request.form())
    gravar_formulario(cid, form)
    acao = form.get("acao", "conferir")
    if acao == "revisar":
        if cid not in REVISANDO:
            REVISANDO.add(cid)
            DISPARAR(rodar_revisao, cid, usuario)
        return _voltar(cid, "Revisão por IA pedida. Os alertas aparecem aqui.")
    if acao == "ncm":
        return _voltar(cid, sugerir_ncm(cid, usuario))
    if acao in ("salvar", "dry_run"):
        motivo = mandar_robo(cid, usuario, dry_run=acao == "dry_run")
        return _voltar(cid, motivo or ("Robô testando (sem salvar)…" if acao == "dry_run"
                                       else "Robô salvando no ME…"))
    banco.me_registrar(cid, "preenchimento guardado", "", usuario)
    return _voltar(cid, "Guardado. Confira os avisos em cada item.")


@router.post("/{cid}/ler")
def ler_itens(cid: int, request: Request):
    usuario = _usuario(request)
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    _cotacao_ou_404(cid)
    try:
        n = carregar_itens(cid)
    except Exception as exc:
        motivo = f"{type(exc).__name__}: {exc}"[:300]
        banco.me_registrar(cid, "erro ao ler itens do ME", motivo, usuario)
        return _voltar(cid, f"Não consegui ler os itens do ME: {motivo}")
    banco.me_registrar(cid, "itens lidos do ME", f"{n} itens", usuario)
    return _voltar(cid, f"{n} itens lidos do ME.")


@router.post("/{cid}/limpar")
def limpar_no_me(cid: int, request: Request):
    usuario = _usuario(request)
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    _cotacao_ou_404(cid)
    motivo = mandar_limpeza(cid, usuario)
    return _voltar(cid, motivo or "Robô limpando no ME… (a página recarrega sozinha)")


@router.post("/{cid}/enviada")
def marcar_enviada(cid: int, request: Request):
    usuario = _usuario(request)
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = _cotacao_ou_404(cid)
    if Status(c["status"]) in pn.FINAIS:
        return _voltar(cid)
    banco.me_atualizar(cid, status=Status.ENVIADA.value,
                       enviada_em=agora().isoformat(timespec="seconds"))
    banco.me_registrar(cid, "marcada como enviada", "à mão, na tela", usuario)
    return _voltar(cid, "Marcada como enviada.")


# ------------------------------------------------------------ documentação
def secao_documentacao() -> str:
    """A parte do Mercado Eletrônico na aba Documentação.

    Os números saem das constantes que a tela usa de verdade (intervalo da
    varredura, limites de caracteres do ME, janela de "fecha em breve"): é a
    regra da aba inteira — ajuda com número velho faz errar com confiança."""
    horas = int(pn.JANELA_URGENTE.total_seconds() // 3600)
    return f"""<h2>Mercado Eletrônico: responder cotações</h2>
<div class="alerta email">
<p><b>O sistema preenche e SALVA a resposta no ME. Quem envia é sempre você</b>,
pelo site do ME, depois de conferir. Não existe botão de enviar aqui — de
propósito: o robô tem três travas que impedem o envio.</p>
</div>
<ol class="passo">
<li>Abra <a href="/me">Mercado Eletrônico</a> no menu. A lista traz as cotações
pendentes da <b>VENTURA</b> e da <b>UNIÃO</b>, com a data limite contando. Ela
se atualiza sozinha a cada <b>{INTERVALO_S // 60} minutos</b>; o botão
<b>Atualizar agora</b> lê o ME na hora.</li>
<li>Clique no número da cotação e em <b>Ler itens do ME</b>. Cada item mostra
o que o comprador pediu: descrição, quantidade, estado de entrega, origem e
data de remessa, e o texto dele (abra "pedido do comprador").</li>
<li>Preencha só o que muda: <b>preço unitário, NCM, prazo em dias corridos,
marca (até {rg.MAX_MARCA} caracteres), observação (até {MAX_OBS}) e origem
(0 ou 2)</b>, e a validade da proposta em dias. Item que você não vai cotar:
deixe o preço vazio e escreva o motivo na observação — o robô usa o
<b>"Recusar item"</b> do ME com esse motivo como justificativa. Impostos, data de entrega,
frete, condição de pagamento e o resto o sistema calcula. NCM, marca e origem
de um material que já apareceu voltam sozinhos.</li>
<li><b>NCM:</b> quando o comprador escreve o NCM no pedido, ele já vem no campo
(etiqueta "do comprador"). Se você trocar por outro, a tela lembra qual o
comprador pediu. Para os itens que ficarem sem NCM, <b>Sugerir NCM com IA</b>
preenche só os vazios, com a etiqueta "IA", a descrição da posição e a
confiança — <b>confira cada um</b>. O NCM sugerido só passa a ser lembrado para
aquele material depois que você salva no ME com ele ou o corrige.</li>
<li><b>Guardar e conferir</b> mostra, embaixo de cada item, o que o robô vai
digitar (ICMS, PIS, COFINS, data de entrega) e os problemas: em
<span style="color:var(--erro)">vermelho</span> o que impede salvar, em
amarelo o que vale conferir.</li>
<li><b>Revisar com IA</b> (opcional) lê o pedido do comprador e a sua resposta
e aponta o que a conta não pega: marca diferente da pedida, entrega em outro
lugar, NCM que não combina, preço fora de escala. Ela <b>só aponta, nunca muda
valor</b>. Se estiver indisponível, dá para salvar do mesmo jeito.</li>
<li><b>Salvar no ME</b> (ou <b>Testar sem salvar</b>, que preenche sem gravar).
Depois de salvar o robô reabre a página e confere campo a campo; se algo não
bateu, a cotação fica em <b>Erro</b> com o motivo.</li>
<li>Precisa desfazer? <b>Limpar no ME</b> (no topo da cotação) apaga do
rascunho do ME tudo o que o robô escreve: preços, impostos, NCM, prazo, marca,
observações, recusas de item e a observação geral. Os itens voltam a ficar
como a cotação chegou e ela volta a <b>Pendente</b>; o que você digitou aqui
continua, para salvar de novo. Frete, telefone, validade e moeda ficam — o ME
não deixa salvar sem eles. Também é um Salvar: não envia nada.</li>
<li>Entre no ME, confira e <b>envie</b>. O sistema percebe o envio sozinho
(o ME passa a dizer "Respondida", ou a cotação sai das pendências); se quiser
adiantar, use <b>Marcar como enviada</b>.</li>
</ol>
<p><b>Status:</b> Pendente → Salva no ME → Enviada. Também: Erro (o robô
falhou; o motivo aparece na cotação), Vencida (saiu do ME depois do prazo) e
Recusada. Faltando menos de <b>{horas} horas</b>, a linha fica vermelha — e
"<b>Salva no ME mas NÃO enviada</b>" é o aviso que não pode ser ignorado: o
ME não trata rascunho como resposta.</p>"""
