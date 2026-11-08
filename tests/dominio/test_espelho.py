"""Regras do espelho sem DXF: onde vai cada id e o que conta como mudança quando o espelho volta do CAD."""

from canteiro_cad.dominio import espelho as E


def _caixa(eid, tipo, cx, cy, dx, dy, **prop):
    return {
        "id": eid,
        "tipo": tipo,
        "propriedades": prop,
        "geometria": {"forma": "caixa", "centro": [cx, cy], "dimensoes": [dx, dy], "z0": 0, "z1": 300},
    }


def test_camada_por_tipo_e_nivel():
    assert E.camada(_caixa("P1", "pilar", 0, 0, 15, 30)) == "PRUMO-PILARES"
    assert E.camada(_caixa("P2", "pilar", 0, 0, 15, 30, morre=True)) == "PRUMO-PILARES-MORREM"
    assert E.camada(_caixa("V-310-001", "viga", 0, 0, 500, 15, nivel_cm=310)) == "PRUMO-VIGAS-310"


def test_id_da_sapata_nao_fica_no_centro_do_pilar():
    sapata = _caixa("S-P1", "sapata", 0, 0, 85, 85)
    (x, y), alt, _ = E.rotulos(sapata, E.contorno(sapata["geometria"]), [])[0]
    assert y < 0 and E.dentro((x, y), E.contorno(sapata["geometria"]))


def test_viga_de_niveis_diferentes_comeca_em_pontos_diferentes():
    a, b = (
        _caixa("V-0-001", "viga", 250, 0, 500, 15, nivel_cm=0),
        _caixa("V-310-001", "viga", 250, 0, 500, 15, nivel_cm=310),
    )
    niveis = sorted({E.camada(a), E.camada(b)})
    pa = E.rotulos(a, E.contorno(a["geometria"]), niveis)[0][0]
    pb = E.rotulos(b, E.contorno(b["geometria"]), niveis)[0][0]
    assert abs(pa[0] - pb[0]) > 100


def test_dentro_do_poligono():
    q = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert E.dentro((5, 5), q) and not E.dentro((15, 5), q)


def test_aplicar_acha_movido_redimensionado_novo_e_removido():
    modelo = {
        "elementos": [
            _caixa("P1", "pilar", 0, 0, 15, 30, secao_cm="15x30", armaduras=[1]),
            _caixa("P2", "pilar", 500, 0, 15, 30),
            _caixa("P3", "pilar", 900, 0, 15, 30),
        ]
    }
    editado = {
        "elementos": [
            {**_caixa("P1", "pilar", 0, 0, 20, 30), "nivel_cm": None, "morre": False},  # seção mudou
            {**_caixa("P2", "pilar", 530, 0, 15, 30), "nivel_cm": None, "morre": False},  # andou 30 cm
            {**_caixa("NOVO-pilar-1", "pilar", 200, 0, 15, 15), "nivel_cm": None, "morre": False},
        ]
    }
    novo, mud = E.aplicar(modelo, editado)
    assert [(m["id"], m["mudanca"]) for m in mud] == [
        ("P1", "redimensionado"),
        ("P2", "movido"),
        ("NOVO-pilar-1", "novo"),
        ("P3", "removido"),
    ]
    p1 = next(e for e in novo["elementos"] if e["id"] == "P1")
    # a armação do detalhamento era para a seção antiga: sai e fica marcada
    assert p1["propriedades"]["armacao_desatualizada"] and "armaduras" not in p1["propriedades"]
    assert novo["resumo"]["pilar"] == 3
