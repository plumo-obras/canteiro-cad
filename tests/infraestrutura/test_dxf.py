"""Espelho no CAD em DXF de verdade (ezdxf), com um modelo inventado: não precisa dos PDFs de exemplo."""

import io

import ezdxf

from canteiro_cad.dominio import espelho as regras
from canteiro_cad.infraestrutura import dxf


def _caixa(eid, tipo, cx, cy, dx, dy, z0, z1, **prop):
    return {
        "id": eid,
        "tipo": tipo,
        "propriedades": prop,
        "geometria": {"forma": "caixa", "centro": [cx, cy], "dimensoes": [dx, dy], "z0": z0, "z1": z1},
    }


# P1 com a sapata S-P1 embaixo (mesmo centro) e duas vigas, térreo e cobertura, na mesma linha da planta: os casos
# em que os ids se encavalavam quando iam todos para o centro do polígono
MODELO = {
    "versao_contrato": "1.0",
    "limites": {"x0": 0, "y0": 0, "x1": 600, "y1": 100, "z0": -150, "z1": 310},
    "elementos": [
        _caixa("P1", "pilar", 0, 0, 15, 30, -150, 310),
        _caixa("P2", "pilar", 500, 0, 15, 30, -150, 310),
        _caixa("S-P1", "sapata", 0, 0, 85, 85, -150, -120),
        _caixa("S-P2", "sapata", 500, 0, 85, 85, -150, -120),
        _caixa("V-0-001", "viga", 250, 0, 500, 15, -30, 0, nivel_cm=0),
        _caixa("V-310-001", "viga", 250, 0, 500, 15, 270, 310, nivel_cm=310),
        {
            "id": "L1",
            "tipo": "laje",
            "propriedades": {"nivel_cm": 310},
            "geometria": {
                "forma": "prisma",
                "poligono": [[0, 0], [500, 0], [500, 300], [0, 300]],
                "z0": 300,
                "z1": 310,
            },
        },
    ],
}


def _caixas_dos_ids(dxf: bytes):
    doc = ezdxf.read(io.StringIO(dxf.decode()))
    caixas = {}
    for t in doc.modelspace().query("TEXT"):
        p = t.dxf.align_point
        caixas[t.dxf.text] = regras.caixa_texto(t.dxf.text, (p.x, p.y), t.dxf.height, t.dxf.rotation)
    return doc, caixas


def test_ids_nao_se_encavalam():
    _, caixas = _caixas_dos_ids(dxf.exportar(MODELO))
    assert set(caixas) == {e["id"] for e in MODELO["elementos"]}
    for a, b in [("P1", "S-P1"), ("P2", "S-P2"), ("V-0-001", "V-310-001")]:
        assert not regras.bate(caixas[a], caixas[b]), f"{a} e {b} no mesmo lugar"


def test_id_volta_pelo_texto_quando_o_cad_descarta_o_xdata():
    doc, _ = _caixas_dos_ids(dxf.exportar(MODELO))
    for pl in doc.modelspace().query("LWPOLYLINE"):
        pl.discard_xdata("PRUMO")
    buf = io.StringIO()
    doc.write(buf)
    lido = dxf.ler(buf.getvalue().encode())
    assert sorted(e["id"] for e in lido["elementos"]) == sorted(e["id"] for e in MODELO["elementos"])


def test_mover_um_pilar_vira_mudanca():
    doc, _ = _caixas_dos_ids(dxf.exportar(MODELO))
    for pl in doc.modelspace().query("LWPOLYLINE"):
        if pl.get_xdata("PRUMO")[0][1] == "P2":
            pl.set_points([(x + 20, y) for x, y in pl.get_points("xy")], format="xy")
    buf = io.StringIO()
    doc.write(buf)
    _, mudancas = regras.aplicar(MODELO, dxf.ler(buf.getvalue().encode()))
    assert [(m["id"], m["mudanca"]) for m in mudancas] == [("P2", "movido")]
