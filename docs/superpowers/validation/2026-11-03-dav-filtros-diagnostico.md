# Validação DAV — 03/11/2026

Base: origin/main 509ced3; branch codex/dav-filtros-e-diagnostico.
Plano: ../plans/2026-11-03-dav-filtros-diagnostico.md.

## Resultado

- Barra compacta modelo 02 compartilhada por vendedor e ADM; menus GET,
  busca, filtros removíveis, teclado e categoria preservados.
- Cartão original de envio em largura total, sem o painel promocional lateral.
- Origem/local/correção/células confirmadas no erro e na conferência inválida.
- Falhas reconhecidas do robô/acesso indicam Enzo, Allan ou Lucas; omitem o
  botão que pediria alterar a planilha por uma falha da automação.
- Espera/duração reais, cópia de resumo com contexto e vínculos de correção.
- Resumo /adm/dav/erros com recorte completo e orientação por causa.
- Mensagens financeiras originais e detalhes técnicos continuam no ADM.

## Testes executados

| Verificação | Resultado |
|---|---|
| Base `python -m pytest tests -k dav -q` | 122 passaram |
| Diagnóstico e planilha após correção | 102 passaram |
| Painel e ADM após correção | 27 passaram |
| Tela, pulso e apresentação | 63 passaram |
| Integração DAV, diagnóstico, resumo, pulso e fila | 168 passaram |
| Primeira suíte completa `python -m pytest tests -q -n 4` | 2642 passaram, 2 ignorados, 146 avisos; 358,38 s |
| Segunda suíte completa após correções da revisão | 2655 passaram, 2 ignorados, 146 avisos; 301,25 s |
| Últimos ajustes de apresentação/ação e ADM | 20 passaram |

Os avisos são da extensão de validação de dados do openpyxl. Os testes novos
de comportamento foram observados falhando antes das respectivas correções.

## Revisão independente

`dav_plano_check` revisou o plano. `dav_revisao_integrada` encontrou dois P2:
agrupamento de conferências com células diferentes e interpretação de conteúdo
digitado como estrutura do erro. Ambos corrigidos com regressão RED→GREEN;
revisão dirigida posterior passou em 9 testes, sem achados pendentes.

Decisões: endereço divergente não atribui culpa; classifica como comparação de
planilha/cadastro. Formato desconhecido pede conferência/suporte. Não expor texto
livre adicional ao vendedor para tentar tornar o diagnóstico mais detalhado.

## Conferência visual local

Prévia usa banco SQLite próprio, cookies/contas fictícios, lifespan desativado e
middleware que recusa métodos diferentes de GET. Nenhuma geração HSE.

Conferidos no navegador: cartão de envio, barra de filtros, seleção por resultado,
chip de remoção, detalhe com quantidade do item 3/B4, contraste da busca no escuro,
painel ADM, resumo e acesso a seus envios. Conferidos temas claro/escuro e largura
de 390px em iframe para vendedor e resumo ADM (não aparelho físico).

Capturas locais na pasta de visualizações da conversa:
- dav-desenvolvido-vendedor-escuro.png
- dav-desenvolvido-orientacao.png
- dav-desenvolvido-adm-escuro.png
- dav-desenvolvido-resumo-erros.png
- dav-desenvolvido-resumo-claro.png
- dav-desenvolvido-celular.png

Não houve merge, instalação no servidor nem operação produtiva no HSE.

## Correção de dependência da CI — 04/11/2026

A execução 41722028673 no GitHub passou em 2650 testes, mas não conseguiu
carregar `tests/test_dav_apresentacao.py`: `ModuleNotFoundError: No module named
'bs4'`. O pacote estava instalado no PC, mas não constava em requirements.txt.
O usuário autorizou adicionar a dependência em 04/11: `beautifulsoup4>=4.15.0`.
Isso substitui a restrição inicial de não acrescentar dependências apenas
para esse parser de testes; não há biblioteca nova na interface do usuário.

Validação da correção: instalação isolada do BeautifulSoup 4.15.0, sem carregar
os pacotes globais, importação e leitura HTML confirmadas; os 5 testes de
apresentação passaram novamente. A aprovação do ambiente limpo será conferida
na nova execução do GitHub após o push.
