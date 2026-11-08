"""OCR em blocos (tiles) para pranchas grandes (A1/A0) exportadas do AutoCAD/Eberick.

Retorna uma lista de tokens: {"text", "conf", "box": [x0, y0, x1, y1]} em pixels da imagem original.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

TILE = 1800       # tamanho do bloco em pixels
OVERLAP = 300     # sobreposição entre blocos (evita cortar textos)
MIN_LONG_SIDE = 7000  # imagens menores que isso são ampliadas (texto fica legível)

_engine = None
VERSAO = "4"  # muda quando o OCR muda (invalida o cache)


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def carregar_imagem(caminho: str | Path) -> np.ndarray:
    img = cv2.imread(str(caminho), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Não consegui abrir a imagem: {caminho}")
    return img


def _escala_para(img: np.ndarray) -> float:
    lado = max(img.shape[:2])
    return MIN_LONG_SIDE / lado if lado < MIN_LONG_SIDE else 1.0


def _tile_vazio(tile: np.ndarray) -> bool:
    cinza = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
    return (cinza < 128).mean() < 0.002  # quase todo branco


def _iou_menor(a, b) -> float:
    """Interseção dividida pela área do menor box."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area = lambda r: max(1e-6, (r[2] - r[0]) * (r[3] - r[1]))
    return inter / min(area(a), area(b))


def _deduplicar(tokens: list[dict]) -> list[dict]:
    # maiores primeiro: o texto inteiro vence o pedaço cortado na borda do tile
    tokens = sorted(tokens, key=lambda t: -((t["box"][2] - t["box"][0]) * (t["box"][3] - t["box"][1])))
    mantidos: list[dict] = []
    for t in tokens:
        if any(_iou_menor(t["box"], m["box"]) > 0.6 for m in mantidos):
            continue
        mantidos.append(t)
    mantidos.sort(key=lambda t: (t["box"][1], t["box"][0]))
    return mantidos


def _votar_orientacao(crop: np.ndarray, texto: str, conf: float) -> tuple[str, float]:
    """Relê o recorte nas duas orientações possíveis (0°/180° se horizontal, 90°/270° se vertical)
    e fica com a leitura de maior confiança. Corrige textos que o classificador de orientação
    vira por engano (ex.: 'P1=P2=P3' lido como '==0=6===9')."""
    if crop.size == 0:
        return texto, conf
    crop = cv2.copyMakeBorder(crop, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    h, w = crop.shape[:2]
    rots = (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE) if h > 1.5 * w else (None, cv2.ROTATE_180)
    melhor = (texto, conf)
    for rot in rots:
        img = crop if rot is None else cv2.rotate(crop, rot)
        res, _ = _get_engine()(img, use_det=False, use_cls=False)
        if res:
            t, c = res[0][0], float(res[0][1])
            if c > melhor[1] + 0.02:
                melhor = (t, c)
    return melhor


def ocr_imagem(img: np.ndarray, progresso=None) -> list[dict]:
    escala = _escala_para(img)
    if escala != 1.0:
        img = cv2.resize(img, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    H, W = img.shape[:2]
    passo = TILE - OVERLAP
    posicoes = [(x, y) for y in range(0, max(1, H - OVERLAP), passo) for x in range(0, max(1, W - OVERLAP), passo)]
    engine = _get_engine()
    tokens = []
    for i, (x, y) in enumerate(posicoes):
        tile = img[y:y + TILE, x:x + TILE]
        if progresso:
            progresso(i + 1, len(posicoes))
        if _tile_vazio(tile):
            continue
        res, _ = engine(tile)
        for quad, texto, conf in res or []:
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            if conf < 0.97:  # leitura duvidosa: confere a orientação
                texto, conf = _votar_orientacao(
                    tile[max(0, int(min(ys))):int(max(ys)) + 1, max(0, int(min(xs))):int(max(xs)) + 1], texto, conf)
            box = [(x + min(xs)) / escala, (y + min(ys)) / escala, (x + max(xs)) / escala, (y + max(ys)) / escala]
            tokens.append({"text": texto.strip(), "conf": round(float(conf), 3), "box": [round(v, 1) for v in box]})
    return _deduplicar([t for t in tokens if t["text"]])


def ocr_com_cache(caminho: str | Path, progresso=None, usar_cache=True) -> tuple[list[dict], tuple[int, int]]:
    caminho = Path(caminho)
    img = carregar_imagem(caminho)
    h = hashlib.sha1(caminho.read_bytes() + VERSAO.encode()).hexdigest()[:16]
    cache = caminho.with_name(f".{caminho.stem}.ocr-{h}.json")
    if usar_cache and cache.exists():
        dados = json.loads(cache.read_text())
        return dados["tokens"], tuple(dados["shape"])
    tokens = ocr_imagem(img, progresso)
    shape = img.shape[:2]
    cache.write_text(json.dumps({"tokens": tokens, "shape": shape}, ensure_ascii=False))
    return tokens, shape
