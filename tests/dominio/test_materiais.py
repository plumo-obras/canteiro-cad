import pytest

from canteiro_cad.dominio import materiais as M


def _folha(folha="02", aco=(), concreto=None, forma=0, blocos=(), vigotas=(), fonte="pdf-vetorial"):
    return {
        "fonte": fonte,
        "carimbo": {"folha": folha},
        "tabelas_aco": [{"linhas": [{"aco": a, "diam_mm": d, "c_total_cm": cm} for a, d, cm in aco]}],
        "totais": {"concreto_m3": concreto or {}, "forma_m2": forma},
        "blocos_enchimento": list(blocos),
        "desenhos": [{"tipo": "vigotas", "dados": {"vigotas": list(vigotas)}}],
    }


@pytest.mark.parametrize(
    "aco,cad,real,ajustou",
    [("CA50", 10.0, 10.0, False), ("CA-50", 9.8, 10.0, True), ("CA50", 9.0, 10.0, True), ("CA60", 5.0, 5.0, False),
     ("CA50", 15.0, 16.0, True), ("CA50", 14.0, None, False)],
)  # fmt: skip
def test_bitola_fabricada_nbr_7480(aco, cad, real, ajustou):
    bitola, ajuste = M.bitola_fabricada(aco, cad)
    assert bitola == real and (ajuste is not None) == ajustou


def test_aco_por_bitola_com_massa_linear_e_perda():
    mats, avisos = M.levantar([("a", _folha(aco=[("CA50", 10.0, 6000), ("CA50", 10.0, 4000), ("CA60", 5.0, 10000)]))])
    ca50 = next(m for m in mats if m.chave == "aco:CA50:10.0")
    assert ca50.quantidade == round(100 * 0.617 * 1.1, 1) and ca50.unidade == "kg"
    assert ca50.atributos["metros"] == 100.0 and ca50.origem == ["Folha 02"]
    assert next(m for m in mats if m.chave == "aco:CA60:5.0").quantidade == round(100 * 0.154 * 1.1, 1)
    assert avisos == []


def test_bitola_digitada_errada_vira_a_real_com_ajuste_e_a_estranha_vira_aviso():
    mats, avisos = M.levantar([("a", _folha(aco=[("CA50", 9.8, 1000), ("CA50", 14.0, 1000)]))])
    assert [m.chave for m in mats] == ["aco:CA50:10.0"]
    assert "NBR 7480" in mats[0].ajuste
    assert len(avisos) == 1 and "14.0" in avisos[0]


def test_concreto_forma_blocos_e_vigotas_de_varias_folhas():
    f1 = _folha("01", blocos=[{"nome": "B8/30/125", "descricao": "EPS B8/30/125", "quantidade": 300, "hb_cm": 8}])
    f2 = _folha("02", concreto={"C-30": 10.0, "C-25": 2.0}, forma=100.0)
    f3 = _folha("03", concreto={"C30": 5.5}, forma=50.5, vigotas=[{"vigota": "VP1", "comprimento_cm": 300}])
    mats, avisos = M.levantar([("a", f1), ("b", f2), ("c", f3)])
    por = {m.chave: m for m in mats}
    assert por["concreto:C30"].quantidade == 15.5 and por["concreto:C30"].origem == ["Folha 02", "Folha 03"]
    assert por["concreto:C25"].quantidade == 2.0
    assert por["forma:chapa"].quantidade == 150.5 and "reaproveitamento" in por["forma:chapa"].nota
    assert por["enchimento:B8/30/125"].quantidade == 300
    # vigota: a planta não diz quantas comprar; o item existe, com quantidade a confirmar
    assert por["vigota:planta"].quantidade == 0 and "fornecedor" in por["vigota:planta"].nota


def test_espelho_do_cad_nao_soma_materiais():
    mats, _ = M.levantar([("a", _folha(concreto={"C-30": 1.0}, fonte="dxf-espelho"))])
    assert mats == []
