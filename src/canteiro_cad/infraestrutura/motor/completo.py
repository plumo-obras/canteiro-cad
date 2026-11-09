"""Extração completa: tudo o que está escrito na prancha entra no resultado.

Cada texto termina em um destes lugares:
  - um campo estruturado (carimbo, tabela de aço, tabela geral, elemento, eixo, barra...);
  - a lista "textos" do desenho/região a que pertence (cotas e anotações soltas);
  - "sem_regiao" (último recurso, com posição).
A cobertura (textos no resultado / textos na prancha) é medida e informada.
"""
from __future__ import annotations

import math
import re
import statistics

import cv2
import numpy as np

from .analisar import RE_SECAO, Tok, _agrupar_linhas, num, texto_pos

VETORES: list[dict] = []  # vetores do PDF com camada (preenchido por analisar.analisar)


def _cam(v):
    from .analisar import norm
    return norm(v.get("camada") or "")


RE_ESCALA = re.compile(r"E?SC(ALA)?[1IT]?:?\d+|ESCALA1:\d+")


def _h_ref(toks):
    alt = [t.h for t in toks if re.fullmatch(r"\d+(\.\d+)?", t.n) and t.h < 2 * t.w] if toks else []
    return statistics.median(alt) if alt else 26


Tok.w = property(lambda s: s.x1 - s.x0)


def _dentro(t, r, m=0):
    return r[0] - m <= t.cx <= r[2] + m and r[1] - m <= t.cy <= r[3] + m


# ----------------------------------------------------------------------------- carimbo

def regiao_carimbo(toks, f):
    ancora = next((t for t in toks if t.n.startswith("CLIENTE")), None)
    if not ancora:
        return None
    topo = min([t.y0 for t in toks if "CALCULOESTRUTURAL" in t.n and abs(t.cy - ancora.cy) < 200] or [ancora.y0 - 80])
    return (ancora.x0 - 80, topo - 20, 1e9, 1e9)


# ----------------------------------------------------------------------------- tabelas gerais

TITULOS_TABELA = {
    "VIGAS": "Vigas", "PILARES": "Pilares", "LAJES": "Lajes", "SAPATAS": "Sapatas",
    "CARACTERISTICASDOSMATERIAIS": "Características dos materiais",
    "BLOCOSDEENCHIMENTO": "Blocos de enchimento",
    "LEGENDADOSPILARES": "Legenda dos pilares",
    "LEGENDADASVIGASEPAREDES": "Legenda das vigas e paredes",
}


def grades_de_tabela(img, f, h):
    """Contornos de tabelas: componentes formados por linhas horizontais E verticais (bordas da tabela)."""
    esc = 0.5
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
    b = (g < 200).astype("uint8")
    comp = max(8, int(2 * h / f * esc))
    hor = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (comp, 1)))
    ver = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, comp)))
    grade = cv2.dilate(hor | ver, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    n, _, st, _ = cv2.connectedComponentsWithStats(grade)
    k = f / esc
    return [(x * k, y * k, (x + w) * k, (y + hh) * k) for x, y, w, hh, _ in st[1:] if w > 4 and hh > 4]


def tabelas_gerais(toks, uso, h, img=None, f=1.0):
    """Tabelas com título conhecido (Vigas, Pilares, Lajes, Materiais, Blocos, Legendas): linhas e células.
    O contorno vem da grade de linhas da tabela; sem grade, cresce pelas linhas de texto coladas."""
    out = []
    grades = grades_de_tabela(img, f, h) if img is not None else []
    livres = lambda: [t for t in toks if id(t) not in uso]
    for tit in [t for t in toks if t.n in TITULOS_TABELA]:
        if id(tit) in uso:
            continue
        # grade logo abaixo do título (ou que contém o título), que cubra o centro do título na horizontal
        cand = [g for g in grades if g[0] - h <= tit.cx <= g[2] + h and -3 * h < g[1] - tit.y1 < 2 * h
                and (g[2] - g[0]) > 3 * h and (g[3] - g[1]) > 1.5 * h]
        if cand:
            g = min(cand, key=lambda g: abs(g[1] - tit.y1))
            corpo = [t for t in livres() if t is not tit and _dentro(t, g)]
        else:
            cab = [t for t in livres() if 0 < t.cy - tit.cy < 3 * h and abs(t.cx - tit.cx) < 18 * h and t is not tit]
            if not cab:
                continue
            x0 = min(t.x0 for t in cab + [tit]) - h
            x1 = max(t.x1 for t in cab + [tit]) + h
            y_ult = max(t.cy for t in cab)
            corpo = list(cab)
            while True:
                prox = [t for t in livres() if t not in corpo and x0 - h < t.cx < x1 + h and 0 < t.cy - y_ult < 2.6 * h]
                if not prox:
                    break
                corpo += prox
                y_ult = max(t.cy for t in prox)
        if not corpo:
            continue
        linhas = [[t.text for t in l] for l in _agrupar_linhas(corpo, 0.45 * h)]
        rot = f"tabela {TITULOS_TABELA[tit.n]} #{len(out)}"
        uso[id(tit)] = rot
        for t in corpo:
            uso[id(t)] = rot
        pos = texto_pos(tit)
        out.append({"titulo": TITULOS_TABELA[tit.n], "linhas": linhas, "x_mm": pos["x_mm"], "y_mm": pos["y_mm"]})
    # notas soltas típicas logo abaixo das tabelas
    for t in livres():
        if t.n.startswith("DIMENSAOMAXIMADOAGREGADO"):
            m = re.search(r"=\s*([\d.,]+)\s*mm", t.text, re.I)
            out.append({"titulo": "Nota", "linhas": [[t.text]], "agregado_max_mm": num(m.group(1)) if m else None,
                        "x_mm": texto_pos(t)["x_mm"], "y_mm": texto_pos(t)["y_mm"]})
            uso[id(t)] = f"nota #{len(out)}"
    return out


def materiais(tabs):
    """Interpreta 'Características dos materiais' (fck/Ecs por elemento) e 'Blocos de enchimento'."""
    mat, blocos = [], []
    for tb in tabs:
        if tb["titulo"] == "Características dos materiais":
            for l in tb["linhas"]:
                nums = [num(x) for x in l if num(x) is not None]
                nome = next((x for x in l if num(x) is None and not x.startswith("(")), None)
                if len(nums) >= 2 and (nome is None or nome.lower() not in ("elemento", "fck", "ecs")):
                    mat.append({"elemento": nome or "Geral", "fck_kgf_cm2": nums[0], "ecs_kgf_cm2": nums[1]})
        if tb["titulo"] == "Blocos de enchimento":
            det = next((num(l[0]) for l in tb["linhas"] if len(l) == 1 and num(l[0]) is not None), None)
            for l in tb["linhas"]:
                nums = [num(x) for x in l if num(x) is not None]
                txt = " ".join(x for x in l if num(x) is None)
                m = re.search(r"([A-Z]\d+/\d+/\d+)", txt)
                if m and len(nums) >= 4:
                    blocos.append({"detalhe": nums[0] if len(nums) >= 5 else det, "descricao": txt.strip(),
                                   "nome": m.group(1), "hb_cm": nums[-4], "bx_cm": nums[-3], "by_cm": nums[-2],
                                   "quantidade": nums[-1]})
    return mat, blocos


# ----------------------------------------------------------------------------- regiões dos desenhos

def _tipo_titulo(n):
    if "LOCAC" in n:
        return "locacao"
    if "FORMADOPAVIMENTO" in n or n.startswith("FORMA"):
        return "forma"
    if re.fullmatch(r"CORTE[A-Z0-9]+-[A-Z0-9]+", n):
        return "corte"
    if "ARMACAO" in n and "LAJE" in n:
        return "armacao_lajes"
    if "VIGOTA" in n:
        return "vigotas"
    return "desenho"


class Mapa:
    """Folha 'comprimida': tinta binarizada (sem moldura e sem as áreas já lidas, como tabelas e carimbo),
    faixas horizontais separadas por brancos e manchas conexas."""

    def __init__(self, img, f, apagar: list[tuple], h, alvo=2400):
        self.k = f / (alvo / max(img.shape[:2]))  # px reduzido -> coordenada normalizada
        esc = alvo / max(img.shape[:2])
        # binariza na resolução cheia e reduz por "máximo": qualquer traço, mesmo fino, sobrevive à compressão
        cheia = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 200).astype("uint8") * 255
        tinta = (cv2.resize(cheia, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA) > 0).astype("uint8")
        H, W = tinta.shape
        for kern in ((int(W * 0.6), 1), (1, int(H * 0.6))):  # moldura
            longas = cv2.morphologyEx(tinta, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, kern))
            tinta[longas > 0] = 0
        for r in apagar:
            x0, y0, x1, y1 = (int(max(0, v / self.k)) for v in r)
            tinta[y0:y1 + 1, x0:x1 + 1] = 0
        # faixas: linhas da folha sem tinta, com altura >= 3 textos
        vazio = tinta.sum(axis=1) == 0
        lim = max(3, int(3 * h / self.k))
        cortes, ini = [], None
        for y, v in enumerate(list(vazio) + [False]):
            if v and ini is None:
                ini = y
            elif not v and ini is not None:
                if y - ini >= lim:
                    cortes.append((ini + y) / 2 * self.k)
                ini = None
        self.cortes = cortes
        dil = cv2.dilate(tinta, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
        n, self.rot, stats, _ = cv2.connectedComponentsWithStats(dil)
        self.caixas = {i: (stats[i][0] * self.k, stats[i][1] * self.k, (stats[i][0] + stats[i][2]) * self.k,
                           (stats[i][1] + stats[i][3]) * self.k) for i in range(1, n)}

    def faixa(self, y):
        return sum(1 for c in self.cortes if y > c)

    def mancha(self, t):
        x, y = int(t.cx / self.k), int(t.cy / self.k)
        H, W = self.rot.shape
        for r in (0, 2, 5):
            jan = self.rot[max(0, y - r):min(H, y + r + 1), max(0, x - r):min(W, x + r + 1)]
            v = jan[jan > 0]
            if v.size:
                return int(statistics.mode(v.tolist()))
        return 0


def areas_lidas(toks, uso, h):
    """Retângulos das áreas já lidas (carimbo, tabelas), para apagar do mapa."""
    grupos = {}
    for t in toks:
        u = uso.get(id(t))
        if u and (u.startswith("tabela") or u == "carimbo" or u.startswith("nota")):
            g = grupos.setdefault(u, [1e9, 1e9, -1e9, -1e9])
            g[:] = [min(g[0], t.x0), min(g[1], t.y0), max(g[2], t.x1), max(g[3], t.y1)]
    return [(g[0] - h, g[1] - h, g[2] + h, g[3] + h) for g in grupos.values()]


def regioes_desenhos(img, f, toks, uso, h, mapa: Mapa, faixas_detalhe: set = frozenset()):
    """Desenhos com título por extenso + 'Escala 1:xx' logo abaixo (formas, locação, cortes, lajes...).
    Cada mancha de tinta vai para o título mais próximo abaixo dela, na mesma faixa da folha."""
    escalas = [t for t in toks if RE_ESCALA.match(t.n)]
    titulos = []
    for t in toks:
        if id(t) in uso or t.n.startswith("SECAO") or RE_ESCALA.match(t.n):
            continue
        if len(t.n) < 9 and not re.fullmatch(r"CORTE[A-Z0-9]+-[A-Z0-9]+", t.n):
            continue
        # título de desenho tem palavra de verdade (não é lista de elementos nem chamada de barra)
        if not re.search(r"[A-Z]{5,}", t.n) or "C=" in t.n or re.fullmatch(r"=?[PSVL]\d+(=[PSVL]\d+)*=?", t.n):
            continue
        # PDF com camadas: título de desenho grande não fica em camada de detalhamento/armadura
        if t.camada and "ARMADURA" in _cam({"camada": t.camada}):
            continue
        esc = next((e for e in escalas if 0 < e.cy - t.cy < 3 * h and t.x0 - 4 * h < e.cx < t.x1 + 4 * h), None)
        if esc:
            titulos.append((t, esc))
    regs = []
    for t, esc in titulos:
        regs.append({"titulo": re.sub(r"\s+", " ", t.text).strip(), "tipo": _tipo_titulo(t.n),
                     "escala": re.sub(r"(?i)^e?sc(ala)?\s*", "", esc.text).strip(), "_tit": t, "_manchas": set()})
        uso[id(t)] = uso[id(esc)] = f"desenho {t.text}"
    def candidatos(c):
        fx = mapa.faixa((c[1] + c[3]) / 2)
        out = []
        for r in regs:
            t = r["_tit"]
            ft = mapa.faixa(t.cy)
            if ft < fx or t.y1 < c[1]:  # título fica abaixo do desenho
                continue
            if ft > fx and any(b in faixas_detalhe for b in range(fx, ft)):
                continue  # não atravessa faixa de detalhamentos
            cx = (c[0] + c[2]) / 2
            # o título fica embaixo, em geral no canto direito do desenho:
            # título à direita da mancha é barato; título à esquerda é caro
            if cx < t.x0:
                dist_h = 0.5 * max(t.x0 - c[2], 0)
            elif cx > t.x1:
                dist_h = 3 * (cx - t.x1)
            else:
                dist_h = 0
            out.append((0, dist_h + 0.1 * max(t.y0 - c[3], 0), r))
        return out

    area = lambda c: (c[2] - c[0]) * (c[3] - c[1])
    grandes = {i: c for i, c in mapa.caixas.items() if area(c) > (40 * h) ** 2}
    dono_grande = {}
    for i, c in grandes.items():
        cands = candidatos(c)
        if cands:
            r = min(cands, key=lambda p: p[:2])[2]
            r["_manchas"].add(i)
            dono_grande[i] = r
    for i, c in mapa.caixas.items():
        if i in grandes:
            continue
        cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
        cont = [j for j in dono_grande if grandes[j][0] <= cx <= grandes[j][2] and grandes[j][1] <= cy <= grandes[j][3]]
        if cont:  # dentro da área de um desenho grande: herda o dono
            dono_grande[min(cont, key=lambda j: area(grandes[j]))]["_manchas"].add(i)
            continue
        cands = candidatos(c)
        if cands:
            min(cands, key=lambda p: p[:2])[2]["_manchas"].add(i)
    return regs


def distribuir(toks, regs, uso, h, mapa: Mapa):
    """Cada texto livre vai para o desenho dono da mancha de tinta em que ele está."""
    dono = {i: r for r in regs for i in r["_manchas"]}
    por_reg = {id(r): [] for r in regs}
    for t in toks:
        if id(t) in uso:
            continue
        r = dono.get(mapa.mancha(t))
        if r is not None:
            por_reg[id(r)].append(t)
    return por_reg


# ----------------------------------------------------------------------------- conteúdo de cada tipo de desenho

def ler_locacao(ts, h):
    usados = set()
    # eixos com letra: letras isoladas alinhadas na vertical (mesmo x)
    letras = [t for t in ts if re.fullmatch(r"[A-Z]", t.n)]
    grupos = {}
    for t in letras:
        grupos.setdefault(round(t.x0 / (3 * h)), []).append(t)
    col = max(grupos.values(), key=len, default=[])
    # eixos numerados: inteiros pequenos alinhados na horizontal, contendo 1, 2, 3
    inteiros = [t for t in ts if re.fullmatch(r"\d{1,2}", t.n) and t.h < 2.5 * t.w + 5]
    linhas = _agrupar_linhas(inteiros, 0.6 * h)
    fila = max((l for l in linhas if {"1", "2", "3"} <= {t.n for t in l}), key=len, default=[])
    decimais = [t for t in ts if re.fullmatch(r"-?\d+\.\d{2}", t.n)]

    eixos_y, eixos_x = [], []
    for t in sorted(col, key=lambda t: t.cy):
        c = [d for d in decimais if abs(d.cy - t.cy) < h and d.x0 > t.x1 + 10 * h]
        coord = num(min(c, key=lambda d: abs(d.cy - t.cy)).n) if c else None
        eixos_y.append({"eixo": t.n, "coord_cm": coord, "_px": t.cy})
        usados.add(id(t))
        if c:
            usados.add(id(min(c, key=lambda d: abs(d.cy - t.cy))))
    for t in sorted(fila, key=lambda t: t.cx):
        c = [d for d in decimais if abs(d.cx - t.cx) < h and d.h > d.w and d.cy < t.cy]
        coord = num(min(c, key=lambda d: abs(d.cx - t.cx)).n) if c else None
        eixos_x.append({"eixo": t.n, "coord_cm": coord, "_px": t.cx})
        usados.add(id(t))
        if c:
            usados.add(id(min(c, key=lambda d: abs(d.cx - t.cx))))

    # cotas entre eixos consecutivos (autoconferência)
    cotas = []
    for eixos, vertical in ((eixos_y, True), (eixos_x, False)):
        for a, b in zip(eixos, eixos[1:]):
            if a["coord_cm"] is None or b["coord_cm"] is None:
                continue
            d = round(abs(a["coord_cm"] - b["coord_cm"]), 1)
            meio = (a["_px"] + b["_px"]) / 2
            cand = [t for t in ts if id(t) not in usados and re.fullmatch(r"\d+(\.\d?)?", t.n)
                    and abs((t.cy if vertical else t.cx) - meio) < abs(b["_px"] - a["_px"]) / 2
                    and (abs(num(t.n.rstrip(".")) - d) <= 0.15
                         or (t.n.endswith(".") and 0 <= d - num(t.n.rstrip(".")) < 1))]
            cota = min(cand, key=lambda t: abs((t.cy if vertical else t.cx) - meio), default=None)
            if cota:
                usados.add(id(cota))
            cotas.append({"entre": f"{a['eixo']}-{b['eixo']}", "distancia_cm": d,
                          "cota_escrita": num(cota.n.rstrip(".")) if cota else None, "confere": bool(cota)})

    # pilares: rótulo + atributos empilhados (seção, h0, h1, df); fica no cruzamento de eixos à esquerda/abaixo
    pilares = []
    rotulos = [t for t in ts if re.fullmatch(r"P\d+", t.n)]
    attrs = []
    for t in ts:
        m = re.fullmatch(r"(H0|H1|DF)?=(\d+)CM\W?[LI1]?", t.n) or re.fullmatch(r"(H0|H1|DF)=?(\d+)CM\W?[LI1]?", t.n)
        if m:
            attrs.append((t, (m.group(1) or "df").lower(), int(m.group(2))))
        elif RE_SECAO.match(t.n) and t.n.endswith("CM"):
            attrs.append((t, "secao_cm", "x".join(RE_SECAO.match(t.n).group(1, 2))))
    dados = {id(p): {} for p in rotulos}
    for a, k, v in attrs:
        cands = [p for p in rotulos if 0 < a.cy - p.cy < 6 * h and abs(a.x0 - p.x0) < 3.5 * h]
        if cands:
            p = min(cands, key=lambda p: (a.cy - p.cy) + abs(a.x0 - p.x0))
            dados[id(p)][k] = v
            usados.add(id(a))
    # deslocamento típico rótulo -> eixo, medido nos próprios pilares da folha; associação só vale se for coerente
    def mais_prox(p):
        ex = max((e for e in eixos_x if e["_px"] <= p.x0 + h and p.x0 - e["_px"] < 10 * h), key=lambda e: e["_px"], default=None)
        ey = min((e for e in eixos_y if e["_px"] >= p.cy - h and e["_px"] - p.cy < 16 * h), key=lambda e: e["_px"], default=None)
        return ex, ey
    dxs = [p.x0 - ex["_px"] for p in rotulos for ex, _ in [mais_prox(p)] if ex]
    dys = [ey["_px"] - p.cy for p in rotulos for _, ey in [mais_prox(p)] if ey]
    mdx = statistics.median(dxs) if dxs else 0
    mdy = statistics.median(dys) if dys else 0
    for p in rotulos:
        usados.add(id(p))
        ex, ey = mais_prox(p)
        if ex and abs((p.x0 - ex["_px"]) - mdx) > 3 * h:
            ex = None
        if ey and abs((ey["_px"] - p.cy) - mdy) > 3 * h:
            ey = None
        d = dados[id(p)]
        pilares.append({"elemento": p.n, "secao_cm": d.get("secao_cm"),
                        "eixo_x": ex["eixo"] if ex else None, "eixo_y": ey["eixo"] if ey else None,
                        "x_cm": ex["coord_cm"] if ex else None, "y_cm": ey["coord_cm"] if ey else None,
                        "sapata": {"h0_cm": d.get("h0"), "h1_cm": d.get("h1"), "df_cm": d.get("df")}})
    # pilares fora dos eixos: posição estimada pela escala do desenho (calibrada pelos próprios eixos)
    pos = {p.n: p for p in rotulos}
    def ajuste(eixos):
        pts = [(e["_px"], e["coord_cm"]) for e in eixos if e["coord_cm"] is not None]
        if len(pts) < 2:
            return None
        a, b = np.polyfit([p[0] for p in pts], [p[1] for p in pts], 1)
        return lambda px: round(float(a * px + b), 1)
    fx, fy = ajuste(eixos_x), ajuste(eixos_y)
    px_eixo = {("x", e["eixo"]): e["_px"] for e in eixos_x} | {("y", e["eixo"]): e["_px"] for e in eixos_y}
    off_x = [px_eixo[("x", p["eixo_x"])] - pos[p["elemento"]].x0 for p in pilares if p["eixo_x"] and p["eixo_y"]]
    off_y = [px_eixo[("y", p["eixo_y"])] - pos[p["elemento"]].cy for p in pilares if p["eixo_x"] and p["eixo_y"]]
    for p in pilares:
        p["posicao"] = "no cruzamento de eixos"
        if (p["eixo_x"] and p["eixo_y"]) or not (fx and fy and off_x):
            continue
        t = pos[p["elemento"]]
        if not p["eixo_x"]:
            p["x_cm"] = fx(t.x0 + statistics.median(off_x))
        if not p["eixo_y"]:
            p["y_cm"] = fy(t.cy + statistics.median(off_y))
        p["posicao"] = "estimada pela escala (fora dos eixos)"
        # refina com a cota escrita ao lado do pilar (distância até um eixo), se ela casar com a estimativa
        for chave, eixos, eixo_px, coord_px in (("y_cm", eixos_y, "eixo_y", t.cy), ("x_cm", eixos_x, "eixo_x", t.x0)):
            if p[eixo_px] or p[chave] is None:
                continue
            perto = [c for c in ts if id(c) not in usados and re.fullmatch(r"\d+(\.\d)?", c.n)
                     and abs(c.cx - t.cx) < 8 * h and abs(c.cy - t.cy) < 14 * h]
            melhor = None
            for c in perto:
                v = num(c.n)
                for e in eixos:
                    if e["coord_cm"] is None:
                        continue
                    for sinal in (1, -1):
                        cand = round(e["coord_cm"] + sinal * v, 2)
                        erro = abs(cand - p[chave])
                        if erro < 15 and (melhor is None or erro < melhor[0]):
                            melhor = (erro, cand, c, e["eixo"], v)
            if melhor:
                _, p[chave], c, eixo, v = melhor
                usados.add(id(c))
                p["posicao"] = f"pela cota de {v} cm ao eixo {eixo}"
    _geometria_locacao(pilares, pos, eixos_x, eixos_y, h)
    pilares.sort(key=lambda p: int(p["elemento"][1:]))
    for e in eixos_x + eixos_y:
        e.pop("_px")
    return {"eixos_numerados": eixos_x, "eixos_letras": eixos_y, "cotas_entre_eixos": cotas, "pilares": pilares}, usados


def _geometria_locacao(pilares, pos, eixos_x, eixos_y, h):
    """PDF com camadas: usa as linhas de eixo (LC-Eixos) e os retângulos dos pilares (LC-Seção dos pilares)
    para dar o centro exato de cada pilar e conferir a seção desenhada contra a seção escrita."""
    retang = [v for v in VETORES if _cam(v).startswith("LC") and "SECAODOSPILARES" in _cam(v)]
    linhas = [v for v in VETORES if _cam(v).startswith("LC") and "EIXOS" in _cam(v)]
    if not retang:
        return
    vert = [(v["box"][0] + v["box"][2]) / 2 for v in linhas if v["box"][2] - v["box"][0] < 3]
    hor = [(v["box"][1] + v["box"][3]) / 2 for v in linhas if v["box"][3] - v["box"][1] < 3]

    def ajusta(eixos, linhas_px):
        pts = []
        for e in eixos:
            if e["coord_cm"] is None:
                continue
            l = min(linhas_px, key=lambda x: abs(x - e["_px"])) if linhas_px else e["_px"]
            # sem linhas (imagem): o rótulo do eixo está centrado na linha
            pts.append((l if abs(l - e["_px"]) < 4 * h else e["_px"], e["coord_cm"]))
        if len(pts) < 2:
            return None
        a, b = np.polyfit([p[0] for p in pts], [p[1] for p in pts], 1)
        return a, b

    ax, ay = ajusta(eixos_x, vert), ajusta(eixos_y, hor)
    if not ax or not ay:
        return
    # liga rótulo -> retângulo (o mais próximo, um para um)
    centros = [((r["box"][0] + r["box"][2]) / 2, (r["box"][1] + r["box"][3]) / 2, r) for r in retang]
    # deslocamento típico rótulo -> retângulo, aprendido dos pares sem ambiguidade (o mais próximo um do outro)
    def mais_prox(px, py):
        return min(range(len(centros)), key=lambda i: math.hypot(centros[i][0] - px, centros[i][1] - py))
    offs = []
    for p in pilares:
        t = pos[p["elemento"]]
        i = mais_prox(t.cx, t.cy)
        j = min(pilares, key=lambda q: math.hypot(centros[i][0] - pos[q["elemento"]].cx, centros[i][1] - pos[q["elemento"]].cy))
        if j is p:
            offs.append((centros[i][0] - t.cx, centros[i][1] - t.cy))
    odx = statistics.median([o[0] for o in offs]) if offs else 0
    ody = statistics.median([o[1] for o in offs]) if offs else 0
    pares = sorted(((math.hypot(cx - pos[p["elemento"]].cx - odx, cy - pos[p["elemento"]].cy - ody), p["elemento"], i)
                    for p in pilares for i, (cx, cy, _) in enumerate(centros)), key=lambda x: x[0])
    usado_p, usado_r, liga = set(), set(), {}
    for d, el, i in pares:
        if el in usado_p or i in usado_r or d > 10 * h:
            continue
        usado_p.add(el)
        usado_r.add(i)
        liga[el] = centros[i]
    for p in pilares:
        if p["elemento"] not in liga:
            continue
        cx, cy, r = liga[p["elemento"]]
        b = r["box"]
        p["centro_cm"] = {"x": round(float(ax[0] * cx + ax[1]), 1), "y": round(float(ay[0] * cy + ay[1]), 1)}
        dx, dy = round(float(abs(ax[0]) * (b[2] - b[0])), 1), round(float(abs(ay[0]) * (b[3] - b[1])), 1)
        p["secao_desenhada_cm"] = f"{min(dx, dy):g}x{max(dx, dy):g}"
        p["dim_cm"] = {"x": dx, "y": dy}  # dimensão do pilar em cada direção da planta
        if p.get("secao_cm"):
            esc = sorted(float(x) for x in p["secao_cm"].split("x"))
            p["secao_confere"] = bool(abs(esc[0] - min(dx, dy)) <= 1 and abs(esc[1] - max(dx, dy)) <= 1)
        # eixo de cada direção decidido pela posição real: o eixo que passa a menos de 20 cm do centro
        for chave_e, chave_c, eixos, c in (("eixo_x", "x_cm", eixos_x, p["centro_cm"]["x"]),
                                           ("eixo_y", "y_cm", eixos_y, p["centro_cm"]["y"])):
            perto = [e for e in eixos if e["coord_cm"] is not None and abs(e["coord_cm"] - c) < 20]
            if perto:
                e = min(perto, key=lambda e: abs(e["coord_cm"] - c))
                p[chave_e], p[chave_c] = e["eixo"], e["coord_cm"]
            else:
                p[chave_e] = None
                if "pela cota" not in str(p.get("posicao")):
                    p[chave_c] = c
                    p["posicao"] = "pela geometria (fora dos eixos)"
            # referência: eixo mais próximo e deslocamento do centro do pilar até ele
            ref = min((e for e in eixos if e["coord_cm"] is not None), key=lambda e: abs(e["coord_cm"] - c), default=None)
            if ref:
                p["ref_" + chave_e[-1]] = {"eixo": ref["eixo"], "deslocamento_cm": round(c - ref["coord_cm"], 1)}
        if p.get("eixo_x") and p.get("eixo_y"):
            p["posicao"] = "no cruzamento de eixos"
        p["posicao_geometria"] = ("retângulo do pilar no PDF (camada LC-Seção dos pilares)" if r.get("conf") is None
                                  else f"símbolo do pilar achado na imagem (correlação {r['conf']})")


RE_VIGA_ROT = re.compile(r"^(V\d+?)(\d{2}[X×*]\d{2})?$")


def ler_forma(ts, h):
    usados, vigas, pilares, lajes = set(), {}, {}, {}
    secoes = [t for t in ts if RE_SECAO.match(t.n) and not t.n.endswith("CM")]
    for t in ts:
        m = re.fullmatch(r"(V\d+)(\d{2}[X×*K]\d{2})?", t.n)
        m2 = re.fullmatch(r"\[?(\d{2})[X×*K8](\d{2})(V\d+)", t.n)  # OCR juntou seção e rótulo
        if m2:
            v = vigas.setdefault(m2.group(3), {"elemento": m2.group(3), "secao_cm": None, "rotulos": 0})
            v["rotulos"] += 1
            v["secao_cm"] = v["secao_cm"] or f"{m2.group(1)}x{m2.group(2)}"
            usados.add(id(t))
            continue
        if m and (m.group(2) or len(m.group(1)) <= 4):
            nome, sec = m.group(1), m.group(2)
            if sec is None and len(t.n) > 3 and re.fullmatch(r"V\d{3,}", t.n):
                continue
            v = vigas.setdefault(nome, {"elemento": nome, "secao_cm": None, "rotulos": 0})
            v["rotulos"] += 1
            if sec:
                v["secao_cm"] = re.sub(r"[X×*K]", "x", sec)
            usados.add(id(t))
            continue
        m = re.fullmatch(r"(P\d+)(\(MORRE\)|\(NASCE\))?", t.n)
        if m:
            p = pilares.setdefault(m.group(1), {"elemento": m.group(1), "secao_cm": None, "situacao": "passa",
                                                "_px": [t.cx, t.cy]})
            if m.group(2):
                p["situacao"] = "morre" if "MORRE" in m.group(2) else "nasce"
            sec = [s for s in secoes if id(s) not in usados and abs(s.cx - t.cx) < 3 * h and 0 < t.cy - s.cy < 2.5 * h]
            if sec:
                s = min(sec, key=lambda s: t.cy - s.cy)
                p["secao_cm"] = "x".join(RE_SECAO.match(s.n).group(1, 2))
                usados.add(id(s))
            usados.add(id(t))
            continue
        m = re.fullmatch(r"(L\d+)", t.n)
        if m:
            l = lajes.setdefault(m.group(1), {"elemento": m.group(1), "detalhe": None, "_px": [t.cx, t.cy]})
            det = [d for d in ts if re.fullmatch(r"DET-?\d+", d.n) and abs(d.cx - t.cx) < 3 * h and 0 < d.cy - t.cy < 2.5 * h]
            if det:
                l["detalhe"] = det[0].text
                usados.add(id(det[0]))
            usados.add(id(t))
    # seções soltas ao lado de rótulos de viga ("V4 15x30" separados)
    for s in secoes:
        if id(s) in usados:
            continue
        viz = [t for t in ts if RE_VIGA_ROT.match(t.n) and abs(t.cy - s.cy) < h and 0 < s.x0 - t.x1 < 2 * h]
        if viz:
            nome = RE_VIGA_ROT.match(viz[0].n).group(1)
            if nome in vigas and not vigas[nome]["secao_cm"]:
                vigas[nome]["secao_cm"] = "x".join(RE_SECAO.match(s.n).group(1, 2))
            usados.add(id(s))
    rot_p = [t for t in ts if re.fullmatch(r"P\d+(\(MORRE\)|\(NASCE\))?", t.n)]
    for s_ in secoes:
        if id(s_) in usados:
            continue
        perto = [t for t in rot_p if abs(t.cx - s_.cx) < 4 * h and abs(t.cy - s_.cy) < 3 * h]
        if perto:
            t = min(perto, key=lambda t: abs(t.cx - s_.cx) + abs(t.cy - s_.cy))
            p = pilares[re.match(r"P\d+", t.n).group(0)]
            p["secao_cm"] = p["secao_cm"] or "x".join(RE_SECAO.match(s_.n).group(1, 2))
            usados.add(id(s_))
    ordena = lambda d: sorted(d.values(), key=lambda e: int(re.sub(r"\D", "", e["elemento"]) or 0))
    for v in vigas.values():
        v.pop("rotulos")
    return {"vigas": ordena(vigas), "pilares": ordena(pilares), "lajes": ordena(lajes)}, usados


def ler_corte(ts, h):
    usados, niveis, elementos = set(), [], []
    for t in ts:
        if re.search(r"[A-Z]{3,}", t.n) and not re.fullmatch(r"[PVL]\d+.*", t.n):
            val = [v for v in ts if re.fullmatch(r"-?\d+(\.\d+)?", v.n) and 0 < t.cy - v.cy < 2.5 * h and abs(v.x0 - t.x0) < 3 * h]
            if val:
                v = min(val, key=lambda v: t.cy - v.cy)
                niveis.append({"nivel": t.text, "cota_cm": num(v.n)})
                usados |= {id(t), id(v)}
    for t in ts:
        m = re.fullmatch(r"([PVL]\d+)(\(MORRE\))?", t.n)
        if m:
            if m.group(1) not in [e["elemento"] for e in elementos]:
                elementos.append({"elemento": m.group(1), "morre": bool(m.group(2))})
            usados.add(id(t))
    return {"niveis": niveis, "elementos": elementos}, usados


def ler_lajes(ts, h):
    usados, lajes = set(), []
    for t in ts:
        if re.fullmatch(r"L\d+", t.n):
            alt = [a for a in ts if re.fullmatch(r"H=\d+(\.\d+)?", a.n) and abs(a.cx - t.cx) < 2 * h and 0 < a.cy - t.cy < 2.5 * h]
            lajes.append({"elemento": t.n, "altura_cm": num(alt[0].n[2:]) if alt else None})
            usados.add(id(t))
            if alt:
                usados.add(id(alt[0]))
    lajes.sort(key=lambda l: int(l["elemento"][1:]))
    return {"lajes": lajes}, usados


def ler_vigotas(ts, h):
    usados, vig = set(), []
    for t in ts:
        m = re.fullmatch(r"(VP\d+[A-Z]?)-(\d+(\.\d+)?)", t.n)
        if m:
            vig.append({"vigota": t.text.split("-")[0].strip(), "comprimento_cm": num(m.group(2))})
            usados.add(id(t))
    vig.sort(key=lambda v: (int(re.sub(r"\D", "", v["vigota"])), v["vigota"]))
    return {"vigotas": vig}, usados


LEITORES = {"locacao": ler_locacao, "forma": ler_forma, "corte": ler_corte,
            "armacao_lajes": ler_lajes, "vigotas": ler_vigotas}


def _tem_conteudo(tipo, d):
    """O que define cada tipo, para aceitá-lo sem o título dizer: locação tem eixos nas duas direções com a coordenada
    escrita; forma tem vigas apoiadas em pilares; corte tem ao menos dois níveis diferentes (texto de escala não é
    nível). Um rótulo solto não basta."""
    if tipo == "locacao":
        com_coord = lambda eixos: sum(1 for e in eixos if e.get("coord_cm") is not None)
        return com_coord(d.get("eixos_letras", [])) >= 2 and com_coord(d.get("eixos_numerados", [])) >= 2
    if tipo == "forma":
        return len(d.get("vigas", [])) >= 2 and len(d.get("pilares", [])) >= 2
    if tipo == "corte":
        cotas = {n["cota_cm"] for n in d.get("niveis", []) if not RE_ESCALA.match(norm_txt(n["nivel"]))}
        return len(cotas) >= 2
    return True


def norm_txt(s):
    from .analisar import norm
    return norm(s)


def ler_regioes(regs, por_reg, uso, h):
    out = []
    for r in regs:
        ts = por_reg[id(r)]
        if r["tipo"] in LEITORES:
            dados, usados = LEITORES[r["tipo"]](ts, h)
        else:  # tipo não reconhecido pelo título: testa todos os leitores e fica com o que mais estruturou
            # só vale o tipo cujo leitor achou o que define aquele desenho; sem isso, um detalhe cheio de rótulos de
            # pilar "vira" locação ou forma e o pacote pega essa folha como a locação do projeto
            tentativas = [(len(u), tipo, d, u) for tipo, leitor in LEITORES.items()
                          for d, u in [leitor(ts, h)] if _tem_conteudo(tipo, d)]
            n, tipo, dados, usados = max(tentativas, key=lambda x: x[0], default=(0, None, {}, set()))
            if n:
                r["tipo"] = tipo
        for t in ts:
            uso[id(t)] = f"desenho {r['titulo']}"
        resto = [t for t in ts if id(t) not in usados]
        cotas, rotulos, textos = separar_soltos(resto)
        out.append({"titulo": r["titulo"], "tipo": r["tipo"], "escala": r["escala"], "dados": dados,
                    "cotas": cotas, "rotulos": rotulos, "textos": textos})
    return out


RE_ROTULO = re.compile(r"(E?SC(ALA)?[1IT]?:?\d+.*|SECAO([A-Z]-[A-Z])?|[A-Z]|PLANTA|CORTE|VISTA[A-Z]|\(\d+C\)|VAR|DET-?\d+)")


def separar_soltos(ts):
    """Divide os textos que sobraram em cotas (números), rótulos de desenho (ESC 1:50, SEÇÃO A-A, A, VISTA H...)
    e outros textos."""
    cotas, rotulos, textos = [], [], []
    for t in ts:
        eh_cota_camada = bool(t.camada) and "COTA" in _cam({"camada": t.camada})
        if re.fullmatch(r"-?\d+(\.\d+)?", t.n) or eh_cota_camada:
            x = texto_pos(t)
            x["valor"] = num(t.n)
            if len(t.n) >= 2:
                x["vertical"] = t.h > 1.3 * t.w
            cotas.append(x)
        elif RE_ROTULO.fullmatch(t.n):
            rotulos.append(t.text)
        else:
            textos.append(texto_pos(t))
    return cotas, rotulos, textos
