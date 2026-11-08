"""Monta um modelo 3D do esqueleto estrutural (cm) a partir do que foi lido na prancha.

- pilares: posição/seção da locação; topo = nível da forma mais alta em que o pilar aparece
  ("morre" = termina naquele nível); base = topo da sapata (-df + h1)
- sapatas: base em -df, altura h1; a dimensão em planta não está nas folhas de forma -> estimada (marcada)
- vigas (só PDF com camadas): traçado da camada FO-Vigas, levado para cm por uma calibração
  forma -> locação feita com os pilares que aparecem nas duas; altura = seção da forma
- lajes: região fechada pelas vigas em volta do rótulo da laje; espessura da tabela de lajes
"""
from __future__ import annotations

import re
import statistics

import cv2
import numpy as np


def _nivel(titulo):
    m = re.search(r"N\S*VEL\s*(-?\d+)", titulo or "", re.I)
    return int(m.group(1)) if m else None


def _calibra(pilares_forma, retangulos, centros_loc, h):
    """pares (centro do pilar na forma em px, centro na locação em cm) -> ajuste linear x e y"""
    pares, usados = [], set()
    for p in pilares_forma:
        if p["elemento"] not in centros_loc or not p.get("_px"):
            continue
        lx, ly = p["_px"]
        cands = [(abs((r[0] + r[2]) / 2 - lx) + abs((r[1] + r[3]) / 2 - ly), i) for i, r in enumerate(retangulos) if i not in usados]
        if not cands:
            continue
        d, i = min(cands)
        if d > 8 * h:
            continue
        usados.add(i)
        r = retangulos[i]
        pares.append((((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), centros_loc[p["elemento"]]))
    if len(pares) < 4:
        return None
    ax = np.polyfit([p[0][0] for p in pares], [p[1][0] for p in pares], 1)
    ay = np.polyfit([p[0][1] for p in pares], [p[1][1] for p in pares], 1)
    res = [abs(np.polyval(ax, p[0][0]) - p[1][0]) + abs(np.polyval(ay, p[0][1]) - p[1][1]) for p in pares]
    px_box = (min(p[0][0] for p in pares), min(p[0][1] for p in pares), max(p[0][0] for p in pares), max(p[0][1] for p in pares))
    return {"ax": ax, "ay": ay, "erro_cm": float(statistics.median(res)), "pares": len(pares), "px_box": px_box}


def _vigas_de_segmentos(segs, largura, altura, z_topo):
    """Pares de linhas paralelas afastadas ~largura da viga -> caixas de viga."""
    hor = [(min(x0, x1), max(x0, x1), (y0 + y1) / 2) for x0, y0, x1, y1 in segs if abs(y1 - y0) < 1 and abs(x1 - x0) > 5]
    ver = [(min(y0, y1), max(y0, y1), (x0 + x1) / 2) for x0, y0, x1, y1 in segs if abs(x1 - x0) < 1 and abs(y1 - y0) > 5]
    caixas = set()
    for grupo, horizontal in ((hor, True), (ver, False)):
        grupo = sorted(grupo, key=lambda s: s[2])
        for i, a in enumerate(grupo):
            for b in grupo[i + 1:]:
                d = b[2] - a[2]
                if d > largura * 1.6:
                    break
                if d < largura * 0.6:
                    continue
                ini, fim = max(a[0], b[0]), min(a[1], b[1])
                if fim - ini < 10:
                    continue
                meio = (a[2] + b[2]) / 2
                if horizontal:
                    caixas.add((round((ini + fim) / 2, 1), round(meio, 1), round(fim - ini, 1), round(d, 1)))
                else:
                    caixas.add((round(meio, 1), round((ini + fim) / 2, 1), round(d, 1), round(fim - ini, 1)))
    return [{"x": c[0], "y": c[1], "dx": c[2], "dy": c[3], "z0": z_topo - altura, "z1": z_topo} for c in sorted(caixas)]


def _lajes(segs, rotulos_cm, caixa, espessura, z_topo, pilares=(), res=2.0):
    """Região fechada pelas vigas em volta de cada rótulo de laje -> polígono em cm."""
    x0, y0, x1, y1 = caixa
    W, H = int((x1 - x0) / res) + 3, int((y1 - y0) / res) + 3
    grade = np.zeros((H + 2, W + 2), np.uint8)
    for a, b, c, d in segs:
        cv2.line(grade, (int((a - x0) / res) + 1, int((y1 - b) / res) + 1), (int((c - x0) / res) + 1, int((y1 - d) / res) + 1), 255, 3)
    for p in pilares:  # as linhas das vigas param nos pilares: o pilar fecha o contorno
        cv2.rectangle(grade, (int((p["x"] - p["dx"] / 2 - x0) / res), int((y1 - p["y"] - p["dy"] / 2) / res)),
                      (int((p["x"] + p["dx"] / 2 - x0) / res) + 2, int((y1 - p["y"] + p["dy"] / 2) / res) + 2), 255, -1)
    out = []
    for nome, (lx, ly) in rotulos_cm.items():
        px, py = int((lx - x0) / res) + 1, int((y1 - ly) / res) + 1
        if not (0 < px < W and 0 < py < H) or grade[py, px]:
            continue
        g = grade.copy()
        mask = np.zeros((H + 4, W + 4), np.uint8)
        cv2.floodFill(g, mask, (px, py), 128)
        reg = (g == 128).astype(np.uint8)
        ys, xs = np.where(reg)
        if not len(xs) or xs.min() <= 1 or ys.min() <= 1 or xs.max() >= W or ys.max() >= H:
            continue  # vazou para fora: região não fechada
        cont, _ = cv2.findContours(reg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cont, key=cv2.contourArea)
        c = cv2.approxPolyDP(c, 2, True)
        pol = [[round(x0 + (p[0][0] - 1) * res, 1), round(y1 - (p[0][1] - 1) * res, 1)] for p in c]
        area = cv2.contourArea(c) * res * res / 1e4
        out.append({"elemento": nome, "poligono": pol, "area_m2": round(area, 2), "z0": z_topo - espessura, "z1": z_topo})
    return out


def montar(desenhos: list[dict], tabelas_gerais: list[dict], vetores: list[dict], h: float) -> dict | None:
    loc = next((d for d in desenhos if d["tipo"] == "locacao"), None)
    if not loc:
        return None
    pil_loc = [p for p in loc["dados"]["pilares"] if p.get("centro_cm") or (p.get("x_cm") is not None and p.get("y_cm") is not None)]
    if not pil_loc:
        return None
    centro = {p["elemento"]: ((p.get("centro_cm") or {}).get("x", p.get("x_cm")), (p.get("centro_cm") or {}).get("y", p.get("y_cm")))
              for p in pil_loc}
    formas = [d for d in desenhos if d["tipo"] == "forma"]
    niveis = sorted({_nivel(f["titulo"]) for f in formas if _nivel(f["titulo"]) is not None}) or [0]
    for d in desenhos:
        if d["tipo"] == "corte":
            niveis = sorted(set(niveis) | {n["cota_cm"] for n in d["dados"].get("niveis", []) if isinstance(n["cota_cm"], (int, float))})
    # espessura das lajes (tabela 'Lajes': coluna Altura)
    esp = 13
    for tg in tabelas_gerais:
        if tg["titulo"] == "Lajes":
            alts = [int(l[2]) for l in tg["linhas"] if len(l) > 2 and re.fullmatch(r"L\d+", l[0]) and l[2].isdigit()]
            if alts:
                esp = statistics.median(alts)

    xs = [c[0] for c in centro.values()]
    ys = [c[1] for c in centro.values()]
    caixa = (min(xs) - 150, min(ys) - 150, max(xs) + 150, max(ys) + 150)
    modelo = {"unidade": "cm", "niveis": niveis, "pilares": [], "sapatas": [], "vigas": [], "lajes": [], "formas": [],
              "caixa": caixa, "avisos": []}

    # topo de cada pilar: maior nível de forma em que ele aparece; 'morre' termina ali
    topo = {}
    for f in formas:
        nv = _nivel(f["titulo"])
        if nv is None:
            continue
        for p in f["dados"]["pilares"]:
            topo[p["elemento"]] = max(topo.get(p["elemento"], nv), nv)
    for p in pil_loc:
        cx, cy = centro[p["elemento"]]
        dx, dy = (p.get("dim_cm") or {}).get("x"), (p.get("dim_cm") or {}).get("y")
        if not dx:
            a, b = (sorted(float(v) for v in p["secao_cm"].split("x")) if p.get("secao_cm") else (15, 30))
            dx, dy = a, b
        s = p.get("sapata") or {}
        df, h1 = s.get("df_cm") or 150, s.get("h1_cm") or 35
        base_pilar = -df + h1
        modelo["pilares"].append({"elemento": p["elemento"], "x": cx, "y": cy, "dx": dx, "dy": dy, "z0": base_pilar,
                                  "z1": topo.get(p["elemento"], max(niveis)), "secao_cm": p.get("secao_cm"),
                                  "morre": topo.get(p["elemento"], max(niveis)) < max(niveis)})
        lado = round(2.2 * max(dx, dy), 0)
        modelo["sapatas"].append({"elemento": p["elemento"], "x": cx, "y": cy, "dx": lado, "dy": lado, "z0": -df, "z1": -df + h1,
                                  "h0_cm": s.get("h0_cm"), "estimada": True})
    modelo["avisos"].append("Dimensão das sapatas em planta não consta nas folhas de forma: desenhadas com tamanho estimado.")

    # vigas e lajes pelo traçado da forma (PDF com camadas)
    retang = [v["box"] for v in vetores if v.get("camada") == "FO-Pilares" and (v["box"][2] - v["box"][0]) < 8 * h]
    seg_vigas = [(s_, v) for v in vetores if v.get("camada") == "FO-Vigas" for s_ in v.get("segs", [])]
    if not seg_vigas:
        modelo["avisos"].append("Traçado das vigas indisponível (só em PDF com camadas): vigas e lajes não desenhadas.")
    for f in formas:
        nv = _nivel(f["titulo"])
        cal = _calibra(f["dados"]["pilares"], retang, centro, h)
        if nv is None or not cal or cal["erro_cm"] > 5 or not seg_vigas:
            if seg_vigas:
                modelo["avisos"].append(f"{f['titulo']}: não foi possível calibrar a forma com a locação.")
            continue
        bx = cal["px_box"]
        mx, my = 0.15 * (bx[2] - bx[0]) + 30, 0.15 * (bx[3] - bx[1]) + 30
        para_cm = lambda x, y: (float(np.polyval(cal["ax"], x)), float(np.polyval(cal["ay"], y)))
        segs = []
        for (x0, y0, x1, y1), _ in seg_vigas:
            if bx[0] - mx <= (x0 + x1) / 2 <= bx[2] + mx and bx[1] - my <= (y0 + y1) / 2 <= bx[3] + my:
                a, b = para_cm(x0, y0)
                c, d = para_cm(x1, y1)
                segs.append([round(a, 1), round(b, 1), round(c, 1), round(d, 1)])
        secs = [v["secao_cm"] for v in f["dados"]["vigas"] if v.get("secao_cm")]
        larg, alt = (sorted(int(x) for x in statistics.mode(secs).split("x")) if secs else (15, 30))
        vigas = _vigas_de_segmentos(segs, larg, alt, nv)
        for v in vigas:
            v["nivel"] = nv
        modelo["vigas"] += vigas
        rot = {l["elemento"]: para_cm(*l["_px"]) for l in f["dados"]["lajes"] if l.get("_px")}
        if rot:
            presentes = {p["elemento"] for p in f["dados"]["pilares"]}
            modelo["lajes"] += _lajes(segs, rot, caixa, esp, nv, [p for p in modelo["pilares"] if p["elemento"] in presentes])
        modelo["formas"].append({"titulo": f["titulo"], "nivel": nv, "calibracao_erro_cm": round(cal["erro_cm"], 2),
                                 "pilares_usados": cal["pares"], "segmentos": len(segs), "vigas": len(vigas)})
    return modelo
