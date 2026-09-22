"""Um PDF de verdade, montado à mão, para os testes do ingestor.

Sem dependência nova: o formato é texto com um índice de bytes no fim. Uma
fonte padrão (Helvetica, WinAnsi), uma linha de texto por linha da proposta.
O que importa é que o pypdf LEIA de volta o que foi escrito — é o mesmo
caminho que um PDF da Della Volpe faz no ingestor."""

from __future__ import annotations


def _escapar(linha: str) -> bytes:
    bruto = linha.encode("cp1252", errors="replace")
    return (bruto.replace(b"\\", b"\\\\").replace(b"(", b"\\(")
            .replace(b")", b"\\)"))


def pdf_com_texto(texto: str) -> bytes:
    linhas = texto.splitlines() or [""]
    corpo = b"BT /F1 9 Tf 11 TL 40 800 Td\n"
    for linha in linhas:
        corpo += b"(" + _escapar(linha) + b") Tj T*\n"
    corpo += b"ET"
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
        b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(corpo) + corpo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
        b" /Encoding /WinAnsiEncoding >>",
    ]
    saida = b"%PDF-1.4\n"
    posicoes = []
    for i, obj in enumerate(objetos, start=1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for p in posicoes:
        saida += b"%010d 00000 n \n" % p
    saida += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objetos) + 1, xref))
    return saida
