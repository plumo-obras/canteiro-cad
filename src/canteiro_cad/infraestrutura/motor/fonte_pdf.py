"""Leitura direta de PDFs vetoriais (exportados do AutoCAD/Eberick): sem OCR, texto exato.

Além do texto, traz a CAMADA do CAD de cada texto e de cada vetor (o AutoCAD grava as camadas no PDF
como 'optional content'). No Eberick os nomes dizem o que cada coisa é: 'LC-Eixos', 'FO-Textos das vigas',
'DT-Título', 'Descrição da armadura', 'LC-Seção dos pilares', '...-Cotas' etc.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

DPI = 200
MIN_LINHAS = 30  # menos que isso = PDF escaneado / sem camada de texto


def _matriz(page):
    import fitz
    e = DPI / 72
    # coordenadas do PDF -> orientação exibida (a página pode ter /Rotate) -> pixels da imagem
    return page.rotation_matrix * fitz.Matrix(e, e)


def renderizar(page, camadas_visiveis: set[int] | None = None):
    pix = page.get_pixmap(dpi=DPI)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)


def ler_pdf(caminho: str | Path, pagina: int = 0, com_vetores: bool = False):
    """Retorna (tokens, imagem) — ou (tokens, imagem, vetores) com com_vetores=True.
    tokens = None se o PDF não tiver texto (escaneado)."""
    import fitz

    doc = fitz.open(str(caminho))
    page = doc[pagina]
    img = renderizar(page)
    m = _matriz(page)

    # camada de cada trecho de texto (texttrace) -> associada às linhas de texto por sobreposição
    trechos = [(fitz.Rect(s["bbox"]), s.get("layer")) for s in page.get_texttrace() if s.get("layer")]

    def camada_de(r: fitz.Rect):
        votos = {}
        for rr, cam in trechos:
            c = fitz.Point((rr.x0 + rr.x1) / 2, (rr.y0 + rr.y1) / 2)
            if r.x0 - 1 <= c.x <= r.x1 + 1 and r.y0 - 1 <= c.y <= r.y1 + 1:
                votos[cam] = votos.get(cam, 0) + 1
        return max(votos, key=votos.get) if votos else None

    tokens, vistos = [], set()
    for bloco in page.get_text("dict")["blocks"]:
        for linha in bloco.get("lines", []):
            texto = " ".join(s["text"].strip() for s in linha["spans"] if s["text"].strip())
            if not texto:
                continue
            bruto = fitz.Rect(linha["bbox"])
            r = bruto * m
            box = [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)]
            chave = (texto, round(r.x0), round(r.y0))
            if chave in vistos:  # CAD às vezes exporta texto duplicado
                continue
            vistos.add(chave)
            tam = max((s["size"] for s in linha["spans"]), default=0)
            tokens.append({"text": texto, "conf": 1.0, "box": box, "camada": camada_de(bruto),
                           "fonte_pt": round(tam, 1)})
    tokens.sort(key=lambda t: (t["box"][1], t["box"][0]))

    vetores = []
    if com_vetores:
        for d in page.get_drawings():
            r = fitz.Rect(d["rect"]) * m
            tipos = "".join(sorted({it[0] for it in d["items"]}))
            v = {"camada": d.get("layer"), "box": [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)],
                 "tipos": tipos, "espessura": round(d.get("width") or 0, 2), "preenchido": d.get("fill") is not None}
            if (d.get("layer") or "").startswith("FO-"):  # formas: guarda os segmentos (traçado de vigas/pilares/lajes)
                segs = []
                for it in d["items"]:
                    if it[0] == "l":
                        a_, b_ = it[1] * m, it[2] * m
                        segs.append([round(a_.x, 1), round(a_.y, 1), round(b_.x, 1), round(b_.y, 1)])
                    elif it[0] in ("re", "qu"):
                        q = (it[1].quad if it[0] == "re" else it[1]) * m
                        pts = [q.ul, q.ur, q.lr, q.ll]
                        for i in range(4):
                            segs.append([round(pts[i].x, 1), round(pts[i].y, 1), round(pts[(i + 1) % 4].x, 1), round(pts[(i + 1) % 4].y, 1)])
                v["segs"] = segs
            vetores.append(v)

    if len(tokens) < MIN_LINHAS:
        tokens = None
    return (tokens, img, vetores) if com_vetores else (tokens, img)
