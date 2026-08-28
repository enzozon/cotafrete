"""O casco compartilhado das telas.

Existe como módulo próprio porque web/adm.py precisa dele e web/app.py
registra as rotas do adm — importar um do outro seria circular. De quebra
tira ~200 linhas de um arquivo que tinha 1753."""

from web import layout


def test_a_pagina_monta_o_casco_completo():
    html = layout.pagina("Teste", "<p>oi</p>")

    assert html.startswith("<!doctype html>")
    assert 'lang="pt-BR"' in html
    assert "Teste — Cotafrete" in html
    assert "<p>oi</p>" in html
    assert layout.CSS in html


def test_o_menu_so_aparece_com_usuario():
    """Sem cookie não há para onde navegar — e mostrar 'Sair' para quem não
    entrou confunde."""
    assert "/historico" not in layout.pagina("t", "c")
    assert "/historico" in layout.pagina("t", "c", usuario="enzo")


def test_escapa_html_do_usuario():
    """O nome vem de um formulário aberto. Sem escapar, vira XSS."""
    assert "<script>" not in layout.pagina("t", "c", usuario="<script>x</script>")
    assert layout.e("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
