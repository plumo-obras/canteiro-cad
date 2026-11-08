"""O catálogo pelo canteiro-products, com o serviço simulado no transporte do httpx: as mesmas regras do catálogo local
escolhem entre os candidatos da busca; serviço fora do ar vira material sem código, não erro."""

import httpx
import pytest

from canteiro_cad.dominio.materiais import Material
from canteiro_cad.infraestrutura import catalogo_produtos
from canteiro_cad.infraestrutura.catalogo_produtos import CatalogoProdutos

ITENS = [
    {"codigo": "43061", "descricao": "ACO CA-60, 4,2 MM OU 5,0 MM, DOBRADO E CORTADO", "unidade": "KG",
     "preco_centavos": 664},
    {"codigo": "43059", "descricao": "ACO CA-60, 4,2 MM, OU 5,0 MM, OU 6,0 MM, OU 7,0 MM, VERGALHAO", "unidade": "KG",
     "preco_centavos": 633},
    {"codigo": "34", "descricao": "ACO CA-50, 10,0 MM, VERGALHAO", "unidade": "KG", "preco_centavos": None},
]  # fmt: skip


@pytest.fixture
def servico(monkeypatch):
    pedidos = []

    def responder(req: httpx.Request) -> httpx.Response:
        pedidos.append(req)
        if req.headers.get("x-api-key") != "k":
            return httpx.Response(401)
        if req.url.path == "/v1/bases":
            return httpx.Response(200, json=[{"base": "sinapi", "meses": ["2026-09", "2026-08"]}])
        return httpx.Response(200, json={"itens": ITENS})

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: cliente.get(url, **kw))
    return pedidos


def _aco(cat, mm):
    return Material("", "aco", "", "kg", 1, atributos={"aco": cat, "bitola_mm": mm})


def test_referencia_e_correspondente_pelo_servico(servico):
    c = CatalogoProdutos("http://produtos:8000/", "k")
    assert c.referencia() == {"fonte": "SINAPI", "mes": "2026-09", "encargos": "sem desoneração"}
    r = c.correspondente(_aco("CA60", 5.0), "sp")
    assert (r.codigo, r.preco_centavos) == ("43059", 633)  # vergalhão, não o dobrado e cortado
    busca = servico[-1]
    assert busca.url.params["q"] == "aco CA 60 5 0 vergalhao" and busca.url.params["uf"] == "SP"
    assert c.correspondente(_aco("CA50", 10.0), "SP").preco_centavos is None  # sem preço na UF


def test_servico_fora_do_ar_nao_derruba(monkeypatch):
    def cair(*_a, **_kw):
        raise httpx.ConnectError("fora do ar")

    monkeypatch.setattr(httpx, "get", cair)
    c = CatalogoProdutos("http://produtos:8000", "k")
    assert c.referencia() is None and c.correspondente(_aco("CA50", 10.0), "SP") is None


def test_categoria_sem_regra_nem_pergunta(servico):
    c = CatalogoProdutos("http://produtos:8000", "k")
    assert c.correspondente(Material("", "enchimento", "", "un", 1), "SP") is None
    assert servico == []
    assert catalogo_produtos._termos(Material("", "concreto", "", "m3", 1, atributos={"fck_mpa": 30})).startswith(
        "concreto usinado bombeavel c30"
    )
