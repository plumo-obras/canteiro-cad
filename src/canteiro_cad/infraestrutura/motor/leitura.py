"""Leitura de uma prancha estrutural: PDF do CAD pelo texto e pelas camadas (exato) ou imagem pelo OCR.

É a entrada do motor: devolve o resultado bruto da prancha (carimbo, classificação, desenhos, tabelas, modelo 3D)
que o domínio transforma no contrato.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

from . import analisar, fonte_pdf, ocr


def _progresso(i, n):
    print(f"\r  OCR {i}/{n} blocos", end="", file=sys.stderr, flush=True)


def processar(caminho: Path, usar_cache: bool, tmp: Path, forcar_ocr: bool = False) -> dict:
    """PDF com texto -> leitura direta (exata). PDF escaneado ou imagem -> OCR."""
    if caminho.suffix.lower() == ".pdf":
        tokens, img, vetores = fonte_pdf.ler_pdf(caminho, com_vetores=True)
        if tokens is not None and not forcar_ocr:
            camadas = sorted({t["camada"] for t in tokens if t.get("camada")})
            print(f"  PDF vetorial: lendo o texto direto (sem OCR); {len(camadas)} camadas do CAD", file=sys.stderr)
            res = analisar.analisar(img, tokens, vetorial=True, vetores=vetores)
            res["camadas_cad"] = camadas
            res["arquivo"], res["fonte"] = caminho.name, "pdf-vetorial"
            return res
        print("  PDF sem texto (escaneado): usando OCR", file=sys.stderr)
        png = tmp / f"{caminho.stem}.png"
        cv2.imwrite(str(png), img)
        imagem = png
    else:
        imagem = caminho
    tokens, _ = ocr.ocr_com_cache(imagem, _progresso, usar_cache)
    print(file=sys.stderr)
    res = analisar.analisar(ocr.carregar_imagem(imagem), tokens)
    res["arquivo"], res["fonte"] = caminho.name, "ocr"
    return res
