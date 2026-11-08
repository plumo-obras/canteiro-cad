"""Espelho do modelo no CAD (DXF): ida e volta.

Ida: o modelo do pacote (contrato 1.0: pilares, sapatas, vigas, lajes com id) vira um DXF em planta, em cm, com uma
camada por tipo e nível (PRUMO-PILARES, PRUMO-VIGAS-310...). Cada elemento é um polígono fechado; o id vai em dois
lugares: um texto na camada PRUMO-IDS (visível, sobrevive a qualquer CAD) e o XDATA "PRUMO" do polígono (id, z0, z1).

Volta: o DXF editado (CADCraft, AutoCAD, LibreCAD...) é lido de novo, exato, sem OCR. Cada polígono das camadas
PRUMO-* volta como elemento; o id sai do XDATA ou, se o CAD não o guardou, do texto que cai dentro do polígono.
Polígono sem id é elemento novo. O que sumiu foi removido.
"""

from __future__ import annotations

import io
import re

import ezdxf
from ezdxf.math import Vec2

from canteiro_cad.dominio import espelho as E

APP = "PRUMO"
CAMADAS_FIXAS = {
    "PRUMO-SAPATAS": 8,  # cinza
    "PRUMO-PILARES": 7,  # branco/preto
    "PRUMO-PILARES-MORREM": 2,  # amarelo
    "PRUMO-IDS": 3,  # verde
    "PRUMO-INFO": 9,
}
COR_VIGA, COR_LAJE = 5, 4  # azul, ciano


def exportar(modelo: dict, obra: dict | None = None, ids_base: list[str] | None = None) -> bytes:
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.CM
    doc.appids.add(APP)
    hdr = doc.header.custom_vars
    hdr.append("PRUMO_CONTRATO", modelo.get("versao_contrato", "1.0"))
    hdr.append("PRUMO_BASE", ",".join(ids_base or []))
    for k in ("cliente", "local", "responsavel"):
        if obra and obra.get(k):
            hdr.append(f"PRUMO_{k.upper()}", str(obra[k]))
    for nome, cor in CAMADAS_FIXAS.items():
        doc.layers.add(nome, color=cor)
    msp = doc.modelspace()
    niveis_viga = sorted({E.camada(e) for e in modelo["elementos"] if e["tipo"] == "viga"})
    postos: list[tuple[float, float, float, float]] = []
    # pilares primeiro (lugar fixo, no centro), depois sapatas e vigas se acomodam em volta
    ordem = {"pilar": 0, "sapata": 1, "viga": 2}
    for e in sorted(modelo["elementos"], key=lambda e: ordem.get(e["tipo"], 3)):
        cam = E.camada(e)
        if cam not in doc.layers:
            doc.layers.add(cam, color=COR_VIGA if "VIGAS" in cam else COR_LAJE)
        pts = E.contorno(e["geometria"])
        pl = msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": cam})
        g = e["geometria"]
        pl.set_xdata(APP, [(1000, e["id"]), (1000, e["tipo"]), (1040, float(g["z0"])), (1040, float(g["z1"]))])
        # o texto fica dentro do polígono: é por ele que o id volta se o CAD descartar o XDATA. Dos lugares
        # possíveis, o primeiro que não cobre um id já posto (lajes não contam: são grandes e o id delas é central)
        opcoes = E.rotulos(e, pts, niveis_viga)
        (x, y), alt, rot = next(
            (o for o in opcoes if not any(E.bate(E.caixa_texto(e["id"], *o), c) for c in postos)), opcoes[0]
        )
        if e["tipo"] != "laje":
            postos.append(E.caixa_texto(e["id"], (x, y), alt, rot))
        msp.add_text(e["id"], height=alt, rotation=rot, dxfattribs={"layer": "PRUMO-IDS"}).set_placement(
            (x, y), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
        )
    lim = modelo["limites"]
    msp.add_mtext(
        "PRUMO: modelo estrutural (cm). Edite os polígonos nas camadas PRUMO-*: mover, redimensionar, apagar ou "
        "desenhar novo (polilinha fechada). Mantenha o id (texto verde) dentro do polígono. Salve em DXF e arraste no "
        "Projeto 3D.",
        dxfattribs={"layer": "PRUMO-INFO", "char_height": 10, "width": 600},
    ).set_location((lim["x0"], lim["y0"] - 40))
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def ler(conteudo: bytes) -> dict:
    """DXF editado -> elementos no formato do contrato (geometria + id), mais os metadados gravados na ida."""
    # leitura binária tolerante: cada CAD grava a quebra de linha, a codificação e o cabeçalho do seu jeito (o DXF
    # salvo pelo CADCraft, lido como texto, vinha vazio)
    from ezdxf import recover

    doc, _auditoria = recover.read(io.BytesIO(conteudo))
    meta = {}
    try:
        for k, v in doc.header.custom_vars:
            if k.startswith("PRUMO_"):
                meta[k[6:].lower()] = v
    except Exception:  # noqa: BLE001
        pass
    msp = doc.modelspace()
    textos = [
        (
            t.dxf.text.strip(),
            Vec2(t.dxf.insert if t.dxf.halign == 0 and t.dxf.valign == 0 else t.dxf.align_point or t.dxf.insert),
        )
        for t in msp.query("TEXT")
        if t.dxf.layer.upper() == "PRUMO-IDS"
    ]
    textos += [
        (m.plain_text().strip(), Vec2(m.dxf.insert)) for m in msp.query("MTEXT") if m.dxf.layer.upper() == "PRUMO-IDS"
    ]
    # 1ª passada: geometria, tipo e o id do XDATA (quando o CAD o guardou)
    brutos, sem_contorno = [], 0
    for pl in msp.query("LWPOLYLINE POLYLINE"):
        cam = pl.dxf.layer.upper()
        if not cam.startswith("PRUMO-") or cam in ("PRUMO-IDS", "PRUMO-INFO"):
            continue
        pts = [
            (p[0], p[1])
            for p in (pl.get_points("xy") if pl.dxftype() == "LWPOLYLINE" else [v.dxf.location for v in pl.vertices])
        ]
        if len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
            pts = pts[:-1]
        if len(pts) < 3:
            sem_contorno += 1
            continue
        if cam.startswith("PRUMO-PILARES"):
            tipo = "pilar"
        elif cam == "PRUMO-SAPATAS":
            tipo = "sapata"
        elif cam.startswith("PRUMO-VIGAS"):
            tipo = "viga"
        elif cam.startswith("PRUMO-LAJES"):
            tipo = "laje"
        else:
            continue
        eid, z0, z1 = None, None, None
        if pl.has_xdata(APP):
            xd = pl.get_xdata(APP)
            strs = [v for c, v in xd if c == 1000]
            nums = [v for c, v in xd if c == 1040]
            eid = strs[0] if strs else None
            if len(nums) >= 2:
                z0, z1 = nums[0], nums[1]
        nivel = re.search(r"-(-?\d+)$", cam)
        brutos.append(
            {
                "cam": cam,
                "tipo": tipo,
                "pts": pts,
                "id": eid,
                "z0": z0,
                "z1": z1,
                "nivel": int(nivel.group(1)) if nivel and tipo in ("viga", "laje") else None,
            }
        )

    # 2ª passada: quem ficou sem XDATA pega o id pelo texto. Cada camada só aceita o id do seu tipo (o "P1" também cai
    # dentro da sapata S-P1; viga do térreo e da cobertura se sobrepõem na planta), o mais perto do centro, e cada
    # texto vale para um polígono só. Quem moveu o polígono e esqueceu o texto ainda casa pelo texto livre mais perto.
    def padrao(b):
        return {
            "pilar": r"P\d+[A-Z]?$",
            "sapata": r"S-P\d+[A-Z]?$",
            "laje": r"L\d+[A-Z]?$",
            "viga": rf"V-{b['nivel']}-\d+$" if b["nivel"] is not None else r"V-.*$",
        }[b["tipo"]]

    usados = {b["id"] for b in brutos if b["id"]}
    livres = [(t, p) for t, p in textos if t not in usados]

    def centro(pts):
        return Vec2(sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))

    pares = []
    for i, b in enumerate(brutos):
        if b["id"]:
            continue
        c = centro(b["pts"])
        for j, (t, p) in enumerate(livres):
            if re.match(padrao(b), t):
                pares.append((0 if E.dentro((p.x, p.y), b["pts"]) else 1, (p - c).magnitude, i, j))

    def tamanho(pts):
        return max(max(x for x, _ in pts) - min(x for x, _ in pts), max(y for _, y in pts) - min(y for _, y in pts))

    ja_i, ja_j = set(), set()
    for fora, d, i, j in sorted(pares):
        if i in ja_i or j in ja_j or (fora and d > 2 * tamanho(brutos[i]["pts"]) + 50):
            continue
        brutos[i]["id"] = livres[j][0]
        ja_i.add(i)
        ja_j.add(j)

    elementos, novos = [], 0
    for b in brutos:
        tipo, pts = b["tipo"], b["pts"]
        eid = b["id"]
        if not eid:
            novos += 1
            eid = f"NOVO-{tipo}-{novos}"
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if tipo == "laje" or len(pts) != 4:
            geo = {"forma": "prisma", "poligono": [[round(x, 1), round(y, 1)] for x, y in pts]}
        else:
            geo = {
                "forma": "caixa",
                "centro": [round((min(xs) + max(xs)) / 2, 1), round((min(ys) + max(ys)) / 2, 1)],
                "dimensoes": [round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)],
            }
        geo["z0"], geo["z1"] = b["z0"], b["z1"]  # None = herdar do modelo base
        elementos.append(
            {
                "id": eid,
                "tipo": tipo,
                "geometria": geo,
                "camada": b["cam"],
                "nivel_cm": b["nivel"],
                "morre": b["cam"] == "PRUMO-PILARES-MORREM",
            }
        )
    return {"meta": meta, "elementos": elementos, "polilinhas_abertas": sem_contorno}


class EspelhoDxf:
    """A porta EspelhoCad em DXF (ezdxf)."""

    def exportar(self, modelo: dict, obra: dict | None, ids_base: list[str]) -> bytes:
        return exportar(modelo, obra, ids_base)
