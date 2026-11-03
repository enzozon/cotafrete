# DAV: filtros, erros e orientações

## Decisões aprovadas

O usuário aprovou o modelo 02 (barra compacta) para vendedor e ADM, o resumo
dos erros e o início do desenvolvimento após o planejamento. O envio conserva
o cartão original: três etapas, arquivo .xlsx até 5 MB, download do modelo e
Conferir planilha. Remover o painel de texto lateral e slogans. Não substituir
conferência, geração, observações, descrição por item ou PDF existentes.

## Filtros e apresentação

- Busca larga, período e resultado em controles personalizados; vendedor só no ADM.
- Preservar todos os estados, categoria, paginação e retorno aos filtros. Busca
  funciona com Enter; menus funcionam com teclado e sem JavaScript por links GET.
- Mostrar filtros ativos removíveis e Limpar filtros. Não memorizar filtros entre
  sessões: não foi solicitado. Sem novas dependências.
- Tema claro/escuro, celular, foco visível. Animações curtas de entrada/menu,
  hover e destaque de atualização real; respeitar prefers-reduced-motion.
- Histórico mantém motivo junto do resultado, PDF e vínculos de correção explícitos.
- Mostrar espera/duração calculadas de datas reais, sem percentual inventado.

## Orientação por origem

O vendedor deve distinguir preenchimento da planilha, cadastro HSE, acesso HSE,
falha reconhecida da automação, resultado sem confirmação e causa desconhecida.
Não atribuir culpa por mensagem ambígua: endereço não encontrado exige comparar
planilha e cadastro. Erro desconhecido não prova falha do robô.

O diagnóstico expõe adicionalmente `origem`, `origem_rotulo`, `onde_conferir`,
`como_corrigir` e `campos` (lista de referências de célula/campo confirmadas).
Esses campos são projeção segura para vendedor; texto técnico original permanece
restrito ao ADM. Manter compatibilidade de `categoria`, `orientacao` e demais
campos existentes. Erros da conferência também recebem orientação.

Mapear células a partir de campo/item conhecido (item n = linha n+1): quantidade
B, preço J, código K, NCM L, origem M, ICMS N, grupo P, descrição R; cliente B31,
prazo B32, vendedor B33, pagamento B34, filial B37, frete B38 e local B30.
Não inferir células fora do modelo ou causa sem evidência; considerar todas as
mensagens relevantes de validação. Avisos financeiros não entram na projeção.

Falha reconhecida da automação orienta procurar **Enzo, Allan ou Lucas**, levando
o número do envio. Resultado sem confirmação sempre orienta conferir no HSE
antes de reenviar, inclusive quando há evidência de salvamento num estado erro.
Copiar resumo inclui número/horários/etapa e somente dados permitidos ao perfil.

## Resumo no ADM

Adicionar `/adm/dav/erros`, com a mesma autorização administrativa. O painel
DAV dá acesso ao resumo. Agrupar ocorrências do recorte completo, antes da
paginação, com motivo, quantidade, origem, onde conferir, como corrigir e links
para envios. Falhas, rejeições/conferências inválidas, resultados sem confirmação
e criados com aviso são grupos distintos. Não misturar DAVs com cotações de frete.
Resumo preserva período, vendedor e busca; detalhes técnicos são escapados.
Cada envio conta uma vez no grupo. Não deduzir vínculo de correção por arquivo.

## Limites

Sem geração/reenvio automáticos, alterações em permissões, nova IA, atribuição de
responsáveis, comentários internos, envio de mensagens ou acesso produtivo ao
HSE. Não instalar no servidor nem fazer merge. Basear em origin/main atual.

## Aceite

Testes de diagnóstico, agrupamento completo, autorização e isolamento entre
vendedores, HTML escapado, filtros e pulso; regressão da fila e planilha. Verificar
visualmente claro/escuro e celular com dados sintéticos sem executar HSE.
