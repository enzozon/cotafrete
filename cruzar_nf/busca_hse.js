// Motor da busca de NF no HSE Sistemas (Fiscal -> Notas fiscais).
//
// Roda DENTRO do iframe da tela de Notas fiscais (o que tem #formFiltro).
// Testado na tela real em 30/09/2026: a busca por 28230,00 achou a NF 13768.
//
// Detalhes da tela que este código respeita:
// - os selects múltiplos (Modelo, Filial, Status) são bootstrap-multiselect:
//   marcar a <option> não basta, tem que chamar multiselect('refresh');
// - "Emissão Fim" é obrigatório: sem ela o Consultar só abre o calendário;
// - a tabela de resultado é #listaNotas; quando não há nota, ela vem vazia;
// - a consulta é assíncrona. A resposta certa é reconhecida pela linha
//   "Filtros: ... Valor: 28230.00", que repete o valor digitado (com ponto).
({
  configurar(desde, ate) {
    const d = document, $ = window.jQuery;
    const marcar = (id, regra) => {
      const s = d.getElementById(id);
      [...s.options].forEach(o => { o.selected = regra(o.text.trim()); });
      try { $(s).multiselect('refresh'); } catch (e) { /* select comum */ }
    };
    marcar('rfModelo', t => /^55\b/.test(t));        // 55 - NFe
    marcar('cdFilial', () => true);                   // todas as empresas
    marcar('rfStatus', t => /^Autorizad/.test(t));    // só autorizadas
    const tipo = d.getElementById('idTipo');          // Operação: Saída
    tipo.value = [...tipo.options].find(o => /Sa[ií]da/.test(o.text)).value;
    d.getElementById('dtEmissaoIni').value = desde;
    d.getElementById('dtEmissaoFim').value = ate;
    return true;
  },

  async buscar(valor, tempoMaxMs) {
    const d = document, $ = window.jQuery;
    const esperado = Number(valor).toFixed(2);          // "28230.00"
    const digitado = esperado.replace('.', ',');        // "28230,00"
    const filtroValor = () => (d.body.innerText.match(/Valor: ([\d.]+)/) || [])[1];

    const velha = d.getElementById('listaNotas');
    if (velha) velha.setAttribute('data-velha', '1');
    for (const id of ['vlInicial', 'vlFinal']) {
      const e = d.getElementById(id);
      e.value = digitado;
      $(e).trigger('change');
    }
    $('.datepicker').hide();
    d.getElementById('btConsultar').click();

    const fim = Date.now() + (tempoMaxMs || 30000);
    while (Date.now() < fim) {
      await new Promise(r => setTimeout(r, 400));
      const t = d.getElementById('listaNotas');
      if (t && !t.hasAttribute('data-velha') && filtroValor() === esperado) {
        const notas = [...t.tBodies].flatMap(b => [...b.rows])
          .map(r => [...r.cells].map(c => c.innerText.trim()))
          .filter(c => /^\d+$/.test(c[5] || ''))
          .map(c => ({
            empresa: c[2], emissao: c[3], modelo: c[4], nota: c[5], serie: c[6],
            origem: c[7], cfop: c[8], destinatario: c[9], cnpj: c[10],
            valor: c[11], uf: c[15], status: c[16],
          }));
        return { valor: esperado, notas };
      }
    }
    return { valor: esperado, erro: 'o HSE não respondeu a tempo' };
  },
})
