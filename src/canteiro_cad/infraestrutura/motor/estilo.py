"""Perfil de estilo aprendido dos PDFs do CAD (engenharia reversa do padrão Eberick/AutoCAD).

Os PDFs trazem a camada de cada texto. Daqui saem medidas que valem também para PNG do mesmo padrão:
altura do texto por tipo (camada), e como os rótulos dos eixos ficam em relação às coordenadas.

    python estilo.py prancha1.pdf prancha2.pdf ...   -> grava estilo.json
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

ARQ = Path(__file__).with_name("estilo.json")
PADRAO = {  # valores dos exemplos (A1, 200 dpi) — usados se estilo.json não existir
    "altura_px_por_camada": {},
    "eixo_rotulo_altura_px": 45.0,
    "eixo_coord_altura_px": 47.0,
}


def carregar() -> dict:
    try:
        return {**PADRAO, **json.loads(ARQ.read_text())}
    except (OSError, ValueError):
        return dict(PADRAO)


def aprender(pdfs: list[str]) -> dict:
    from . import fonte_pdf

    import cv2
    import numpy as np

    alturas: dict[str, list[float]] = {}
    rot, coord, recortes = [], [], []
    for arq in pdfs:
        toks, img, vet = fonte_pdf.ler_pdf(arq, com_vetores=True)
        if not toks:
            continue
        # símbolo do pilar (retângulo hachurado) recortado da própria renderização do PDF
        cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for v in vet:
            if v["camada"] and "Seção dos pilares" in v["camada"] and v["camada"].startswith("LC"):
                x0, y0, x1, y1 = (int(round(c)) for c in v["box"])
                r = cinza[y0 - 2:y1 + 3, x0 - 2:x1 + 3]
                if r.size and r.shape[0] < r.shape[1]:
                    r = cv2.rotate(r, cv2.ROTATE_90_CLOCKWISE)
                if r.size:
                    recortes.append(r)
        for t in toks:
            x0, y0, x1, y1 = t["box"]
            menor = min(x1 - x0, y1 - y0) if len(t["text"]) > 1 else (y1 - y0)
            if t.get("camada"):
                alturas.setdefault(t["camada"], []).append(menor)
            if re.fullmatch(r"[A-Z]|\d", t["text"]) and t.get("fonte_pt", 0) > 12:
                rot.append(y1 - y0)
            if re.fullmatch(r"\d+\.\d\d", t["text"]) and t.get("fonte_pt", 0) > 12:
                coord.append(min(x1 - x0, y1 - y0))
    if recortes:
        hh = int(statistics.median(r.shape[0] for r in recortes))
        ww = int(statistics.median(r.shape[1] for r in recortes))
        modelo = np.median(np.stack([cv2.resize(r, (ww, hh)) for r in recortes]), axis=0).astype("uint8")
        cv2.imwrite(str(ARQ.with_name("estilo_pilar.png")), modelo)
    perfil = {
        "altura_px_por_camada": {k: round(statistics.median(v), 1) for k, v in sorted(alturas.items())},
        "eixo_rotulo_altura_px": round(statistics.median(rot), 1) if rot else PADRAO["eixo_rotulo_altura_px"],
        "eixo_coord_altura_px": round(statistics.median(coord), 1) if coord else PADRAO["eixo_coord_altura_px"],
        "pilar_modelo": "estilo_pilar.png" if recortes else None,
        "fonte": [Path(p).name for p in pdfs],
    }
    return perfil


if __name__ == "__main__":
    perfil = aprender(sys.argv[1:])
    ARQ.write_text(json.dumps(perfil, ensure_ascii=False, indent=2))
    print(json.dumps(perfil, ensure_ascii=False, indent=2))
