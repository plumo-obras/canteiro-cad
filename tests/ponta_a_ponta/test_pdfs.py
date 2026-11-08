"""Ponta a ponta com as pranchas de verdade: a API inteira, o motor e os processos de leitura.

Usa os PDFs de exemplo, que são de cliente e por isso não ficam no repositório (variável EXEMPLOS_PDF, padrão
~/Downloads/{1,2,3}.pdf). Sem eles, os testes pulam; rodar antes de mexer no motor:
    EXEMPLOS_PDF=/caminho .venv/bin/pytest tests/ponta_a_ponta -q
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PASTA = Path(os.environ.get("EXEMPLOS_PDF", str(Path.home() / "Downloads")))
PDF1, PDF2 = PASTA / "1.pdf", PASTA / "2.pdf"
pytestmark = pytest.mark.skipif(not PDF1.exists(), reason="PDFs de exemplo ausentes")


@pytest.fixture(scope="module")
def cli(tmp_path_factory):
    from canteiro_cad.interfaces.http.app import criar_app
    from canteiro_cad.interfaces.http.configuracao import Configuracao

    cfg = Configuracao.do_ambiente(
        {
            "TRADUTOR_DADOS": str(tmp_path_factory.mktemp("dados")),
            "TRADUTOR_API_KEYS": "chave-teste",
            "TRADUTOR_SINAPI_AUTO": "0",
        }
    )
    with TestClient(criar_app(cfg)) as c:
        c.headers["X-API-Key"] = "chave-teste"
        yield c


def test_saude(cli):
    r = cli.get("/v1/saude")
    assert r.status_code == 200 and r.json()["versao_contrato"] == "1.0"


def test_sem_chave(cli):
    r = cli.get("/v1/traducoes/abc", headers={"X-API-Key": "errada"})
    assert r.status_code == 401


def test_formato_invalido(cli):
    r = cli.post("/v1/traducoes", files={"arquivo": ("x.docx", b"oi", "application/octet-stream")})
    assert r.status_code == 415


def test_pdf_locacao_e_modelo3d(cli):
    with open(PDF1, "rb") as f:
        r = cli.post("/v1/traducoes?aguardar=120", files={"arquivo": ("1.pdf", f, "application/pdf")})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["versao_contrato"] == "1.0" and "rastreio" not in res
    assert res["cobertura"]["sem_regiao"] == 0
    tid = res["id"]
    st = cli.get(f"/v1/traducoes/{tid}").json()
    assert st["status"] == "concluida" and "modelo3d" in st["links"]
    m = cli.get(f"/v1/traducoes/{tid}/modelo3d").json()
    import json

    import jsonschema

    esquema = json.loads((Path(__file__).resolve().parents[2] / "docs" / "modelo3d.schema.json").read_text())
    jsonschema.validate(m, esquema)  # o contrato publicado continua valendo
    assert m["resumo"] == {"pilar": 31, "sapata": 31, "viga": m["resumo"]["viga"], "laje": 13}
    assert m["resumo"]["viga"] > 50
    assert all(f["calibracao_erro_cm"] < 2 for f in m["calibracao_formas"])
    p1 = next(e for e in m["elementos"] if e["id"] == "P1")
    assert p1["geometria"]["forma"] == "caixa" and abs(p1["geometria"]["centro"][0] - 234.0) < 1
    x = cli.get(f"/v1/traducoes/{tid}/excel")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_pdf_detalhamento(cli):
    with open(PDF2, "rb") as f:
        r = cli.post("/v1/traducoes?aguardar=120", files={"arquivo": ("2.pdf", f, "application/pdf")})
    res = r.json()
    linhas = sum(len(t["linhas"]) for t in res["tabelas_aco"])
    assert linhas == 84 and all(t["linhas_com_divergencia"] == 0 for t in res["tabelas_aco"])
    assert len(res["detalhamentos"]["Vigas"]) == 26
    tid = res["id"]
    assert cli.get(f"/v1/traducoes/{tid}/modelo3d").status_code == 404  # folha sem locação
    assert cli.delete(f"/v1/traducoes/{tid}").status_code == 204
    assert cli.get(f"/v1/traducoes/{tid}").status_code == 404


def test_projeto_junta_as_folhas(cli):
    ids = []
    for nome in ("1.pdf", "2.pdf", "3.pdf"):
        with open(PASTA / nome, "rb") as f:
            r = cli.post("/v1/traducoes?aguardar=120", files={"arquivo": (nome, f, "application/pdf")})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    o = cli.get(f"/v1/projetos?ids={','.join(ids)}").json()
    assert o["pronto_para_3d"] and all(p["situacao"] == "coberto" for p in o["pacote"])
    assert o["quantitativos"]["aco_total_kg"] == 1129.2
    sap = [e for e in o["modelo3d"]["elementos"] if e["tipo"] == "sapata"]
    assert len(sap) == 31 and not any(e["propriedades"]["dimensao_em_planta_estimada"] for e in sap)
    textos = " ".join(c["texto"] for c in o["conferencias"])
    assert "31/31" in textos and "26/34" in textos
    # só com a locação: o pacote mostra o que falta e o 3D sai com sapata estimada
    o1 = cli.get(f"/v1/projetos?ids={ids[0]}").json()
    falta = {p["papel"] for p in o1["pacote"] if p["situacao"] == "faltando"}
    assert {"fundacoes", "pilares", "vigas", "lajes"} <= falta
    assert cli.get("/v1/projetos?ids=a,a").status_code == 422


def test_espelho_cad_ida_e_volta(cli):
    import io

    import ezdxf

    ids = []
    for nome in ("1.pdf", "2.pdf", "3.pdf"):
        with open(PASTA / nome, "rb") as f:
            ids.append(
                cli.post("/v1/traducoes?aguardar=120", files={"arquivo": (nome, f, "application/pdf")}).json()["id"]
            )
    r = cli.get(f"/v1/projetos/espelho.dxf?ids={','.join(ids)}")
    assert r.status_code == 200 and b"PRUMO-PILARES" in r.content
    # edita como um CAD faria: move o P5 (polígono e texto) e apaga uma viga
    from ezdxf import recover

    doc, _ = recover.read(io.BytesIO(r.content))
    msp = doc.modelspace()

    def pl(i):
        return next(p for p in msp.query("LWPOLYLINE") if p.has_xdata("PRUMO") and p.get_xdata("PRUMO")[0][1] == i)

    pl("P5").translate(20, 0, 0)
    next(t for t in msp.query("TEXT") if t.dxf.text == "P5").translate(20, 0, 0)
    msp.delete_entity(pl("V-310-001"))
    buf = io.StringIO()
    doc.write(buf)
    e = cli.post(
        "/v1/traducoes?aguardar=30", files={"arquivo": ("editado.dxf", buf.getvalue().encode(), "application/dxf")}
    )
    assert e.status_code == 200, e.text
    o = cli.get(f"/v1/projetos?ids={','.join(ids + [e.json()['id']])}").json()
    textos = [m["texto"] for m in o["edicoes_cad"]["mudancas"]]
    assert textos == ["P5 movido 20 cm", "V-310-001 removido no CAD"]
    p5 = next(x for x in o["modelo3d"]["elementos"] if x["id"] == "P5")
    assert abs(p5["geometria"]["centro"][0] - 418.6) < 1
    assert not any(x["id"] == "V-310-001" for x in o["modelo3d"]["elementos"])
    # DXF que não é espelho é recusado com explicação
    vazio = io.StringIO()
    ezdxf.new().write(vazio)
    f = cli.post(
        "/v1/traducoes?aguardar=30", files={"arquivo": ("qualquer.dxf", vazio.getvalue().encode(), "application/dxf")}
    ).json()
    assert f["status"] == "falhou" and "PRUMO" in f["erro"]
