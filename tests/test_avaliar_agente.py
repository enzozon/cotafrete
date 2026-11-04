from scripts.avaliar_agente import pontuar


def _l(esp, obt, conf="alta", ce=False, co=()):
    return {"culpa_esp": esp, "culpa_obt": obt, "conf": conf, "criados_esp": ce, "criados_obt": list(co)}


def test_pontuar_culpa_e_perigo():
    m = pontuar([_l("vendedor", "vendedor"), _l("robo", "vendedor"), _l("robo", "robo", conf="media"),
                 _l("teste", "x"), _l("hse", "hse", ce=True, co=[]), _l("hse", "hse", ce=True, co=[5]),
                 {**_l("hse", "hse"), "criados_obt": "nao_verificado"}])
    assert (m["culpa_ok"], m["culpa_tot"]) == (5, 6)       # "teste" fica fora
    assert (m["alta_ok"], m["alta_tot"]) == (4, 5)
    assert m["perigosos"] == 1 and m["nao_verificado"] == 1
    assert m["criados_ok"] == 5 and m["criados_tot"] == 6
