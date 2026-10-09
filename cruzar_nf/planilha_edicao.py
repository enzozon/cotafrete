"""Edição cirúrgica de pedidos; não salva o workbook pelo openpyxl."""
from __future__ import annotations

import datetime as dt
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.utils.datetime import to_excel

from cruzar_nf import nf_planilha as NP
from cruzar_nf.cadastro_pedidos import _campo
from cruzar_nf.planilha_portal import normalizar


def ler(original):
    w = openpyxl.load_workbook(io.BytesIO(original), read_only=True, data_only=False)
    try:
        s = w[NP._titulo_aba(w)]
        cab = next(s.iter_rows(max_row=1, values_only=True))
        nomes = [str(c).strip().upper() for c in cab if c is not None]
        if len(nomes) != len(set(nomes)):
            raise NP.GravacaoRecusada('Cabeçalhos duplicados na planilha.')
        colunas = {str(c).strip().upper(): get_column_letter(i) for i, c in enumerate(cab, 1) if c}
        formulas = {c.coordinate for row in s.iter_rows(max_col=max(
            (openpyxl.utils.column_index_from_string(c) for c in colunas.values()), default=1))
            for c in row if c.data_type == 'f'}
        with zipfile.ZipFile(io.BytesIO(original)) as z:
            raiz = ET.fromstring(z.read(NP.parte_da_aba(original, 'PEDIDOS')))
            for mescla in raiz.findall('{%s}mergeCells/{%s}mergeCell' % (NP.NS_MAIN, NP.NS_MAIN)):
                for row in openpyxl.utils.rows_from_range(mescla.get('ref')):
                    formulas.update(row)
        return colunas, formulas, w.epoch
    finally:
        w.close()


def celula(ref, valor, estilo, nome, epoch):
    s = ' s="%s"' % estilo if estilo is not None else ''
    if valor is None or str(valor).strip() == '':
        return '<c r="%s"%s/>' % (ref, s)
    if nome == 'DATA DE ENTREGA':
        valor = to_excel(dt.datetime.strptime(normalizar(nome, valor), '%Y-%m-%d'), epoch)
        if estilo is None:
            raise NP.GravacaoRecusada('Coluna de data sem estilo; confira a planilha.')
    elif nome == 'VALOR':
        valor = Decimal(normalizar(nome, valor))
    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, s, valor)
    texto = str(valor)
    if any(ord(c) < 32 and c not in '\t\n\r' for c in texto):
        raise NP.GravacaoRecusada('Texto contém caracteres inválidos para Excel.')
    return '<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, s, escape(texto))


def _estilos(linha):
    return {NP.REF_RE.search(c).group(1): (NP.ESTILO_RE.search(c).group(1)
            if NP.ESTILO_RE.search(c) else None) for c in NP.CELL_RE.findall(linha)}


def _estender(ref, ultima):
    partes = []
    for faixa in ref.split():
        a, b, c, d = range_boundaries(faixa)
        if d is not None and d >= 2 and b <= 2 and d < ultima:
            faixa = '%s%s:%s%s' % (get_column_letter(a), b, get_column_letter(c), ultima)
        partes.append(faixa)
    return ' '.join(partes)


def _intervalos(xml, ultima):
    def tag(m):
        return re.sub(r'\b(ref|sqref)="([^"]+)"',
                      lambda x: '%s="%s"' % (x.group(1), _estender(x.group(2), ultima)), m.group(0))
    return re.sub(r'<(?:autoFilter|conditionalFormatting|dataValidation)\b[^>]*>', tag, xml)


def _remover_links(xml, refs):
    # O texto do e-mail mudou: retirar só seu link antigo evita abrir o destinatário errado.
    def remover(m):
        ref = re.search(r'\bref="([^"]+)"', m.group(0))
        return '' if ref and ref.group(1) in refs else m.group(0)
    return re.sub(r'<hyperlink\b[^>]*/>', remover, xml)


def preparar(original, mudancas, novas):
    """mudanças: linha -> campos; novas: pedidos. Retorna bytes e células autorizadas."""
    colunas, formulas, epoch = ler(original)
    parte = NP.parte_da_aba(original, 'PEDIDOS')
    with zipfile.ZipFile(io.BytesIO(original)) as z:
        xml0 = z.read(parte).decode('utf-8')
        linhas = {int(m.group(1)): m.group(0) for m in NP.ROW_RE.finditer(xml0)}
        if not linhas or '</sheetData>' not in xml0:
            raise NP.GravacaoRecusada('Estrutura de linhas não reconhecida.')
        xml = xml0
        esperadas = {}
        for numero, campos in mudancas.items():
            estilos = _estilos(linhas[numero])
            for nome, valor in campos.items():
                if nome not in colunas:
                    raise NP.GravacaoRecusada('Coluna ausente: %s' % nome)
                col = colunas[nome]
                ref = '%s%s' % (col, numero)
                if ref in formulas:
                    raise NP.GravacaoRecusada('Não substituo fórmula em %s.' % ref)
                xml = NP.editar_aba(xml, {numero: ''}, coluna=col, coluna_estilo=col)
                nova = celula(ref, valor, estilos.get(col), nome, epoch)
                xml = NP.CELL_RE.sub(lambda m: nova if NP.REF_RE.search(m.group(0)).group(0)
                                    == 'r="%s"' % ref else m.group(0), xml)
                esperadas[ref] = (nome, valor)
        partes = {}
        novas_linhas = []
        if novas:
            # A última linha com PEDIDO fornece o estilo; linhas só formatadas ficam intactas.
            w = openpyxl.load_workbook(io.BytesIO(original), read_only=True, data_only=False)
            try:
                s = w[NP._titulo_aba(w)]
                modelo = max((c.row for row in s.iter_rows(min_col=openpyxl.utils.column_index_from_string(colunas['PEDIDO']),
                              max_col=openpyxl.utils.column_index_from_string(colunas['PEDIDO']), min_row=2)
                              for c in row if c.value is not None), default=2)
            finally:
                w.close()
            if modelo not in linhas:
                raise NP.GravacaoRecusada('Não achei uma linha modelo para acrescentar pedidos.')
            if any(re.search(r'<f\b', c) for c in NP.CELL_RE.findall(linhas[modelo])):
                raise NP.GravacaoRecusada('Linha modelo tem fórmula; inserção exige revisão.')
            estilos = _estilos(linhas[modelo])
            ultima = max(linhas)
            for pedido in novas:
                ultima += 1
                corpo = []
                for nome, col in colunas.items():
                    if nome == 'NF (MAESTRO)' or 'NOTA FISCAL' in nome:
                        continue
                    valor = _campo(pedido, nome)
                    ref = '%s%s' % (col, ultima)
                    corpo.append(celula(ref, valor, estilos.get(col), nome, epoch))
                    esperadas[ref] = (nome, valor)
                abertura = linhas[modelo].split('>', 1)[0] + '>'
                abertura = re.sub(r'\br="\d+"', 'r="%s"' % ultima, abertura)
                abertura = re.sub(r'\s+(?:spans|hidden)="[^"]*"', '', abertura)
                novas_linhas.append(abertura + ''.join(corpo) + '</row>')
            xml = xml.replace('</sheetData>', ''.join(novas_linhas) + '</sheetData>', 1)
            def dimension(m):
                a, b, c, d = range_boundaries(m.group(1))
                return '<dimension ref="%s%s:%s%s"' % (get_column_letter(a), b, get_column_letter(c), max(d, ultima))
            xml = re.sub(r'<dimension ref="([^"]+)"', dimension, xml, count=1)
            xml = _intervalos(xml, ultima)
            raiz = ET.fromstring(xml0)
            ns = {'m': NP.NS_MAIN}
            for mescla in raiz.findall('m:mergeCells/m:mergeCell', ns):
                if range_boundaries(mescla.get('ref'))[3] >= min(int(NP.REF_RE.search(r).group(2)) for r in novas_linhas):
                    raise NP.GravacaoRecusada('Mesclagem alcança as linhas novas.')
            relpath = parte.rsplit('/', 1)[0] + '/_rels/' + parte.rsplit('/', 1)[1] + '.rels'
            if relpath in z.namelist():
                import posixpath
                for rel in ET.fromstring(z.read(relpath)):
                    if not rel.get('Type', '').endswith('/table'):
                        continue
                    alvo = rel.get('Target')
                    nome = alvo.lstrip('/') if alvo.startswith('/') else posixpath.normpath(posixpath.join(parte.rsplit('/', 1)[0], alvo))
                    texto = z.read(nome).decode('utf-8')
                    if ET.fromstring(texto).get('totalsRowCount', '0') != '0':
                        raise NP.GravacaoRecusada('Tabela com total exige revisão antes de inserir.')
                    novo = re.sub(r'(<(?:table|autoFilter)\b[^>]*?\bref=")([^"]+)(")',
                                  lambda m: m.group(1) + _estender(m.group(2), ultima) + m.group(3), texto)
                    if novo != texto:
                        partes[nome] = novo.encode('utf-8')
        xml = _remover_links(xml, esperadas)
        partes[parte] = xml.encode('utf-8')
        novo = NP._reempacotar(original, partes)
    conferir(original, novo, esperadas, partes, len(novas_linhas))
    return novo, esperadas, partes, len(novas_linhas)


def conferir(antes, depois, esperadas, partes, acrescentadas):
    """XML das células antigas não autorizadas e partes externas devem ser idênticos."""
    parte = NP.parte_da_aba(antes, 'PEDIDOS')
    with zipfile.ZipFile(io.BytesIO(antes)) as a, zipfile.ZipFile(io.BytesIO(depois)) as d:
        if a.namelist() != d.namelist():
            raise NP.GravacaoRecusada('Partes do XLSX mudaram.')
        for nome in a.namelist():
            if nome not in partes and a.read(nome) != d.read(nome):
                raise NP.GravacaoRecusada('Parte não autorizada mudou: %s' % nome)
            if nome in partes and d.read(nome) != partes[nome]:
                raise NP.GravacaoRecusada('Parte diferente do plano: %s' % nome)
        x, y = a.read(parte).decode('utf-8'), d.read(parte).decode('utf-8')
        ca = {NP.REF_RE.search(c).group(0): c for c in NP.CELL_RE.findall(x)}
        cd = {NP.REF_RE.search(c).group(0): c for c in NP.CELL_RE.findall(y)}
        for ref, c in ca.items():
            if ref[3:-1] not in esperadas and cd.get(ref) != c:
                raise NP.GravacaoRecusada('Célula não autorizada mudou: %s' % ref)
        ra = {int(m.group(1)): m.group(0) for m in NP.ROW_RE.finditer(x)}
        rd = {int(m.group(1)): m.group(0) for m in NP.ROW_RE.finditer(y)}
        def limpar(linha):
            return NP.CELL_RE.sub(lambda m: '' if NP.REF_RE.search(m.group(0)).group(0)[3:-1]
                                  in esperadas else m.group(0), linha)
        if len(rd) != len(ra) + acrescentadas:
            raise NP.GravacaoRecusada('Número de linhas diferente do plano.')
        for n, linha in ra.items():
            if n not in rd or limpar(linha) != limpar(rd[n]):
                raise NP.GravacaoRecusada('Estrutura da linha antiga mudou: %s' % n)
        # Compara também os blocos fora das linhas, exceto referências ampliadas.
        rx, ry = _remover_links(NP.ROW_RE.sub('', x), esperadas), NP.ROW_RE.sub('', y)
        if acrescentadas:
            rx = _intervalos(rx, max(int(NP.REF_RE.search(c).group(2)) for c in cd))
            rx = re.sub(r'<dimension\b[^>]*/>', '', rx)
            ry = re.sub(r'<dimension\b[^>]*/>', '', ry)
        if rx != ry:
            raise NP.GravacaoRecusada('Metadados não autorizados mudaram.')
    w = openpyxl.load_workbook(io.BytesIO(depois), read_only=True, data_only=False)
    try:
        s = w[NP._titulo_aba(w)]
        encontradas = set()
        for row in s.iter_rows():
            for c in row:
                ref = getattr(c, 'coordinate', None)
                if ref not in esperadas:
                    continue
                nome, valor = esperadas[ref]
                if normalizar(nome, c.value) != normalizar(nome, valor):
                    raise NP.GravacaoRecusada('Célula diferente do esperado: %s' % ref)
                encontradas.add(ref)
        if encontradas != set(esperadas):
            raise NP.GravacaoRecusada('Células previstas ausentes na conferência.')
    finally:
        w.close()
