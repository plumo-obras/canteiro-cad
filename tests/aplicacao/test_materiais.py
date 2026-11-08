import pytest

from canteiro_cad.aplicacao.casos_de_uso import Tradutor
from canteiro_cad.dominio.erros import PedidoInvalido
from tests.falsos import DETALHAMENTO, CatalogoFalso, EspelhoFalso, LeitorFalso, NotificadorFalso, RepositorioEmMemoria


def montar(catalogo):
    repo = RepositorioEmMemoria()
    ids = iter(f"t{i}" for i in range(1, 100))
    tr = Tradutor(repo, LeitorFalso(repo, {"det.pdf": DETALHAMENTO}), NotificadorFalso(), EspelhoFalso(), catalogo,
                  max_bytes=1024, retencao_horas=72, novo_id=lambda: next(ids))  # fmt: skip
    return tr


async def test_materiais_com_codigo_preco_e_total_em_centavos():
    tr = montar(CatalogoFalso())
    await tr.enviar("det.pdf", b"%PDF", aguardar=5)
    out = tr.materiais(["t1"], "sp")
    assert out["referencia"] == {"fonte": "SINAPI", "mes": "2026-09", "encargos": "sem desoneração", "uf": "SP"}
    aco = next(i for i in out["itens"] if i["chave"] == "aco:CA50:10.0")
    assert aco["quantidade"] == 67.9  # 100 m x 0,617 kg/m x 1,10
    assert aco["referencia"] == {"codigo": "34", "descricao": "ACO CA-50, 10,0 MM, VERGALHAO", "unidade": "KG",
                                 "preco_centavos": 669, "total_centavos": round(669 * 67.9)}  # fmt: skip
    concreto = next(i for i in out["itens"] if i["chave"] == "concreto:C30")
    assert concreto["referencia"] is None  # o falso não acha: o item vem, sem código
    assert out["total_referencia_centavos"] == round(669 * 67.9)


async def test_uf_sem_preco_e_sem_catalogo():
    tr = montar(CatalogoFalso())
    await tr.enviar("det.pdf", b"%PDF", aguardar=5)
    assert tr.materiais(["t1"], "MG")["itens"][0]["referencia"]["total_centavos"] is None
    sem = montar(CatalogoFalso(carregado=False))
    await sem.enviar("det.pdf", b"%PDF", aguardar=5)
    out = sem.materiais(["t1"], "SP")
    assert out["referencia"] is None and all(i["referencia"] is None for i in out["itens"])
    assert any("SINAPI" in a for a in out["avisos"])


@pytest.mark.parametrize("uf", ["", "XX", "São Paulo"])
def test_uf_invalida(uf):
    with pytest.raises(PedidoInvalido):
        montar(CatalogoFalso()).materiais(["t1"], uf)
