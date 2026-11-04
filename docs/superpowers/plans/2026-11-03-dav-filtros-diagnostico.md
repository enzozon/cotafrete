# DAV Filters and Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Entregar as telas DAV aprovadas e orientação útil ao vendedor sobre a origem dos erros.

**Architecture:** Reusar HTML de servidor FastAPI, CSS_DAV e consultas existentes.
Estender o diagnóstico puro com dados seguros e agrupar ocorrências na consulta;
as rotas apenas autorizam e apresentam. Nenhuma mudança na geração do HSE.

**Tech Stack:** Python, FastAPI, SQLite, HTML/CSS e JavaScript sem dependências novas.

**Spec:** docs/superpowers/specs/2026-11-03-dav-filtros-diagnostico-design.md

## Global Constraints

- Texto técnico original permanece restrito ao ADM; escapar toda saída variável.
- Resultado sem confirmação sempre orienta conferir no HSE antes de reenviar.
- Sem geração/reenvio automáticos, novas dependências ou acesso produtivo ao HSE.
- Não substituir conferência, geração, observações, descrição por item ou PDF existentes.
- Respeitar prefers-reduced-motion, teclado e celular.
- Não instalar no servidor nem fazer merge.

## Review Focus

- Erro legado com número/evidência de salvamento: tratar como incerto, nunca recomendar reenvio direto (T1/T3).
- Mensagem desconhecida ou financeira: não inferir culpa nem vazar dados ao vendedor (T1/T3).
- Mais de 25 envios e conferência inválida em rascunho: resumo completo sem contagem duplicada (T2).
- Filtros/categoria com caracteres HTML e sessão expirada: preservar recorte e autorização (T2/T3).
- Datas ausentes, antigas ou com fuso: não exibir duração negativa nem progresso fictício (T3).

## T1 — Origem e localização do erro

**Files:** orcamento/diagnostico.py; tests/test_dav_diagnostico.py (adicionar testes).
**Consumes:** registro DAV e relatório/conferência existentes.
**Produces:** diagnostico(dav: dict, *, administrador: bool) -> dict, com os campos
existentes e origem/origem_rotulo/onde_conferir/como_corrigir/campos conforme spec.

- [x] Adicionar testes: quantidade Item 3 → B4; cliente → B31; endereço ambíguo → desconhecida/B30, rótulo Conferir planilha e cadastro HSE; automação conhecida → contato; mensagem desconhecida → desconhecida; incerto domina orientação; nenhum financeiro em novos campos; conferência inválida com erro de item.
- [x] Rodar `python -m pytest tests/test_dav_diagnostico.py -q` e confirmar novas falhas.
- [x] Implementar classificação conservadora e projeção segura, sem alterar o robô nem assumir que rejeição de arquivo é bug da automação.
- [x] Rodar testes de diagnóstico e planilha; registrar resultado e commit dos arquivos próprios.

## T2 — Resumo administrativo dos erros

**Files:** core/painel_dav.py; web/adm_dav.py; tests/test_dav_painel.py; tests/test_adm_dav.py.
**Consumes:** diagnóstico T1; filtros_dav(dados, filtros, administrador=True, base=...) de T3.
**Produces:** consultar retorna `ocorrencias` (grupos com tipo, categoria, titulo,
origem_rotulo, onde_conferir, como_corrigir, total, envios); rota GET /adm/dav/erros;
componente resumo_erros(dados, filtros) de acesso no painel. Grupo usa todos os
registros filtrados, antes da paginação; cada envio só uma vez. Preservar grupos existentes.

- [x] Escrever testes de 30 ocorrências, financeiro pronto separado, erro com salvamento classificado incerto, rascunho inválido, autorização e escape HTML.
- [x] Confirmar falhas com `python -m pytest tests/test_dav_painel.py tests/test_adm_dav.py -q`.
- [x] Implementar agregação, tela com diagnóstico/orientações e links por envio, preservando período/vendedor/busca e autenticação.
- [x] Encurtar textos do painel e adicionar acesso ao resumo. Não editar web/dav_ui.py nem web/layout.py.
- [x] Reexecutar os testes e fazer commit dos arquivos próprios.

## T3 — Modelo 02, vendedor, detalhes e movimento

**Files:** web/dav_ui.py; web/layout.py; tests/test_dav_tela.py; tests/test_dav_atualizacao.py.
**Consumes:** T1 e rotas existentes; `ocorrencias`/resumo T2.
**Produces:** filtros_dav(dados: dict, filtros: dict, *, administrador: bool=False,
base: str | None=None) -> str; barra compacta com menus de links GET; detalhes
com origem/local/correção e resumo copiável seguro; tempo calculado de datas reais.

- [x] Testar remoção individual/limpeza de filtros, busca/categoria escapadas, vendedor restrito, bloco de envio sem aside, novos campos seguros nos detalhes/cópia e datas inválidas/futuras.
- [x] Executar os testes novos e confirmar falhas antes de implementar.
- [x] Manter cartão de envio, remover painel promocional e slogans, aplicar barra modelo 02 com menus nativos details/summary e links GET, chips e busca com Enter.
- [x] Integrar diagnóstico e tempo nos detalhes/histórico; destacar vínculos de correção existentes; melhorar cópia sem duplicar dados secretos.
- [x] Aplicar CSS de claro/escuro/celular, animações breves e reduced motion; pulso mantém foco e detalhes abertos.
- [x] Rodar `python -m pytest tests -k dav -q` e regressão `tests/orcamento/test_fila.py`; commit dos arquivos próprios.

## T4 — Integração, revisão e entrega

**Files:** docs/MAPA_DO_SISTEMA.md; docs/superpowers/validation/2026-11-03-dav-filtros-diagnostico.md.
**Consumes:** T1–T3 integradas. **Produces:** revisão independente, resultados e capturas.

- [x] Atualizar mapa da área DAV e registrar decisões/desvios no ledger.
- [x] Revisão independente dos diagnósticos/permissões/rotas e aderência ao modelo.
- [x] Executar suíte apropriada e suíte completa em segundo plano; investigar falhas introduzidas.
- [x] Prévia local sintética, sem POSTs/HSE; conferir ADM/vendedor/resumo/detalhe, temas e viewport celular.
- [x] Registrar comandos/resultados/capturas, fazer commit e entregar branch/PR para revisão sem merge/deploy.

## Execução autorizada

O usuário pediu explicitamente desenvolvimento após este planejamento. Prosseguir
na mesma sessão sem nova aprovação intermediária; subagentes para partes isoladas
e revisão, conforme autorização anterior. Base inicial: origin/main 509ced3.


