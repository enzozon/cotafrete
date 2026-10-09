"""Planilha ⇄ portal: prévia padrão, merge de três pontas e exclusões preservadas (3.8)."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import tempfile
import time
from collections import Counter
from contextlib import nullcontext
from pathlib import Path

from cruzar_nf import cadastro_pedidos as CP, nf_planilha as NP, planilha_edicao as PE
from cruzar_nf.arquivo_pedidos import ArquivoPedidosConcorrente, ConflitoGravacao
from cruzar_nf.maestro import _guardar_backup
from cruzar_nf.planilha_portal import (EDITAVEIS, IDENTIDADE, carregar_ignorar, conferir, formato_data_portal,
                                      normalizar, parear)
from cruzar_nf.sincronizar import trava, SincronizacaoEmAndamento

ARQ_ESTADO = 'sync_planilha_portal.json'
ARQ_RELATORIO = 'sync_planilha_portal_relatorio.json'
LISTAS = ('acoes', 'conflitos', 'ambiguas', 'removidos', 'historico', 'pendentes')


def _ler(pasta, nome):
    arq = Path(pasta) / nome
    return json.loads(arq.read_text(encoding='utf-8')) if arq.exists() else {}


def _salvar(pasta, nome, dados):
    fd, tmp = tempfile.mkstemp(prefix='.sync_planilha_', dir=str(pasta))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False, indent=1)
        os.replace(tmp, str(Path(pasta) / nome))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _valores(linha, formato_data='dmy'):
    return {nome: normalizar(nome, CP._campo(linha, nome), formato_data) for nome in IDENTIDADE + EDITAVEIS}


def _registro(excel, portal, antigo=False):
    base = {}
    formato = formato_data_portal(excel, portal)
    if excel is not None and portal is not None:
        for nome in IDENTIDADE + EDITAVEIS:
            try:
                a, b = normalizar(nome, CP._campo(excel, nome)), normalizar(nome, CP._campo(portal, nome), formato)
                if a == b:
                    base[nome] = a
            except ValueError:
                pass
    return {'excel': excel, 'portal': portal, 'base': base, 'historico': antigo,
            'chaves': sorted({CP.chave(p) for p in (excel, portal) if p is not None}),
            'removido_excel': False, 'removido_portal': False, 'formato_data_portal': formato}


def planejar(linhas, pedidos, estado, ignorar, vistos):
    primeira = not estado
    proximo = copy.deepcopy(estado) if estado else {'versao': 1, 'itens': {}}
    if proximo.get('versao') != 1:
        raise ValueError('Versão desconhecida do estado da sincronização.')
    itens = proximo['itens']
    r = dict(gerado_em=dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
             primeira_vez=primeira, gravou=False, adiado=False, aviso=None,
             **{nome: [] for nome in LISTAS})
    r['conferencia'] = conferir(linhas, pedidos, ignorar)
    pares = parear(linhas, pedidos)
    inverso = {i: [n for n, indices in pares.items() if i in indices] for i in range(len(pedidos))}
    consumidos = set()
    grupos = []
    for n, l in linhas:
        if len(pares[n]) > 1 or any(len(inverso[i]) > 1 for i in pares[n]):
            r['ambiguas'].append({'linha': n, 'chave': CP.chave(l), 'candidatos': pares[n]})
            consumidos.update(pares[n])
            if primeira:
                itens.setdefault(CP.chave(l), _registro(l, None, True))
            continue
        i = pares[n][0] if pares[n] else None
        if i is not None:
            consumidos.add(i)
        grupos.append((n, l, i, pedidos[i] if i is not None else None))
    grupos.extend((None, None, i, p) for i, p in enumerate(pedidos) if i not in consumidos)
    duplicadas = {k for contagem in (Counter(CP.chave(l) for _, l in linhas),
                                    Counter(CP.chave(p) for p in pedidos))
                  for k, quantidade in contagem.items() if quantidade > 1}
    for n, l, i, p in grupos:
        atual = l if l is not None else p
        k = CP.chave(atual)
        if any(CP.chave(x) in ignorar for x in (l, p) if x is not None):
            continue
        if any(CP.chave(x) in duplicadas for x in (l, p) if x is not None):
            r['ambiguas'].append({'linha': n, 'chave': k, 'erro': 'Chave repetida'})
            if primeira:
                itens.setdefault(k, _registro(l, p, True))
            continue
        achados = [key for key, registro in itens.items() if k in registro['chaves']]
        if not achados:
            achados = [key for key, registro in itens.items() if any(
                CP.correspondentes(atual, [x]) for x in (registro['excel'], registro['portal']) if x is not None)]
        if len(achados) > 1:
            r['ambiguas'].append({'linha': n, 'chave': k, 'estado': achados})
            continue
        registro = itens[achados[0]] if achados else None
        if registro and set(registro['chaves']) & ignorar:
            continue
        if primeira:
            itens[k] = _registro(l, p, antigo=(l is None or p is None))
            if l is None or p is None:
                r['historico'].append({'chave': k, 'lado': 'portal' if l is None else 'excel'})
            continue
        if l is None or p is None:
            lado = 'excel' if l is None else 'portal'
            if registro:
                if registro[lado] is not None:
                    registro['removido_' + lado] = True
                    r['removidos'].append({'chave': k, 'lado': lado})
                else:
                    r['historico'].append({'chave': k, 'lado': 'portal' if l is None else 'excel'})
                continue
            pendente = any(a['chave'] == k for a in estado.get('pendente', []))
            if p is None and k in vistos and not pendente:
                itens[k] = _registro(l, p, True)
                r['historico'].append({'chave': k, 'lado': 'excel'})
                continue
            try:
                _valores(atual)
            except ValueError as e:
                r['pendentes'].append({'chave': k, 'erro': str(e)})
                continue
            if not CP.completa(atual):
                r['pendentes'].append({'chave': k, 'erro': 'Pedido incompleto'})
                continue
            r['acoes'].append({'chave': k, 'destino': 'excel' if l is None else 'portal',
                               'tipo': 'novo', 'linha': n, 'pedido': CP._sem_colunas_do_robo(atual)})
            continue
        if registro is None:
            itens[k] = _registro(l, p)
            registro = itens[k]
        if registro['removido_excel'] or registro['removido_portal']:
            r['removidos'].append({'chave': k, 'lado': 'reapareceu; exige revisão'})
            continue
        try:
            ve, vp = _valores(l), _valores(p, registro.get('formato_data_portal', 'dmy'))
        except ValueError as e:
            r['pendentes'].append({'chave': k, 'erro': str(e)})
            continue
        if any(ve[nome] != vp[nome] for nome in IDENTIDADE):
            r['conflitos'].append({'chave': k, 'linha': n, 'campo': 'IDENTIDADE',
                                   'erro': 'PEDIDO, RFQ ou PRODUTO mudou; revisão manual'})
            continue
        # Correção feita manualmente nas duas pontas pode atualizar a foto, nunca os identificadores.
        registro['chaves'] = sorted(set(registro['chaves']) | {CP.chave(l), CP.chave(p)})
        conflitos, alteracoes = [], []
        for nome in EDITAVEIS:
            a, b = ve[nome], vp[nome]
            if a == b:
                continue
            base = registro['base']
            if nome not in base or (a != base[nome] and b != base[nome]):
                conflitos.append({'chave': k, 'linha': n, 'campo': nome, 'base': base.get(nome),
                                   'excel': CP._campo(l, nome), 'portal': CP._campo(p, nome)})
            else:
                destino = 'portal' if a != base[nome] else 'excel'
                alteracoes.append({'chave': k, 'tipo': 'campo', 'destino': destino, 'linha': n,
                                    'indice': i, 'campo': nome,
                                    'antes': CP._campo(p if destino == 'portal' else l, nome),
                                    'valor': CP._campo(l if destino == 'portal' else p, nome)})
                alteracoes[-1]['formato_antes'] = registro.get('formato_data_portal', 'dmy') if destino == 'portal' else 'dmy'
                if nome == 'DATA DE ENTREGA' and destino == 'excel' and vp[nome] is not None:
                    alteracoes[-1]['valor'] = dt.datetime.strptime(vp[nome], '%Y-%m-%d').strftime('%d/%m/%Y')
        if conflitos:
            r['conflitos'].extend(conflitos)
        else:
            r['acoes'].extend(alteracoes)
            if not alteracoes:
                registro['base'] = ve
                registro['excel'], registro['portal'] = l, p
    if primeira:
        proximo['inicializado_em'] = r['gerado_em']
    return r, proximo


def _marcar_vistos(pasta, linhas, acoes):
    estado = CP.carregar_estado(pasta)
    vistos = set(estado.get('vistos', []))
    if 'vistos' not in estado:
        vistos.update(CP.chave(l) for _, l in linhas)
    vistos.update(a['chave'] for a in acoes if a['tipo'] == 'novo')
    estado['vistos'] = sorted(vistos)
    CP._salvar_estado(pasta, estado)


def _gravar_portal(caminho, acoes, pasta, dormir):
    manager = ArquivoPedidosConcorrente(caminho, dormir=dormir)
    for tentativa in range(6):
        manager.iniciar()
        lista = manager.pedidos['PEDIDOS']
        mudou = False
        for a in acoes:
            if a['destino'] != 'portal':
                continue
            if a['tipo'] == 'novo':
                candidatos = CP.correspondentes(a['pedido'], lista)
                if len(candidatos) > 1:
                    raise ConflitoGravacao('Cadastro ficou ambíguo no portal.')
                if not candidatos:
                    lista.append(CP._sem_colunas_do_robo(a['pedido']))
                    mudou = True
                continue
            indices = [i for i, p in enumerate(lista) if CP.chave(p) == a['chave']]
            if len(indices) != 1:
                raise ConflitoGravacao('Pedido mudou ou foi apagado; nova comparação necessária.')
            p = lista[indices[0]]
            if CP._campo(p, a['campo']) == a['valor']:
                continue
            atual = normalizar(a['campo'], CP._campo(p, a['campo']), a.get('formato_antes', 'dmy'))
            if atual == normalizar(a['campo'], a['valor']):
                continue
            if atual != normalizar(a['campo'], a['antes'], a.get('formato_antes', 'dmy')):
                raise ConflitoGravacao('Campo mudou no portal; não sobrescrevo a edição.')
            nome = next((k for k in p if k.strip().upper() == a['campo']), a['campo'])
            p[nome] = a['valor']
            mudou = True
        if not mudou:
            return
        if tentativa == 0:
            _guardar_backup(caminho, str(Path(pasta) / 'backups'), 'PEDIDOS antes da sincronizacao planilha')
        try:
            manager.salvar()
        except ConflitoGravacao:
            continue
        dormir(3)
    raise ConflitoGravacao('Portal mudou em todas as tentativas; operação fica pendente.')


def sincronizar(planilha, caminho_pedidos, pasta_dados, gravar=False, dormir=time.sleep,
                antes_de_trocar=None, agora=None, diario=False):
    agora = agora or dt.datetime.now()
    pasta = Path(pasta_dados)
    if gravar:
        pasta.mkdir(parents=True, exist_ok=True)
    if diario:
        rel = _ler(pasta, ARQ_RELATORIO)
        if (agora.weekday() >= 5 or not (dt.time(12, 30) <= agora.time() <= dt.time(18))
                or (rel.get('concluido_em', '').startswith(agora.strftime('%d/%m/%Y')))):
            return {'sem_mudanca': True, 'acoes': []}
    with trava(pasta, 'Sincronização planilha/portal') if gravar else nullcontext():
        with trava(pasta, 'Pedidos na planilha', arquivo=NP.ARQ_TRAVA) if gravar else nullcontext():
            return _rodar(planilha, caminho_pedidos, pasta, gravar, dormir, antes_de_trocar)


def _rodar(planilha, caminho_pedidos, pasta, gravar, dormir, antes_de_trocar):
    assinatura = CP._assinatura(planilha)
    original = Path(planilha).read_bytes()
    if CP._assinatura(planilha) != assinatura:
        raise NP.GravacaoRecusada('Planilha mudou durante a leitura.')
    # Leitura do mesmo snapshot usado na edição, sem uma segunda leitura da rede.
    with tempfile.TemporaryDirectory(prefix='sync_planilha_') as temp:
        copia = Path(temp) / 'planilha.xlsx'
        copia.write_bytes(original)
        linhas = CP.ler_planilha_com_linhas(str(copia))
    manager = ArquivoPedidosConcorrente(caminho_pedidos, dormir=dormir)
    manager.iniciar()
    assinatura_portal = manager._assinatura
    estado = _ler(pasta, ARQ_ESTADO)
    ignorar = carregar_ignorar(str(pasta))
    vistos = set(CP.carregar_estado(str(pasta)).get('vistos', []))
    r, proximo = planejar(linhas, manager.pedidos['PEDIDOS'], estado, ignorar, vistos)
    colunas, formulas, _epoch = PE.ler(original)
    linhas_formula = {n for n, _ in linhas if any(colunas.get(nome, '') + str(n) in formulas for nome in EDITAVEIS)}
    chaves_formula = {CP.chave(l) for n, l in linhas if n in linhas_formula}
    if not r['primeira_vez']:
        for k in chaves_formula:
            r['pendentes'].append({'chave': k, 'erro': 'Campo sincronizável contém fórmula ou mesclagem; revisão manual'})
    bloqueadas = {a['chave'] for a in r['acoes'] if a['tipo'] == 'campo'
                  and a['destino'] == 'excel' and colunas.get(a['campo'], '') + str(a['linha']) in formulas}
    for k in bloqueadas:
        r['pendentes'].append({'chave': k, 'erro': 'Célula de destino contém fórmula'})
    r['acoes'] = [a for a in r['acoes'] if a['chave'] not in bloqueadas | chaves_formula]
    mudancas = {}
    for a in r['acoes']:
        if a['tipo'] == 'campo' and a['destino'] == 'excel':
            mudancas.setdefault(a['linha'], {})[a['campo']] = a['valor']
    novas = [a['pedido'] for a in r['acoes'] if a['tipo'] == 'novo' and a['destino'] == 'excel']
    preparado = PE.preparar(original, mudancas, novas) if mudancas or novas else None
    if not gravar:
        return r
    if r['acoes']:
        aberta = NP.esta_aberta(planilha)
        if aberta:
            r.update(adiado=True, aviso=aberta)
            _salvar(pasta, ARQ_RELATORIO, r)
            return r
        if CP._assinatura(planilha) != assinatura:
            raise NP.GravacaoRecusada('Planilha mudou antes de gravar.')
        from cruzar_nf.arquivo_pedidos import _assinatura
        if _assinatura(caminho_pedidos) != assinatura_portal:
            raise ConflitoGravacao('Portal mudou; é necessário recalcular a rodada.')
        pendente = copy.deepcopy(estado)
        if not pendente:
            raise RuntimeError('Inicialização não pode conter operações de escrita.')
        pendente['pendente'] = r['acoes']
        _salvar(pasta, ARQ_ESTADO, pendente)
        _marcar_vistos(str(pasta), linhas, r['acoes'])
        if preparado:
            novo, esperadas, partes, acrescentadas = preparado
            r['backup_planilha'] = NP._guardar_backup(original, str(pasta / NP.PASTA_BACKUPS))
            fd, tmp = tempfile.mkstemp(prefix='~sync_planilha_', suffix='.tmp',
                                       dir=str(Path(planilha).resolve().parent))
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(novo)
                if antes_de_trocar:
                    antes_de_trocar()
                if NP.esta_aberta(planilha) or CP._assinatura(planilha) != assinatura:
                    raise NP.GravacaoRecusada('Planilha mudou ou foi aberta antes da troca.')
                if _assinatura(caminho_pedidos) != assinatura_portal:
                    raise ConflitoGravacao('Portal mudou antes da troca; recalcular.')
                NP._trocar(tmp, planilha)
                no_disco = Path(planilha).read_bytes()
                PE.conferir(original, no_disco, esperadas, partes, acrescentadas)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        if preparado:
            if Path(planilha).read_bytes() != preparado[0]:
                raise NP.GravacaoRecusada('Excel mudou após a troca; não atualizo o portal.')
        elif CP._assinatura(planilha) != assinatura:
            raise NP.GravacaoRecusada('Excel mudou antes de atualizar o portal.')
        _gravar_portal(caminho_pedidos, r['acoes'], str(pasta), dormir)
        for a in r['acoes']:
            if a.get('campo') == 'DATA DE ENTREGA' and a['destino'] == 'portal':
                for registro in proximo['itens'].values():
                    if a['chave'] in registro['chaves']:
                        registro['formato_data_portal'] = 'dmy'
        # A referência só avança após reler as duas pontas; operações não confirmadas ficam pendentes.
        with tempfile.TemporaryDirectory(prefix='sync_confirmar_') as temp:
            cp = Path(temp) / 'p.xlsx'
            cp.write_bytes(Path(planilha).read_bytes())
            finais = CP.ler_planilha_com_linhas(str(cp))
        manager.iniciar()
        apos, confirmado = planejar(finais, manager.pedidos['PEDIDOS'], proximo, ignorar, vistos)
        restantes = {a['chave'] for a in apos['acoes']} | {a['chave'] for a in apos['conflitos']}
        if any(a['chave'] in restantes for a in r['acoes']):
            raise ConflitoGravacao('Mudança não confirmada; foto anterior e operação pendente mantidas.')
        proximo = confirmado
        r['gravou'] = True
    proximo.pop('pendente', None)
    _salvar(pasta, ARQ_ESTADO, proximo)
    r['concluido_em'] = r['gerado_em']
    _salvar(pasta, ARQ_RELATORIO, r)
    if r['gravou']:
        r['conferencia'] = conferir(finais, manager.pedidos['PEDIDOS'], ignorar)
        _salvar(pasta, ARQ_RELATORIO, r)
    _salvar(pasta, 'conferencia_planilha.json', r['conferencia'])
    return r


def estado_para_tela(pasta):
    r = _ler(pasta, ARQ_RELATORIO)
    if not r:
        return None
    return dict({k: len(r.get(k, [])) for k in LISTAS}, gerado_em=r.get('gerado_em'),
                adiado=r.get('adiado'), aviso=r.get('aviso'), erro=r.get('erro'),
                primeira_vez=r.get('primeira_vez'), gravou=r.get('gravou'),
                listas={k: r.get(k, [])[:30] for k in LISTAS})


def main(argv=None):
    from dotenv import load_dotenv
    from cruzar_nf.sincronizar import DADOS_PADRAO, PEDIDOS_PADRAO
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--planilha', default=os.environ.get('CADASTRO_PLANILHA') or CP.PLANILHA_PADRAO)
    ap.add_argument('--pedidos', default=os.environ.get('SYNC_NF_PEDIDOS') or PEDIDOS_PADRAO)
    ap.add_argument('--dados', default=os.environ.get('SYNC_NF_DADOS') or DADOS_PADRAO)
    ap.add_argument('--gravar', action='store_true')
    ap.add_argument('--diario', action='store_true', help='dias úteis, 12:30–18:00, uma rodada concluída por dia')
    a = ap.parse_args(argv)
    try:
        r = sincronizar(a.planilha, a.pedidos, a.dados, a.gravar, diario=a.diario)
    except Exception as e:
        print('[ERRO] %s' % e)
        if a.gravar:
            Path(a.dados).mkdir(parents=True, exist_ok=True)
            if not isinstance(e, SincronizacaoEmAndamento):
                _salvar(a.dados, ARQ_RELATORIO, {'gerado_em': dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                                               'erro': str(e), 'adiado': True})
        return 1
    if not r.get('sem_mudanca'):
        resumo = {k: r.get(k) for k in ('gerado_em', 'primeira_vez', 'gravou', 'adiado', 'aviso')}
        resumo['contagens'] = {k: len(r.get(k, [])) for k in LISTAS}
        resumo['exemplos'] = {k: r.get(k, [])[:10] for k in LISTAS if r.get(k)}
        resumo['conferencia'] = {k: len(v) for k, v in r.get('conferencia', {}).items() if isinstance(v, list)}
        print(json.dumps(resumo, ensure_ascii=False, indent=1))
    return 1 if r.get('adiado') else 0


if __name__ == '__main__':
    raise SystemExit(main())
