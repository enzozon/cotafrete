from orcamento.hse import motivo_recusa

# trecho real da resposta do Incluir recusado (mouse 13370 a 43,50 no orçamento 16354)
RECUSA = """<script>
    var percentDesconto = 0;
    var percentDescontoValor = 30.23;
    var percentDescMax = 15;
    var erroDescontoMsg = 'Desconto máximo 15%<br>desconto aplicado 30,23%';
    //console.log('vlOriginal', 62.35);
</script>"""


def test_motivo_da_recusa_por_desconto():
    assert motivo_recusa(RECUSA) == ("Desconto máximo 15% - desconto aplicado 30,23%; "
                                     "preço de tabela 62,35, menor preço aceito 53,00")


def test_recusa_sem_mensagem():
    assert motivo_recusa("<div>tabela</div>") == "o HSE não informou o motivo"
