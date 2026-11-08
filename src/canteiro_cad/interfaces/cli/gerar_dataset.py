#!/usr/bin/env python3
"""Gera dados rotulados a partir de PDFs do CAD com camadas (engenharia reversa: o PDF é o gabarito).

Para cada prancha e cada resolução pedida:
  imagens/<nome>_<dpi>.png                imagem da prancha (o que o programa recebe como PNG)
  mascaras/<nome>_<dpi>/<camada>.png      só a tinta daquela camada do CAD (segmentação)
  rotulos/<nome>_<dpi>.txt                caixas no formato YOLO (classe cx cy w h, normalizados)
  anotacoes.json                          tudo: texto, camada, categoria, caixa em pixels
  classes.txt                             nomes das categorias (índice = linha)

Uso:
  python gerar_dataset.py prancha1.pdf prancha2.pdf ... --saida dataset --dpi 200 150 120 [--sem-mascaras]
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np

# camada do CAD -> categoria (vale para o padrão Eberick; camadas desconhecidas viram 'outro')
CATEGORIAS = [
    ("carimbo", r"^LC-TEXTOS$"),
    ("cota", r"COTAS|^TEXTOSARMADURAS$"),
    ("chamada_armadura", r"DESCRICAODAARMADURA"),
    ("tabela_aco", r"RELACAODOACO"),
    ("titulo", r"TITULO"),
    ("rotulo_viga", r"TEXTOSDASVIGAS"),
    ("rotulo_pilar", r"TEXTOSDOSPILARES"),
    ("rotulo_laje", r"TEXTOSDASLAJES"),
    ("eixo", r"EIXOS"),
    ("secao_pilar", r"SECAODOSPILARES|^FO-PILARES$"),
    ("hachura_pilar_morre", r"PILARQUEMORRE"),
    ("hachura_pilar_passa", r"PILARQUEPASSA"),
    ("viga", r"^FO-VIGAS$"),
    ("fundacao", r"SECAODASFUNDACOES"),
    ("nivel", r"NIVEIS|INDICACOES"),
    ("corte", r"^FO-CORTES$"),
    ("barra", r"BARRAS|ARMADURA|ESTRIBOS"),
    ("forma_detalhe", r"^DT-FORMA$|PONTILHADO"),
    ("texto_detalhe", r"^DT-TEXTOS$"),
]
NOMES = [c for c, _ in CATEGORIAS] + ["outro"]


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "", s.upper())


def categoria(camada: str | None, eh_texto: bool) -> str:
    n = _norm(camada)
    if eh_texto and n == "LC-TEXTOS":
        return "carimbo_ou_texto_locacao"
    for nome, padrao in CATEGORIAS:
        if re.search(padrao, n):
            return nome
    return "outro"


def gerar(pdfs: list[Path], saida: Path, dpis: list[int], mascaras: bool):
    import pymupdf as fitz

    for sub in ("imagens", "mascaras", "rotulos"):
        (saida / sub).mkdir(parents=True, exist_ok=True)
    nomes = NOMES + ["carimbo_ou_texto_locacao"]
    (saida / "classes.txt").write_text("\n".join(nomes) + "\n")
    anotacoes = {"classes": nomes, "imagens": []}

    for pdf in pdfs:
        doc = fitz.open(str(pdf))
        ocgs = doc.get_ocgs()
        if not ocgs:
            print(f"  {pdf.name}: sem camadas no PDF — ignorado")
            continue
        page = doc[0]
        trechos = page.get_texttrace()
        desenhos = page.get_drawings()
        for dpi in dpis:
            nome = f"{pdf.stem}_{dpi}"
            esc = dpi / 72
            m = page.rotation_matrix * fitz.Matrix(esc, esc)
            pix = page.get_pixmap(dpi=dpi)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(saida / "imagens" / f"{nome}.png"), img)
            H, W = img.shape[:2]

            objs = []
            for s in trechos:
                r = fitz.Rect(s["bbox"]) * m
                txt = "".join(chr(c[0]) for c in s["chars"]).strip()
                if txt:
                    objs.append(
                        {
                            "tipo": "texto",
                            "texto": txt,
                            "camada": s.get("layer"),
                            "categoria": categoria(s.get("layer"), True),
                            "bbox": [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)],
                        }
                    )
            for d in desenhos:
                r = fitz.Rect(d["rect"]) * m
                if r.width < 2 and r.height < 2:
                    continue
                objs.append(
                    {
                        "tipo": "vetor",
                        "camada": d.get("layer"),
                        "categoria": categoria(d.get("layer"), False),
                        "bbox": [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)],
                    }
                )
            # YOLO: textos + símbolos pequenos (seção de pilar etc.); linhas compridas ficam só nas máscaras
            linhas = []
            for o in objs:
                x0, y0, x1, y1 = o["bbox"]
                if o["tipo"] == "vetor" and (
                    max(x1 - x0, y1 - y0) > 0.05 * W or o["categoria"] in ("outro", "barra", "forma_detalhe")
                ):
                    continue
                c = nomes.index(o["categoria"])
                linhas.append(
                    f"{c} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} "
                    f"{max(x1 - x0, 1) / W:.6f} {max(y1 - y0, 1) / H:.6f}"
                )
            (saida / "rotulos" / f"{nome}.txt").write_text("\n".join(linhas) + "\n")

            if mascaras:
                pasta = saida / "mascaras" / nome
                pasta.mkdir(parents=True, exist_ok=True)
                # liga uma camada por vez (configuração de interface: 0 = ligar, 2 = desligar)
                cfgs = doc.layer_ui_configs()
                for alvo in cfgs:
                    for c in cfgs:
                        doc.set_layer_ui_config(c["number"], 0 if c["number"] == alvo["number"] else 2)
                    p = doc[0].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
                    g = np.frombuffer(p.samples, np.uint8).reshape(p.height, p.width)
                    if (g < 200).any():
                        nome_cam = re.sub(r"[^\w\-]+", "_", alvo["text"]).strip("_")
                        cv2.imwrite(str(pasta / f"{nome_cam}.png"), ((g < 200) * 255).astype(np.uint8))
                for c in cfgs:
                    doc.set_layer_ui_config(c["number"], 0)
            anotacoes["imagens"].append(
                {
                    "arquivo": f"imagens/{nome}.png",
                    "pdf": pdf.name,
                    "dpi": dpi,
                    "largura": W,
                    "altura": H,
                    "objetos": objs,
                }
            )
            print(
                f"  {nome}: {sum(o['tipo'] == 'texto' for o in objs)} textos, "
                f"{sum(o['tipo'] == 'vetor' for o in objs)} vetores, {len(linhas)} caixas YOLO"
            )
    (saida / "anotacoes.json").write_text(json.dumps(anotacoes, ensure_ascii=False))
    return anotacoes


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--saida", type=Path, default=Path("dataset"))
    ap.add_argument("--dpi", type=int, nargs="+", default=[200])
    ap.add_argument("--sem-mascaras", action="store_true")
    a = ap.parse_args()
    gerar(a.pdfs, a.saida, a.dpi, not a.sem_mascaras)
    print(f"Dataset em {a.saida.resolve()}")
