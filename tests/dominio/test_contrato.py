from canteiro_cad.dominio import contrato
from tests.falsos import LOCACAO


def test_modelo3d_do_contrato():
    m = contrato.modelo3d(LOCACAO, "t1")
    assert m["versao_contrato"] == "1.0" and m["resumo"] == {"pilar": 1, "sapata": 1, "viga": 0, "laje": 0}
    assert [e["id"] for e in m["elementos"]] == ["P1", "S-P1"]
    assert m["sistema_coordenadas"]["unidade"] == "cm"


def test_prancha_sem_locacao_nao_tem_modelo():
    assert contrato.modelo3d({"modelo_3d": None}, "t1") is None


def test_resultado_esconde_o_rastreio_salvo_pedido():
    r = {**LOCACAO, "rastreio": [1, 2]}
    assert "rastreio" not in contrato.resultado(r, "t1")
    assert contrato.resultado(r, "t1", incluir_rastreio=True)["rastreio"] == [1, 2]
