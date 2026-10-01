# Como ligar o cruzamento de NF no portal Maestro

Plano para levar o `cruzar_nf` para a tela da planilha
(`public/planilha_vale.html`) do [portaismaestro](https://github.com/allan-max/portaismaestro).
Por enquanto o programa roda à mão (`CruzarNF.bat`); este é o caminho para o
botão no portal e, depois, para o fluxo automático.

## Como o portal funciona hoje

A planilha não fica no Node. O `server.js` é só um repassador de eventos
Socket.IO entre a tela e o **robô Python** (o socket que se registra com
`sou_o_robo`, guardado em `bot_socket_id`). Quem lê e grava a planilha é o robô:

```
tela (planilha_vale.html)          server.js                     robô Python
  solicitar_planilha_json   ──►  comando_carregar_planilha_json ──►  lê a planilha
  retorno_planilha_json     ◄──  retorno_planilha_json          ◄──  { pedidos: [...] }
```

Os pedidos que a tela recebe já têm os campos do `PEDIDOS.json`
(`"PEDIDO"`, `"VALOR "`, `"REQUISITANTE "`...). Então o cruzamento entra
**no robô**, do mesmo jeito que os outros comandos, e o `cruzar_nf` foi
escrito só com biblioteca padrão para o robô poder importar sem instalar nada.

O código do robô não está no repositório do portal; os trechos da parte 3
abaixo seguem o padrão dos eventos que o `server.js` já usa e precisam ser
encaixados no cliente Socket.IO do robô.

## Fluxo com o botão

```
1. Pedidos > menu ☰ > "Cruzar NF com o ERP" > escolhe o comparar.json
2. tela   ── solicitar_cruzamento_nf { comparar: [...] } ──► server.js
3. server ── comando_cruzar_nf { comparar, clientId }      ──► robô
4. robô: pedidos da planilha + comparar -> cruzar() -> PEDIDOS_ATUALIZADO.json
5. robô   ── retorno_cruzamento_nf { sucesso, relatorio, clientId } ──► server ──► tela
6. tela mostra o relatório; a coluna NF aparece na tabela de Pedidos
```

O `comparar.json` vai pelo próprio socket: o `server.js` já sobe o Socket.IO
com `maxHttpBufferSize: 1e8` (100 MB), folga para qualquer exportação do ERP.

## 1. `server.js` — repassar os dois eventos

Ao lado de `solicitar_planilha_json` (mesmo padrão):

```js
    // CRUZAMENTO DE NF: tela -> robô -> tela
    socket.on('solicitar_cruzamento_nf', (dados = {}) => {
        if (!Array.isArray(dados.comparar)) {
            return socket.emit('retorno_cruzamento_nf', { sucesso: false, erro: "Arquivo do ERP inválido." });
        }
        if (bot_socket_id) {
            dados.clientId = socket.id;
            io.to(bot_socket_id).emit('comando_cruzar_nf', dados);
        } else {
            socket.emit('retorno_cruzamento_nf', { sucesso: false, erro: "O Robô está offline." });
        }
    });

    socket.on('retorno_cruzamento_nf', (dados) => {
        if (dados.clientId) io.to(dados.clientId).emit('retorno_cruzamento_nf', dados);
        if (dados.sucesso && dados.planilha_alterada) io.emit('planilha_atualizada');
    });
```

## 2. `public/planilha_vale.html` — botão, relatório e coluna NF

**Item no menu ☰** (dentro de `#dropdown-menu`, antes do "ATUALIZAR DADOS"),
com o seletor de arquivo escondido:

```html
<a href="#" onclick="document.getElementById('input-comparar-nf').click(); return false;"
   style="padding: 12px 15px; color: var(--text-main); text-decoration: none; border-top: 1px solid var(--border-color); display: flex; align-items: center; gap: 10px;">
   <i class="fa-solid fa-file-invoice" style="width: 20px; text-align: center;"></i> Cruzar NF com o ERP</a>
<input type="file" id="input-comparar-nf" accept=".json,application/json" style="display:none" onchange="enviarCruzamentoNF(this)">
```

**Modal do relatório** (junto dos outros modais, reaproveitando o estilo do `modal-detalhes`):

```html
<div id="modal-cruzamento-nf" style="position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: none; align-items: center; justify-content: center; z-index: 9999999;">
    <div style="background: #2d333b; border: 1px solid #444c56; border-radius: 12px; padding: 25px; width: min(1000px, 94vw); max-height: 88vh; overflow: auto; position: relative;">
        <button onclick="document.getElementById('modal-cruzamento-nf').style.display='none'" style="position: absolute; top: 15px; right: 15px; background: none; border: none; color: #768390; font-size: 1.5rem; cursor: pointer;">&times;</button>
        <h2 style="margin-top: 0; color: #cdd9e5; border-bottom: 1px solid #444c56; padding-bottom: 10px;">Cruzamento de NF</h2>
        <div id="modal-cruzamento-nf-corpo" style="color: #adbac7;"></div>
    </div>
</div>
```

**JavaScript** (no `<script>` que já tem o `socket`):

```js
function enviarCruzamentoNF(input) {
    const arquivo = input.files[0];
    input.value = '';                 // deixa escolher o mesmo arquivo de novo
    if (!arquivo) return;
    const leitor = new FileReader();
    leitor.onload = () => {
        let comparar;
        try {
            comparar = JSON.parse(String(leitor.result).replace(/^﻿/, ''));
            if (!Array.isArray(comparar)) comparar = Object.values(comparar).find(Array.isArray);
            if (!Array.isArray(comparar)) throw new Error();
        } catch (e) {
            return alert('O arquivo não é um JSON com a lista de vendas do ERP.');
        }
        document.getElementById('modal-cruzamento-nf-corpo').innerHTML =
            '<p><i class="fa-solid fa-spinner fa-spin"></i> Cruzando ' + comparar.length + ' linhas do ERP...</p>';
        document.getElementById('modal-cruzamento-nf').style.display = 'flex';
        socket.emit('solicitar_cruzamento_nf', { comparar });
    };
    leitor.readAsText(arquivo, 'utf-8');
}

function escHtml(v) {
    return String(v ?? '-').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function tabelaNF(titulo, itens, colunas) {
    if (!itens || !itens.length) return '';
    const cab = colunas.map(c => `<th style="text-align:left; padding:6px; border-bottom:1px solid #444c56;">${c[0]}</th>`).join('');
    const linhas = itens.map(i => '<tr>' + colunas.map(c =>
        `<td style="padding:6px; border-bottom:1px solid #373e47;">${escHtml(c[1](i))}</td>`).join('') + '</tr>').join('');
    return `<h3 style="color:#cdd9e5; margin:20px 0 8px;">${titulo} (${itens.length})</h3>
            <table style="width:100%; border-collapse:collapse; font-size:0.85rem;"><thead><tr>${cab}</tr></thead><tbody>${linhas}</tbody></table>`;
}

socket.on('retorno_cruzamento_nf', (res) => {
    const corpo = document.getElementById('modal-cruzamento-nf-corpo');
    if (!res.sucesso) {
        corpo.innerHTML = `<p style="color:#e5534b;">Erro: ${escHtml(res.erro)}</p>`;
        return;
    }
    const rel = res.relatorio, r = rel.resumo;
    const cartao = (rotulo, n, cor) => `<div style="background:#373e47; border-radius:8px; padding:12px; border-left:4px solid ${cor};">
        <div style="font-size:1.6rem; font-weight:bold; color:#cdd9e5;">${n}</div><div style="font-size:0.8rem;">${rotulo}</div></div>`;
    const oc = p => p.oc || p.pedido, nfs = p => (p.nfs || []).join(' / ');
    corpo.innerHTML = `
        <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px;">
            ${cartao('Bateram (1 NF)', r.bateram_1_nf, '#57ab5a')}
            ${cartao('Mais de uma NF', r.mais_de_uma_nf, '#c69026')}
            ${cartao('No ERP sem NF', r.no_erp_sem_nf, '#c69026')}
            ${cartao('Planilha, não no ERP', r.nao_encontrados_no_erp, '#e5534b')}
            ${cartao('ERP, não na planilha', r.so_no_erp, '#e5534b')}
            ${cartao('Divergência de valor', r.divergencia_de_valor, '#e5534b')}
            ${cartao('Com NF', r.percentual_com_nf + '%', '#539bf5')}
        </div>
        ${tabelaNF('Mais de uma NF', rel.mais_de_uma_nf, [['Pedido', oc], ['NFs', nfs], ['Requisitante', p => p.requisitante], ['Cidade', p => p.cidade]])}
        ${tabelaNF('No ERP, mas sem NF', rel.sem_nf, [['Pedido', oc], ['Requisitante', p => p.requisitante], ['Produto', p => p.produto]])}
        ${tabelaNF('Na planilha, não no ERP', rel.nao_encontrados, [['Pedido', oc], ['Requisitante', p => p.requisitante], ['Produto', p => p.produto]])}
        ${tabelaNF('No ERP, não na planilha', rel.so_no_erp, [['OC', o => o.oc], ['NFs', nfs], ['Emissão', o => o.emissao], ['Cliente', o => o.cliente]])}
        ${tabelaNF('Divergência de valor', rel.divergencia_valor, [['Pedido', oc], ['NF', p => p.nf_gravada], ['Planilha', p => p.valor_planilha], ['ERP', p => p.valor_erp], ['Diferença', p => p.diferenca_valor]])}
        ${tabelaNF('Mesma NF para várias OCs', rel.nf_varias_ocs, [['NF', n => n.nf], ['OCs', n => n.ocs.join(', ')]])}
        ${tabelaNF('Pedido repetido na planilha', rel.pedidos_duplicados, [['OC', d => d.oc], ['Vezes', d => d.vezes]])}
        ${tabelaNF('NF trocada', rel.nf_alterada, [['Pedido', oc], ['Antes', p => p.nf_anterior], ['Agora', p => p.nf_gravada]])}
        ${tabelaNF('Bateram', rel.bateram, [['Pedido', oc], ['NF', p => p.nf_gravada], ['Requisitante', p => p.requisitante], ['Cidade', p => p.cidade]])}`;
});
```

**Coluna NF na tabela de Pedidos.** No `<thead>` de `#view-pedi`, entre
"Cidade" e "Ações":

```html
<th style="width: 10%;"><i class="fa-solid fa-file-invoice" style="margin-right:8px;"></i>NF</th>
```

e em `renderPediRow`, na mesma posição:

```js
<td><div class="cell-content"><div class="cell-main-text">${p['NF'] || '-'}</div></div></td>
```

Depois disso, trocar o `colspan="6"` das mensagens de "Carregando..." e
"Nenhum registro" de `#tbody-bd-pedi` para `colspan="7"`, e ajustar as
larguras (hoje somam 100%). O modal de detalhes do pedido não precisa de
mudança: ele já mostra todos os campos do registro, então a `NF` aparece lá
sozinha.

## 3. Robô Python — o comando `comando_cruzar_nf`

Copiar a pasta `cruzar_nf/` para junto do robô (ou pôr este repositório no
`PYTHONPATH`). No cliente Socket.IO do robô, ao lado do handler de
`comando_carregar_planilha_json`:

```python
from cruzar_nf import cruzar
from cruzar_nf.cruzar import gravar_json

@sio.on('comando_cruzar_nf')
def comando_cruzar_nf(dados):
    resposta = {'clientId': dados.get('clientId')}
    try:
        pedidos = carregar_pedidos()   # a MESMA função que serve o comando_carregar_planilha_json
        atualizados, relatorio = cruzar(pedidos, dados['comparar'])
        gravar_json(PASTA / 'PEDIDOS_ATUALIZADO.json', atualizados)
        gravar_json(PASTA / 'RELATORIO_NF.json', relatorio)
        resposta.update(sucesso=True, relatorio=relatorio, planilha_alterada=False)
    except Exception as e:
        resposta.update(sucesso=False, erro=str(e))
    sio.emit('retorno_cruzamento_nf', resposta)
```

`planilha_alterada=False` nesta fase: o robô grava o
`PEDIDOS_ATUALIZADO.json` e **não mexe** na planilha de verdade, igual ao
programa manual. Para a coluna NF aparecer na tela, o passo seguinte é o robô
escrever a NF na planilha (a coluna `NF` da aba de pedidos) com os
`atualizados` e responder `planilha_alterada=True`; o `server.js` então
dispara `planilha_atualizada` e todas as telas abertas recarregam.

## 4. Depois: fluxo automático

Com o comando acima no robô, automatizar é só trocar quem dispara e de onde
vem o `comparar.json`:

1. **Origem do comparar.json.** Hoje é exportação manual do ERP. Para
   automatizar, o robô precisa buscar isso sozinho (exportação agendada do
   ERP numa pasta, ou consulta direta) — é a parte que depende do ERP e que
   precisa ser vista com quem o administra.
2. **Quando rodar.** O portal já tem `node-cron` nas dependências. Um
   `cron.schedule('0 7,13,18 * * 1-5', ...)` no `server.js` que emite
   `comando_cruzar_nf` para o robô (sem `clientId`), ou o próprio robô agendar.
3. **Aviso.** Com `clientId` vazio, o robô emite o resultado para todas as
   telas (`io.to('frontend')`), e o portal pode mostrar um selo na aba
   Pedidos quando houver OC sem NF, NF duplicada ou divergência de valor. O
   `nodemailer` que o portal já usa serve para mandar o `RELATORIO_NF.md` por e-mail.
4. **Cuidado ao gravar na planilha automaticamente.** A regra de "NF trocada"
   (o ERP diz uma NF diferente da que está na planilha) sobrescreve. No modo
   automático vale considerar só **preencher NF vazia** e deixar as trocas no
   relatório para alguém confirmar.
