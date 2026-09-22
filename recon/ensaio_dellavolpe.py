"""Ensaio da Della Volpe contra o site REAL, sem enviar nada. DRY-RUN.

    python recon/ensaio_dellavolpe.py            # janela fora da tela
    python recon/ensaio_dellavolpe.py --mostrar  # janela visível

Preenche o formulário público com uma carga de exemplo, carimbada como
"(cot. 999999)", e PARA antes de "Pedir orçamento". Nada chega à Della
Volpe. Serve para conferir, antes de ligar a automática no .env:

1. se o campo "Nome completo" aceita o carimbo sem apagar nada;
2. se o e-mail de resposta que vai no formulário é o do suporte;
3. se a caixinha "confirme que é humano" apareceu (status
   intervencao_necessaria) ou não (status rascunho).

O print do formulário preenchido sai em teste_real/dellavolpe-ensaio/.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(override=False)

from carriers.dellavolpe import caixa  # noqa: E402
from carriers.dellavolpe.adapter import DellavolpeAdapter  # noqa: E402
from core.models import (CotacaoRequest, Local, Mercadoria,  # noqa: E402
                         NotaFiscal, Parte, Servico, Solicitante, TipoFrete,
                         Volume)

# CNPJs da própria Ventura e de um cliente de exemplo dos testes — o ensaio
# não envia, então não há cotação de ninguém sendo pedida.
CARGA = CotacaoRequest(
    solicitante=Solicitante(nome="Ensaio Cotafrete", email="ensaio@ventura.com.br",
                            whatsapp="27999887766"),
    servico=Servico.FRACIONADO_LTL,
    origem=Local(uf="ES", cidade="Vila Velha"),
    destino=Local(uf="SP", cidade="São Paulo"),
    remetente=Parte(cnpj="08310365000124"),
    destinatario=Parte(cnpj="60042686000105"),
    tipo_frete=TipoFrete.CIF,
    volumes=[Volume(qtd=1, comprimento_cm=Decimal(40), largura_cm=Decimal(40),
                    altura_cm=Decimal(40), peso_kg=Decimal(5))],
    mercadoria=Mercadoria(tipo_material="Diversos"),
    nota_fiscal=NotaFiscal(valor_total=Decimal(1500)),
)


def main() -> int:
    mostrar = "--mostrar" in sys.argv
    resposta = caixa.email_de_resposta()
    print(f"E-mail que iria no formulário: "
          f"{resposta or 'o do vendedor (caixa do suporte não configurada)'}")
    # headless=False: o envio real usa janela de verdade, e o ensaio precisa
    # ver o site como o envio veria — inclusive a caixinha.
    adapter = DellavolpeAdapter(headless=False, mostrar_janela=mostrar,
                                workdir=str(RAIZ / "teste_real"
                                            / "dellavolpe-ensaio"))
    res = adapter.cotar(CARGA, confirmar_envio=False, cotacao_id=999999,
                        email_resposta=resposta)
    print(f"status:     {res.status.value}")
    print(f"erro:       {res.erro or '—'}")
    print(f"evidências: {', '.join(res.evidencias) or '—'}")
    if res.status.value == "intervencao_necessaria":
        print("\nA caixinha APARECEU. Com a automática ligada, esta cotação "
              "cairia no cartão Semiautomática.")
    elif res.erro:
        print("\nO site apagou algum campo — veja o erro acima e o print.")
    else:
        print("\nSem caixinha e sem campo recusado. Abra o print e confira o "
              "nome com '(cot. 999999)'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
