"""A API com os casos de uso de verdade e as portas em memória: códigos HTTP, autenticação e formato das respostas."""

import pytest
from fastapi.testclient import TestClient

from canteiro_cad.aplicacao.casos_de_uso import Tradutor
from canteiro_cad.interfaces.http.app import criar_app
from canteiro_cad.interfaces.http.configuracao import Configuracao
from tests.falsos import LOCACAO, EspelhoFalso, LeitorFalso, NotificadorFalso, RepositorioEmMemoria


@pytest.fixture
def cli(tmp_path):
    repo = RepositorioEmMemoria()
    tr = Tradutor(
        repo,
        LeitorFalso(repo, {"1.pdf": LOCACAO}),
        NotificadorFalso(),
        EspelhoFalso(),
        max_bytes=1024,
        retencao_horas=72,
    )
    cfg = Configuracao.do_ambiente({"TRADUTOR_DADOS": str(tmp_path), "TRADUTOR_API_KEYS": "chave-teste"})
    with TestClient(criar_app(cfg, tr)) as c:
        c.headers["X-API-Key"] = "chave-teste"
        yield c


def enviar(cli, nome="1.pdf", corpo=b"%PDF", aguardar=5):
    return cli.post(f"/v1/traducoes?aguardar={aguardar}", files={"arquivo": (nome, corpo, "application/pdf")})


def test_saude_sem_chave(cli):
    r = cli.get("/v1/saude", headers={"X-API-Key": ""})
    assert r.status_code == 200 and r.json()["versao_contrato"] == "1.0"


def test_chave_errada_e_401(cli):
    assert cli.get("/v1/traducoes/abc", headers={"X-API-Key": "errada"}).status_code == 401


@pytest.mark.parametrize(
    "nome,corpo,codigo", [("x.docx", b"oi", 415), ("x.pdf", b"", 400), ("x.pdf", b"0" * 2000, 413)]
)
def test_arquivo_recusado(cli, nome, corpo, codigo):
    r = enviar(cli, nome, corpo)
    assert r.status_code == codigo and r.json()["detail"]


def test_fluxo_completo(cli):
    r = enviar(cli)
    assert r.status_code == 200 and r.json()["versao_contrato"] == "1.0"
    tid = r.json()["id"]
    st = cli.get(f"/v1/traducoes/{tid}").json()
    assert st["status"] == "concluida" and set(st["links"]) == {"resultado", "modelo3d", "excel"}
    assert "callback_url" not in st
    assert cli.get(f"/v1/traducoes/{tid}/modelo3d").json()["resumo"]["pilar"] == 1
    x = cli.get(f"/v1/traducoes/{tid}/excel")
    assert x.status_code == 200 and x.headers["content-disposition"] == 'attachment; filename="1_traduzido.xlsx"'
    assert cli.get(f"/v1/projetos?ids={tid}").json()["modelo3d"]["resumo"]["pilar"] == 1
    e = cli.get(f"/v1/projetos/espelho.dxf?ids={tid}")
    assert e.status_code == 200 and e.headers["content-disposition"].startswith('attachment; filename="espelho-')
    assert cli.delete(f"/v1/traducoes/{tid}").status_code == 204
    assert cli.get(f"/v1/traducoes/{tid}").status_code == 404


def test_sem_aguardar_e_202_com_location(cli):
    r = enviar(cli, aguardar=0)
    assert r.status_code == 202 and r.headers["location"].endswith(f"/v1/traducoes/{r.json()['id']}")


def test_erros_do_dominio_viram_codigos(cli):
    assert cli.get("/v1/traducoes/naoexiste").status_code == 404
    assert cli.get("/v1/traducoes/..%2F..%2Fetc").status_code == 404
    assert cli.get("/v1/projetos?ids=a,a").status_code == 422
    assert cli.get("/v1/projetos/espelho.dxf?ids=naoexiste").status_code == 409
    sem_locacao = enviar(cli, "2.pdf").json()["id"]
    assert cli.get(f"/v1/traducoes/{sem_locacao}/modelo3d").status_code == 404
