"""Recupera, no caminho por imagem (OCR), os rótulos e as coordenadas dos eixos da planta de locação.

O OCR da folha inteira perde caracteres isolados grandes (as letras/números dos eixos). Usando o padrão
aprendido dos PDFs (estilo.py): rótulos com letra ficam alinhados numa coluna e cada um na mesma altura da
sua coordenada; rótulos numerados ficam alinhados numa linha e cada um na mesma vertical da sua coordenada
(texto girado). As posições já lidas servem de âncora; o que falta é relido com um recorte isolado.
"""
from __future__ import annotations

import re
import statistics

import cv2
import numpy as np

from . import estilo


def _ler(img, x0, y0, x1, y1, padrao, giros=(None,), letra=False):
    from .ocr import _get_engine
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None, 0
    crop = cv2.copyMakeBorder(img[y0:y1, x0:x1], 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    melhor = (None, 0)
    for g in giros:
        c = crop if g is None else cv2.rotate(crop, g)
        res, _ = _get_engine()(c, use_det=False, use_cls=False)
        if res:
            txt, conf = res[0][0].strip().replace(",", "."), float(res[0][1])
            txt = re.sub(r"[^A-Za-z0-9.]", "", txt).strip(".")  # tira traço da linha do eixo, pontos soltos
            if letra:
                txt = txt.upper().translate(str.maketrans({"1": "I", "0": "O", "|": "I", "L": "L"}))
            if re.fullmatch(padrao, txt) and conf > melhor[1]:
                melhor = (txt, conf)
    return melhor


def _manchas_na_faixa(bin_img, x0, y0, x1, y1, alt, eixo):
    """posições (centro no 'eixo' da faixa) de manchas de tinta com tamanho de rótulo"""
    H, W = bin_img.shape
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1))
    if x1 <= x0 or y1 <= y0:
        return []
    n, _, st, _ = cv2.connectedComponentsWithStats(bin_img[y0:y1, x0:x1])
    out = []
    for x, y, w, h, a in st[1:]:
        if 0.55 * alt <= h <= 1.4 * alt and w <= 1.2 * alt:
            out.append((y0 + y + h / 2) if eixo == "y" else (x0 + x + w / 2))
    return out


def _agrupa(vals, tol):
    grupos = []
    for v in sorted(vals, key=lambda p: p[0]):
        if grupos and v[0] - grupos[-1][-1][0] <= tol:
            grupos[-1].append(v)
        else:
            grupos.append([v])
    return grupos


def recuperar_eixos(img, toks: list[dict], f: float) -> list[dict]:
    """Recebe tokens brutos (coordenadas em pixels da imagem) e devolve tokens novos para acrescentar."""
    perfil = estilo.carregar()
    k = img.shape[1] / 9362.0  # tamanho relativo à folha de referência
    alt = perfil["eixo_rotulo_altura_px"] * k
    bin_img = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 160).astype(np.uint8)
    box = lambda t: t["box"]
    cx = lambda t: (t["box"][0] + t["box"][2]) / 2
    cy = lambda t: (t["box"][1] + t["box"][3]) / 2
    novos = []

    def ja_tem(x, y):
        return any(abs(cx(t) - x) < 0.8 * alt and abs(cy(t) - y) < 0.8 * alt for t in toks + novos)

    letras = [t for t in toks if re.fullmatch(r"[A-Z]", t["text"].strip()) and box(t)[3] - box(t)[1] > 0.7 * alt]
    digitos = [t for t in toks if re.fullmatch(r"\d", t["text"].strip()) and box(t)[3] - box(t)[1] > 0.7 * alt]
    coords = [t for t in toks if re.fullmatch(r"\d+[.,]\d\d", t["text"].strip())]
    coord_h = [t for t in coords if box(t)[2] - box(t)[0] > box(t)[3] - box(t)[1]]  # horizontais (eixos com letra)
    coord_v = [t for t in coords if box(t)[3] - box(t)[1] > box(t)[2] - box(t)[0]]  # giradas (eixos numerados)

    # ---- eixos com letra: coluna de letras + coluna de coordenadas na mesma altura
    col_l = max(_agrupa([(box(t)[0], t) for t in letras], alt), key=len, default=[])
    col_c = max(_agrupa([(box(t)[0], t) for t in coord_h], alt), key=len, default=[])
    if len(col_l) < 2 and len(col_c) >= 3:
        # sem letras lidas: o rótulo fica na ponta esquerda da linha do eixo, na altura da coordenada
        xa = min(box(t)[0] for _, t in col_c)
        achadas = []
        for _, c in col_c:
            y = cy(c)
            n, _, st, _ = cv2.connectedComponentsWithStats(bin_img[int(y - 0.7 * alt):int(y + 0.7 * alt), 0:int(xa - 10 * alt)])
            cand = [(x, w) for x, yy, w, hh, a in st[1:] if 0.55 * alt <= hh <= 1.4 * alt and w <= 1.2 * alt]
            if cand:
                x, w = min(cand)
                txt, conf = _ler(img, x - 0.3 * alt, y - 0.75 * alt, x + w + 0.1 * alt, y + 0.75 * alt, r"[A-Z]", letra=True)
                if txt:
                    achadas.append({"text": txt, "conf": conf, "box": [x, y - alt / 2, x + w, y + alt / 2], "recuperado": True})
        if len(achadas) >= 2:
            xs0 = statistics.median(a["box"][0] for a in achadas)
            achadas = [a for a in achadas if abs(a["box"][0] - xs0) < 1.5 * alt]
            novos.extend(achadas)
            letras = letras + achadas
            col_l = max(_agrupa([(box(t)[0], t) for t in letras], alt), key=len, default=[])
    if len(col_l) >= 2 or (col_l and len(col_c) >= 3):
        lx0 = statistics.median(box(t)[0] for _, t in col_l)
        lx1 = statistics.median(box(t)[2] for _, t in col_l)
        ys = [cy(t) for _, t in col_c] + [cy(t) for _, t in col_l]
        topo, base = min(ys) - 3 * alt, max(ys) + 3 * alt
        ys += _manchas_na_faixa(bin_img, lx0 - 0.3 * alt, topo, lx1 + 0.3 * alt, base, alt, "y")
        for y in sorted(set(round(v) for v in ys)):
            if ja_tem((lx0 + lx1) / 2, y):
                continue
            txt, conf = _ler(img, lx0 - 0.3 * alt, y - 0.75 * alt, lx1 + 0.1 * alt, y + 0.75 * alt, r"[A-Z]", letra=True)
            if txt:
                novos.append({"text": txt, "conf": conf, "box": [lx0, y - alt / 2, lx1, y + alt / 2], "recuperado": True})
        coluna = [t for t in letras + novos if abs(box(t)[0] - lx0) < alt and re.fullmatch(r"[A-Z]", t["text"])]
        _corrige_sequencia(coluna, cy, letras=True)
        for _, c in col_c:  # eixo existe (tem coordenada) mas o rótulo não foi lido: deduz pela ordem
            y = cy(c)
            if any(abs(cy(t) - y) < 0.6 * alt for t in coluna):
                continue
            acima = max((t for t in coluna if cy(t) < y), key=cy, default=None)
            abaixo = min((t for t in coluna if cy(t) > y), key=cy, default=None)
            if acima and abaixo and ord(abaixo["text"]) - ord(acima["text"]) == 2:
                novo = {"text": chr(ord(acima["text"]) + 1), "conf": 0.5, "box": [lx0, y - alt / 2, lx1, y + alt / 2],
                        "recuperado": True, "inferido_pela_sequencia": True}
                novos.append(novo)
                coluna.append(novo)
        # coordenadas que faltam, na altura de cada letra
        if col_c:
            cx0 = statistics.median(box(t)[0] for _, t in col_c)
            cx1 = max(box(t)[2] for _, t in col_c)
            for t in [t for t in letras + novos if abs(box(t)[0] - lx0) < alt]:
                y = cy(t)
                if any(abs(cy(c) - y) < 0.6 * alt for c in coord_h):
                    continue
                txt, conf = _ler(img, cx0 - 0.3 * alt, y - 0.8 * alt, cx1 + 0.5 * alt, y + 0.8 * alt, r"\d+\.\d\d")
                if txt:
                    novos.append({"text": txt, "conf": conf, "box": [cx0, y - alt / 2, cx1, y + alt / 2], "recuperado": True})

    # ---- eixos numerados: linha de dígitos + coordenadas giradas na mesma vertical
    lin_c = max(_agrupa([(box(t)[3], t) for t in coord_v], 2 * alt), key=len, default=[])
    digitos = [t for t in toks if re.fullmatch(r"\d", t["text"].strip()) and box(t)[3] - box(t)[1] > 0.55 * alt]
    if len(lin_c) >= 2:  # rótulos numerados ficam abaixo das coordenadas giradas, na mesma faixa horizontal
        xa = min(box(t)[0] for _, t in lin_c) - 12 * alt
        xb = max(box(t)[2] for _, t in lin_c) + 12 * alt
        ya = statistics.median(box(t)[3] for _, t in lin_c)
        digitos = [t for t in digitos if box(t)[1] > ya and xa < cx(t) < xb]
    lin_d = max(_agrupa([(box(t)[1], t) for t in digitos], alt), key=len, default=[])
    if len(lin_d) >= 2 or (lin_d and len(lin_c) >= 3):
        dy0 = statistics.median(box(t)[1] for _, t in lin_d)
        dy1 = statistics.median(box(t)[3] for _, t in lin_d)
        xs = [cx(t) for _, t in lin_c] + [cx(t) for _, t in lin_d]
        esq, dir_ = min(xs) - 12 * alt, max(xs) + 12 * alt
        xs += _manchas_na_faixa(bin_img, esq, dy0 - 0.05 * alt, dir_, dy1 + 0.3 * alt, alt, "x")
        for x in sorted(set(round(v) for v in xs)):
            if ja_tem(x, (dy0 + dy1) / 2):
                continue
            txt, conf = _ler(img, x - 0.6 * alt, dy0 - 0.1 * alt, x + 0.6 * alt, dy1 + 0.3 * alt, r"\d")
            if txt:
                novos.append({"text": txt, "conf": conf, "box": [x - alt / 3, dy0, x + alt / 3, dy1], "recuperado": True})
        _corrige_sequencia([t for t in digitos + novos if abs(box(t)[1] - dy0) < alt and re.fullmatch(r"\d", t["text"])],
                           cx, letras=False)
        if lin_c:
            cy0 = min(box(t)[1] for _, t in lin_c)
            cy1 = statistics.median(box(t)[3] for _, t in lin_c)
            giros = (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE)
            for t in [t for t in digitos + novos if abs(box(t)[1] - dy0) < alt and re.fullmatch(r"\d", t["text"])]:
                x = cx(t)
                if any(abs(cx(c) - x) < 0.6 * alt for c in coord_v):
                    continue
                txt, conf = _ler(img, x - 0.8 * alt, cy0 - 0.5 * alt, x + 0.8 * alt, cy1 + 0.5 * alt, r"\d+\.\d\d", giros)
                if txt:
                    novos.append({"text": txt, "conf": conf, "box": [x - alt / 2, cy0, x + alt / 2, cy1], "recuperado": True})
    return novos


def _corrige_sequencia(rotulos, pos, letras: bool):
    """Eixos vêm em sequência (A, B, C... ou 1, 2, 3...). Um rótulo fora da sequência, entre dois vizinhos
    que a confirmam, é corrigido (ex.: 'H', '?', 'J' -> 'I')."""
    rot = sorted(rotulos, key=pos)
    val = lambda t: (ord(t["text"]) - ord("A")) if letras else int(t["text"])
    for i in range(1, len(rot) - 1):
        a, b, c = rot[i - 1], rot[i], rot[i + 1]
        try:
            va, vb, vc = val(a), val(b), val(c)
        except (TypeError, ValueError):
            continue
        if vc - va == 2 and vb != va + 1:
            b["text"] = chr(ord("A") + va + 1) if letras else str(va + 1)
            b["corrigido_pela_sequencia"] = True


def retangulos_pilares(img) -> list[dict]:
    """Acha os símbolos de pilar (retângulo hachurado) por correlação com o modelo aprendido do PDF.
    Devolve no formato dos vetores do PDF (camada 'LC-Seção dos pilares') para reaproveitar a geometria."""
    from pathlib import Path
    perfil = estilo.carregar()
    if not perfil.get("pilar_modelo"):
        return []
    arq = Path(estilo.__file__).with_name(perfil["pilar_modelo"])
    modelo = cv2.imread(str(arq), cv2.IMREAD_GRAYSCALE)
    if modelo is None:
        return []
    k = img.shape[1] / 9362.0
    if abs(k - 1) > 0.02:
        modelo = cv2.resize(modelo, None, fx=k, fy=k)
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    achados = []
    for m in (modelo, cv2.rotate(modelo, cv2.ROTATE_90_COUNTERCLOCKWISE)):
        res = cv2.matchTemplate(cinza, m, cv2.TM_CCOEFF_NORMED)
        pico = (res == cv2.dilate(res, np.ones((15, 15), np.uint8))) & (res >= 0.75)  # só máximos locais fortes
        ys, xs = np.where(pico)
        for y, x in sorted(zip(ys, xs), key=lambda p: -res[p[0], p[1]]):
            h, w = m.shape
            if any(abs(x - a[0]) < w * 0.7 and abs(y - a[1]) < h * 0.7 for a in achados):
                continue
            achados.append((int(x), int(y), w, h, float(res[y, x])))
    return [{"camada": "LC-Seção dos pilares", "box": [x + 2 * k, y + 2 * k, x + w - 3 * k, y + h - 3 * k],
             "tipos": "qu", "espessura": 0, "preenchido": False, "conf": round(c, 3)} for x, y, w, h, c in achados]
