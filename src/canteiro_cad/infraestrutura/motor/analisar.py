"""Interpretação dos tokens de OCR de pranchas de cálculo estrutural (padrão Eberick/AutoCAD).

Todas as coordenadas são normalizadas para uma folha de largura REF_W (A1 a 200 dpi),
assim os limiares em pixels valem para PNGs de qualquer resolução.
"""
from __future__ import annotations

import math
import re
import statistics
import unicodedata

import cv2

REF_W = 9362.0
DIAMETROS = ["5.0", "6.3", "8.0", "10.0", "12.5", "16.0", "20.0", "25.0", "32.0"]
GRUPOS = {"S": "Sapatas", "P": "Pilares", "V": "Vigas", "L": "Lajes"}
SINGULAR = {"S": "Sapata", "P": "Pilar", "V": "Viga", "L": "Laje"}


# ----------------------------------------------------------------------------- utilidades

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "", s.upper())


class Tok:
    __slots__ = ("text", "conf", "x0", "y0", "x1", "y1", "camada")

    def __init__(self, d, f):
        self.text = d["text"]
        self.conf = d["conf"]
        self.camada = d.get("camada")  # camada do CAD (só em PDF vetorial com camadas)
        self.x0, self.y0, self.x1, self.y1 = (v * f for v in d["box"])

    cx = property(lambda s: (s.x0 + s.x1) / 2)
    cy = property(lambda s: (s.y0 + s.y1) / 2)
    h = property(lambda s: s.y1 - s.y0)
    n = property(lambda s: norm(s.text))

    def __repr__(self):
        return f"<{self.text}@{int(self.cx)},{int(self.cy)}>"


def num(s):
    s = s.replace(",", ".").strip()
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def massa_linear(diam_mm: float) -> float:
    """kg/m de uma barra de aço (densidade 7850 kg/m³)."""
    return math.pi * (diam_mm / 1000) ** 2 / 4 * 7850


# ----------------------------------------------------------------------------- carimbo

def _linhas_ocr(crop, escala):
    from .ocr import _get_engine
    crop = cv2.resize(crop, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    res, _ = _get_engine()(crop, use_cls=False)
    linhas = []
    for quad, txt, _c in res or []:
        linhas.append((sum(p[1] for p in quad) / 4 * 2 / escala, min(p[0] for p in quad) * 2 / escala, txt.strip()))
    return sorted(linhas)


def ler_carimbo(img, toks: list[Tok], f: float, vetorial: bool = False) -> dict:
    """Carimbo. Em imagem, relê ampliado 2x (no OCR da folha inteira os espaços somem);
    em PDF vetorial usa o texto do próprio PDF."""

    ancora = next((t for t in toks if t.n.startswith("CLIENTE")), None)
    H, W = img.shape[:2]
    if ancora:
        topo = min([t.y0 for t in toks if "CALCULOESTRUTURAL" in t.n and abs(t.cy - ancora.cy) < 200] or [ancora.y0 - 80])
        x0, y0 = int((ancora.x0 - 60) / f), int((topo - 30) / f)
    else:  # posição padrão: canto inferior direito
        x0, y0 = int(W * 0.86), int(H * 0.92)
    if vetorial:
        linhas = sorted(((t.cy / f - y0) * 2, (t.x0 / f - x0) * 2, t.text) for t in toks
                        if t.x0 / f >= x0 - 2 and t.y0 / f >= y0 - 2)
    else:
        linhas = _linhas_ocr(img[max(0, y0):, max(0, x0):], 2)

    def apos(chave):
        """texto à direita do rótulo, na mesma linha"""
        for cy, x, txt in linhas:
            if norm(txt).startswith(chave):
                resto = txt.split(":", 1)[1].strip() if ":" in txt else ""
                if resto:
                    return resto
                viz = [(xx, tt) for cc, xx, tt in linhas if abs(cc - cy) < 15 and xx > x and not norm(tt).startswith(("DATA", "FOLHA"))]
                if viz:
                    return " ".join(tt for _, tt in sorted(viz))
        return None

    def apos_pagina(chave):
        """fallback: mesmo campo no OCR da folha inteira (sem espaços, mas presente)"""
        rot = next((t for t in toks if t.n.startswith(chave) and (not ancora or t.cy >= ancora.cy - 30)), None)
        if not rot:
            return None
        viz = sorted((t for t in toks if abs(t.cy - rot.cy) < 15 and 0 < t.x0 - rot.x1 < 400), key=lambda t: t.x0)
        return viz[0].text if viz else None

    def campo(chave):
        v = apos(chave)
        if v and " " not in v and len(v) > 20:  # texto colado: tenta outra ampliação
            v = None
        if not v and not vetorial:
            nonlocal linhas
            orig = linhas
            linhas = _linhas_ocr(img[max(0, y0):, max(0, x0):], 3)
            v = apos(chave)
            linhas = orig
        return v or apos_pagina(chave)
    out = {
        "titulo": next((t for _, _, t in linhas if "ESTRUTURAL" in norm(t)), None),
        "cliente": campo("CLIENTE"),
        "local": campo("LOCAL"),
        "data": None,
        "folha": None,
        "responsavel": campo("CALCULO:"),
        "crea": None,
        "conteudo": None,
    }
    for cy, x, txt in linhas:
        m = re.search(r"DATA[:\s]*([\d/]+)", norm(txt))
        if m:
            out["data"] = m.group(1)
    rot_folha = next(((cy, x) for cy, x, t in linhas if norm(t).startswith("FOLHA")), None)
    m_folha = next((re.match(r"FOLHA:?(\d{1,3})$", norm(t)) for _, _, t in linhas if re.match(r"FOLHA:?\d", norm(t))), None)
    if m_folha:
        out["folha"] = m_folha.group(1)
    elif rot_folha:
        cands = [(abs(cy - rot_folha[0]) + abs(x - rot_folha[1]) / 5, t) for cy, x, t in linhas
                 if re.fullmatch(r"\d{1,3}", norm(t)) and cy >= rot_folha[0] - 20]
        if cands:
            out["folha"] = min(cands)[1]
    rot_cont = next(((cy, x) for cy, x, t in linhas if norm(t).startswith("CONTEUDO")), None)
    if rot_cont:
        partes = [t for cy, x, t in linhas if cy > rot_cont[0] - 15 and x > rot_cont[1] + 20
                  and not norm(t).startswith("FOLHA") and not re.fullmatch(r"\d{1,3}", norm(t))]
        out["conteudo"] = " ".join(partes).strip() or None
    for k, v in out.items():
        if isinstance(v, str):
            out[k] = re.sub(r"\s+", " ", v).strip()
    if out["responsavel"]:
        m = re.search(r"CREA\s*([\d.\-/A-Z]+?)(?:-?\s*TEL|$)", out["responsavel"].upper())
        if m:
            out["crea"] = m.group(1).strip("- ")
        out["responsavel"] = re.split(r"\s*-\s*CREA", out["responsavel"], flags=re.I)[0].strip()
    return out


# ----------------------------------------------------------------------------- classificação

def classificar(toks: list[Tok], carimbo: dict, tabelas: list[dict], detalhes: dict) -> dict:
    conteudos = []
    for t in toks:
        n = t.n
        m = re.search(r"FORMADOPAVIMENTO(.+?)\(N[I1]VEL(\d+)\)", n)
        if m:
            mm = re.search(r"PAVIMENTO\s*(.+?)\s*\(", t.text, re.I)
            conteudos.append(f"Forma do pavimento {(mm.group(1) if mm else m.group(1)).strip().title()} (nível {m.group(2)})")
        elif "PLANTADELOCAC" in n:
            conteudos.append("Planta de locação (pilares e sapatas)")
        elif re.fullmatch(r"CORTE[A-Z]-[A-Z]", n):
            conteudos.append(f"Corte {n[5:]}")
        elif "ARMACAOPOSITIVADASLAJES" in n or "ARMACAONEGATIVADASLAJES" in n:
            eixo = re.search(r"EIXO([XY])", n)
            tipo = "positiva" if "POSITIVA" in n else "negativa"
            conteudos.append(f"Armação {tipo} das lajes" + (f" (eixo {eixo.group(1)})" if eixo else ""))
        elif "PLANTADEVIGOTAS" in n:
            conteudos.append("Planta de vigotas pré-moldadas")
    for grupo, itens in detalhes.items():
        if itens:
            conteudos.append(f"Detalhamento de {grupo.lower()} ({len(itens)} desenhos)")
    if tabelas:
        conteudos.append(f"Tabelas de aço ({len(tabelas)})")
    conteudos = list(dict.fromkeys(conteudos))

    # tipo principal
    tem = lambda chave: any(chave in c for c in conteudos)
    if tem("Forma do pavimento") or tem("locação"):
        tipo = "Formas e locação"
    elif tem("Detalhamento") or tem("Armação"):
        tipo = "Detalhamento de armaduras"
    else:
        tipo = "Não identificado"
    pav = None
    if carimbo.get("conteudo"):
        m = re.search(r"PAV\.?\s*(.+)", carimbo["conteudo"], re.I)
        if m:
            pav = m.group(1).strip().title()
    return {"tipo": tipo, "pavimento": pav, "conteudos": conteudos}


# ----------------------------------------------------------------------------- tabelas de aço

def _mesma_linha(a: Tok, b: Tok, tol=18):
    return abs(a.cy - b.cy) < tol


def _agrupar_linhas(itens: list[Tok], tol: float) -> list[list[Tok]]:
    linhas: list[list[Tok]] = []
    for t in sorted(itens, key=lambda t: t.cy):
        if linhas and t.cy - statistics.mean(x.cy for x in linhas[-1]) <= tol:
            linhas[-1].append(t)
        else:
            linhas.append([t])
    return [sorted(l, key=lambda t: t.cx) for l in linhas]


def _colunas(toks, ancora: Tok, nomes: dict[str, callable], alcance=(-700, 700)):
    cols = {}
    for t in toks:
        if _mesma_linha(t, ancora) and alcance[0] < t.cx - ancora.cx < alcance[1]:
            for k, teste in nomes.items():
                if k not in cols and teste(t.n):
                    cols[k] = t.cx
    return cols


def _por_coluna(t: Tok, cols: dict) -> str:
    return min(cols, key=lambda k: abs(cols[k] - t.cx))


def extrair_tabelas(toks: list[Tok]) -> list[dict]:
    tabelas = []
    cabecalhos = [t for t in toks if t.n == "QUANT"]
    titulos = [t for t in toks if "RELACAODOAC" in t.n]
    resumos = [t for t in toks if "RESUMODOACO" in t.n]
    usados_titulos = set()

    for q in cabecalhos:
        cols = _colunas(toks, q, {
            "aco": lambda n: n in ("ACO", "AÇO"),
            "n": lambda n: n == "N",
            "diam": lambda n: n.startswith("DIAM"),
            "quant": lambda n: n == "QUANT",
            "c_unit": lambda n: n.startswith("C.UNIT"),
            "c_total": lambda n: n.startswith("C.TOTAL"),
        })
        if not {"n", "diam", "c_unit", "c_total"} <= cols.keys():
            continue
        cols.setdefault("aco", cols["n"] - 100)
        xmin, xmax = min(cols.values()) - 60, max(cols.values()) + 90

        titulo = min((t for t in titulos if t.cy < q.cy and abs(t.cx - (xmin + xmax) / 2) < 500),
                     key=lambda t: q.cy - t.cy, default=None)
        resumo = min((t for t in resumos if t.cy > q.cy and xmin - 100 < t.cx < xmax + 100),
                     key=lambda t: t.cy - q.cy, default=None)
        fim = resumo.cy - 10 if resumo else q.cy + 2500

        # elementos listados entre o título e o cabeçalho (ex.: "24xS1 S12 2xS13")
        elementos = []
        if titulo:
            usados_titulos.add(id(titulo))
            for t in sorted(toks, key=lambda t: (round(t.cy / 15), t.cx)):
                if titulo.cy < t.cy < q.cy - 10 and xmin - 60 < t.cx < xmax + 60:
                    for m in re.finditer(r"(?:(\d+)X)?([PVSL]\d+)", t.n):
                        elementos.append({"elemento": m.group(2), "quantidade": int(m.group(1) or 1)})
        letras = [e["elemento"][0] for e in elementos]
        grupo = GRUPOS.get(max(set(letras), key=letras.count)) if letras else None

        # linhas de dados
        dados = [t for t in toks if q.cy + 45 < t.cy < fim and xmin < t.cx < xmax
                 and (re.fullmatch(r"\d+(\.\d+)?", t.n) or re.fullmatch(r"CA-?\d{2}", t.n))]
        diam_y = sorted(t.cy for t in dados if _por_coluna(t, cols) == "diam")
        passo = statistics.median([b - a for a, b in zip(diam_y, diam_y[1:])] or [24])
        linhas_out = []
        aco_atual = None
        for linha in _agrupar_linhas(dados, max(6.0, 0.45 * passo)):
            cel = {}
            for t in linha:
                cel.setdefault(_por_coluna(t, cols), t.n)
            if "aco" in cel:
                aco_atual = cel["aco"].replace("-", "")
            if "n" not in cel or "diam" not in cel:
                continue
            reg = {"aco": aco_atual, "n": num(cel["n"]), "diam_mm": num(cel["diam"]),
                   "quant": num(cel.get("quant", "")), "c_unit_cm": num(cel.get("c_unit", "")),
                   "c_total_cm": num(cel.get("c_total", ""))}
            # autoconferência: QUANT x C.UNIT = C.TOTAL
            q_, u_, tot = reg["quant"], reg["c_unit_cm"], reg["c_total_cm"]
            if q_ and u_ and tot:
                reg["conferido"] = q_ * u_ == tot
            elif q_ and u_ and not tot:
                reg["c_total_cm"], reg["conferido"] = q_ * u_, "calculado"
            elif u_ and tot and not q_ and tot % u_ == 0:
                reg["quant"], reg["conferido"] = tot // u_, "calculado"
            else:
                reg["conferido"] = False
            linhas_out.append(reg)

        tab = {"grupo": grupo, "elementos": elementos, "linhas": linhas_out,
               "_pos": (xmin, q.cy, xmax, fim), "_titulo": titulo}
        tab.update(_resumo(toks, resumo, xmin, xmax) if resumo else {"resumo": [], "peso_total_kg": {}})
        tab.update(_concreto_forma(toks, xmin, xmax, q.cy, fim + 1200))
        tab["resumo_calculado"] = _resumo_calculado(linhas_out)
        y_fim = max(fim, tab.pop("_ymax", 0) or 0)
        # borda esquerda = texto mais à esquerda que é da tabela (cabeçalho, título, lista de elementos, volume)
        da_tabela = [t for t in toks if _mesma_linha(t, q) and xmin - 100 < t.cx < xmax + 100]
        if titulo:
            da_tabela += [titulo] + [t for t in toks if titulo.cy < t.cy < q.cy - 10 and xmin - 60 < t.cx < xmax + 60]
        x_esq = min([t.x0 for t in da_tabela] + [tab.pop("_xmin", 1e9)]) - 5
        tab["_bbox"] = (x_esq, (titulo.y0 if titulo else q.y0) - 10, xmax + 150, y_fim + 10)
        tabelas.append(tab)

    # tabelas sem linhas (ex.: lajes pré-moldadas): só título + volume de concreto
    for t in titulos:
        if id(t) in usados_titulos:
            continue
        cf = _concreto_forma(toks, t.cx - 400, t.cx + 400, t.cy, t.cy + 600)
        if cf.get("concreto"):
            cf["_bbox"] = (t.cx - 450, t.y0 - 10, t.cx + 450, (cf.pop("_ymax", 0) or t.cy + 300) + 10)
            tabelas.append({"grupo": None, "elementos": [], "linhas": [], "resumo": [], "peso_total_kg": {},
                            "resumo_calculado": [], "_pos": (t.cx - 400, t.cy, t.cx + 400, t.cy + 600), "_titulo": t, **cf})

    # grupo pelas legendas próximas quando a tabela não lista elementos
    rotulos = [(t, "Lajes") for t in toks if "LAJES" in t.n or "VIGOTAS" in t.n]
    for tab in tabelas:
        if not tab["grupo"] and rotulos:
            x, y = (tab["_pos"][0] + tab["_pos"][2]) / 2, tab["_pos"][1]
            tab["grupo"] = min(rotulos, key=lambda r: math.hypot(r[0].cx - x, r[0].cy - y))[1]
    return tabelas


def _resumo(toks, resumo: Tok, xmin, xmax) -> dict:
    cab = min((t for t in toks if t.n.startswith("C.TOTAL") and t.cy > resumo.cy and xmin - 100 < t.cx < xmax + 100),
              key=lambda t: t.cy, default=None)
    peso_tot = min((t for t in toks if "PESOTOTAL" in t.n and t.cy > resumo.cy and xmin - 150 < t.cx < xmax + 150),
                   key=lambda t: t.cy, default=None)
    out = {"resumo": [], "peso_total_kg": {}}
    if not cab:
        return out
    cols = _colunas(toks, cab, {"aco": lambda n: n == "ACO", "diam": lambda n: n.startswith("DIAM"),
                                "c_total": lambda n: n.startswith("C.TOTAL"), "peso": lambda n: n.startswith("PESO")})
    fim = peso_tot.cy - 5 if peso_tot else cab.cy + 400
    dados = [t for t in toks if cab.cy + 45 < t.cy < fim and xmin - 100 < t.cx < xmax + 100
             and (re.fullmatch(r"\d+(\.\d+)?", t.n) or re.fullmatch(r"CA-?\d{2}", t.n))]
    aco = None
    for linha in _agrupar_linhas(dados, 10):
        cel = {}
        for t in linha:
            cel.setdefault(_por_coluna(t, cols), t.n)
        aco = cel.get("aco", aco)
        if "diam" in cel and "c_total" in cel:
            out["resumo"].append({"aco": aco, "diam_mm": num(cel["diam"]), "comprimento_m": num(cel["c_total"]),
                                  "peso_kg_mais_10pct": num(cel.get("peso", ""))})
    if peso_tot:
        dados = [t for t in toks if peso_tot.cy + 25 < t.cy < peso_tot.cy + 200 and xmin - 100 < t.cx < xmax + 100]
        for linha in _agrupar_linhas(dados, 10):
            txt = [t.n for t in linha]
            if len(txt) >= 2 and re.fullmatch(r"CA-?\d{2}", txt[0]) and num(txt[1]) is not None:
                out["peso_total_kg"][txt[0].replace("-", "")] = num(txt[1])
    return out


def _concreto_forma(toks, xmin, xmax, y0, y1) -> dict:
    out = {}
    for t in sorted(toks, key=lambda t: t.cy):
        if not (y0 < t.cy < y1 and xmin - 300 < t.x0 < xmax + 100):
            continue
        m = re.search(r"VOLUMEDECONCRETO\(?(C-?\d+)?\)?=([\d.]+)", t.n)
        if m and "concreto" not in out:
            out["concreto"] = {"classe": (m.group(1) or "").replace("C", "C-").replace("--", "-") or None,
                               "volume_m3": num(m.group(2).rstrip("."))}
        m = re.search(r"AREADEFORMA=([\d.]+)", t.n)
        if m and "forma_m2" not in out:
            out["forma_m2"] = num(m.group(1).rstrip("."))
            out["_ymax"] = t.y1
        if m or "VOLUMEDECONCRETO" in t.n:
            out["_xmin"] = min(out.get("_xmin", 1e9), t.x0)
    return out


def _resumo_calculado(linhas) -> list[dict]:
    soma = {}
    for l in linhas:
        if l["diam_mm"] and l["c_total_cm"]:
            k = (l["aco"], l["diam_mm"])
            soma[k] = soma.get(k, 0) + l["c_total_cm"]
    return [{"aco": a, "diam_mm": d, "comprimento_m": round(cm / 100, 1),
             "peso_kg_mais_10pct": round(cm / 100 * massa_linear(d) * 1.1, 1)}
            for (a, d), cm in sorted(soma.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))]


# ----------------------------------------------------------------------------- elementos

RE_SECAO = re.compile(r"^(\d{2,3})\s*[X×*]\s*(\d{2,3})(CM)?$")


def elementos_tabelados(toks: list[Tok], niveis: dict) -> list[dict]:
    """Tabelas 'Nome / Seção / Elevação / Nível' (pilares, vigas) e de lajes."""
    out = []
    for t in toks:
        if not re.fullmatch(r"[PVL]\d+", t.n):
            continue
        viz = sorted((u for u in toks if u is not t and _mesma_linha(u, t, 12) and 0 < u.x0 - t.x0 < 1150),
                     key=lambda u: u.cx)
        v = [u.n for u in viz]
        nums = [num(x) for x in v[1:3] if num(x) is not None]
        if t.n[0] in "PV" and len(v) >= 2 and RE_SECAO.match(v[0]) and nums and viz[0].x0 - t.x1 < 150 \
                and viz[1].x0 - viz[0].x1 < 300:
            b, h = RE_SECAO.match(v[0]).group(1, 2)
            nivel = nums[-1]
            out.append({"elemento": t.n, "tipo": SINGULAR[t.n[0]], "secao_cm": f"{b}x{h}",
                        "elevacao_cm": nums[0] if len(nums) > 1 else None,
                        "nivel_cm": nivel, "pavimento": niveis.get(nivel), "origem": "tabela"})
        elif t.n[0] == "L" and v and ("MOLDADA" in v[0] or "MACICA" in v[0] or "NERVURADA" in v[0]) and len(v) >= 7:
            vals = [num(x) for x in v[1:]]
            nivel = vals[2]
            out.append({"elemento": t.n, "tipo": "Laje", "laje_tipo": viz[0].text, "altura_cm": vals[0],
                        "nivel_cm": nivel, "pavimento": niveis.get(nivel),
                        "peso_proprio_kgf_m2": vals[3], "carga_adicional_kgf_m2": vals[4],
                        "carga_acidental_kgf_m2": vals[5], "origem": "tabela"})
    # se a folha declara os níveis (títulos "FORMA DO PAVIMENTO X (NÍVEL n)"), descarta linhas com nível desconhecido
    if niveis:
        out = [e for e in out if e.get("nivel_cm") in niveis]
    # remove duplicatas (mesmo elemento/nível)
    vistos, unicos = set(), []
    for e in out:
        k = (e["elemento"], e.get("nivel_cm"))
        if k not in vistos:
            vistos.add(k)
            unicos.append(e)
    return unicos


def niveis_pavimentos(toks) -> dict:
    niveis = {}
    for t in toks:
        m = re.search(r"PAVIMENTO\s*(.+?)\s*\(\s*N\S*VEL\s*(\d+)\s*\)", t.text, re.I)
        if m:
            niveis[int(m.group(2))] = m.group(1).strip().title()
    return niveis


def sapatas_locacao(toks: list[Tok]) -> list[dict]:
    """Na planta de locação cada pilar traz: '15x30 cm', 'h0 = 25 cm', 'h1 = 35 cm', 'df = 150 cm'."""
    rotulos = [t for t in toks if re.fullmatch(r"P\d+", t.n)]
    attrs = []
    for t in toks:
        n = t.n
        m = re.fullmatch(r"(H0|H1|DF)=?(\d+)CM", n)
        if m:
            attrs.append((t, m.group(1).lower(), int(m.group(2))))
        elif RE_SECAO.match(n) and n.endswith("CM"):
            b, h = RE_SECAO.match(n).group(1, 2)
            attrs.append((t, "secao_cm", f"{b}x{h}"))
    if not attrs:
        return []
    dados: dict[int, dict] = {}
    for a, k, v in attrs:
        cands = [p for p in rotulos if 0 < a.cy - p.cy < 160 and abs(a.x0 - p.x0) < 90]
        if not cands:
            continue
        p = min(cands, key=lambda p: (a.cy - p.cy) + abs(a.x0 - p.x0))
        dados.setdefault(id(p), {"elemento": p.n})[k] = v
    out = []
    for d in dados.values():
        if {"h0", "h1", "df"} & d.keys():
            out.append({"elemento": d["elemento"], "tipo": "Pilar", "secao_cm": d.get("secao_cm"),
                        "sapata": {"h0_cm": d.get("h0"), "h1_cm": d.get("h1"), "df_cm": d.get("df")},
                        "origem": "planta de locação"})
    return sorted(out, key=lambda e: int(e["elemento"][1:]))


RE_CHAMADA = re.compile(r"(\d+)N(.+?)(?:C/(\d+))?C?=(\d+)")


def _ler_chamada(texto: str, tabela_idx: dict) -> dict | None:
    """'2 N10 ø8.0 C=963 (1c)' -> {qtd:2, n:10, diam:8.0, c:963}. O 'ø' costuma virar 0/o/α/∞ no OCR."""
    t = norm(re.sub(r"[øØφΦ∅]", "#", texto))  # mantém o 'ø' como separador
    t = re.sub(r"^\(\d+C\)", "", t)
    t = re.sub(r"^[IL|](?=\d*N)", "1", t)  # 'I N12' -> '1 N12' 
    m = RE_CHAMADA.search(t)
    if not m:
        return None
    qtd, meio, espac, c = m.groups()
    meio = re.sub(r"[^\d.]", "|", meio).strip("|")
    cands = []
    if "|" in meio:
        partes = [p for p in meio.split("|") if p]
        if len(partes) >= 2 and partes[0].isdigit():
            cands.append((int(partes[0]), partes[-1]))
    else:
        for d in DIAMETROS:
            if meio.endswith(d) and len(meio) > len(d):
                resto = meio[: -len(d)]
                if resto.isdigit():
                    cands.append((int(resto), d))
                    if resto.endswith("0") and len(resto) > 1:
                        cands.append((int(resto[:-1]), d))
    if not cands:
        return None
    c = int(c)
    escolha = next(((n, d) for n, d in cands if tabela_idx.get(n) == (float(d), c)), None)
    escolha = escolha or next(((n, d) for n, d in cands if n in tabela_idx and tabela_idx[n][0] == float(d)), cands[0])
    return {"quant": int(qtd), "n": escolha[0], "diam_mm": float(escolha[1]), "comprimento_cm": c,
            "espacamento_cm": int(espac) if espac else None}


def _titulos_detalhe(toks: list[Tok], tabelas: list[dict], h_ref: float) -> list[tuple[Tok, str]]:
    def dentro_tabela(t):
        for tab in tabelas:
            x0, y0, x1, y1 = tab["_pos"]
            ty = tab["_titulo"].cy if tab.get("_titulo") else y0
            if x0 - 150 < t.cx < x1 + 150 and ty - 20 < t.cy < y1:
                return True
        return False

    cands = [t for t in toks if re.fullmatch(r"=?[PSV]\d+(=[PSV]\d+)*=?", t.n) and not dentro_tabela(t)]
    escalas = [t for t in toks if _eh_escala(t)]
    if any(t.camada for t in toks):  # PDF com camadas: o CAD já diz quem é título de detalhamento
        com_camada = [t for t in cands if t.camada and "TITULO" in norm(t.camada) and norm(t.camada).startswith("DT")]
        if com_camada:
            cands = com_camada
            escalas = escalas + cands  # dispensa a exigência de 'ESC 1:xx' embaixo

    # título de desenho: tem "ESC 1:xx"/"PLANTA"/"VISTA" logo abaixo, ou é uma lista com '='
    def tem_escala_abaixo(t):
        return any((0 < e.cy - t.cy < 3.5 * h_ref and -2 * h_ref < e.x0 - t.x0 < 8 * h_ref)          # vigas/sapatas
                   or (abs(e.cy - t.cy) < h_ref and 0 < e.x0 - t.x1 < 30 * h_ref and e.n.startswith("VISTA"))  # pilares
                   for e in escalas)

    if any(t.camada and "TITULO" in norm(t.camada) for t in cands):
        titulos = list(cands)
    else:
        titulos = [t for t in cands if "=" in t.n or (t.h > 1.15 * h_ref and tem_escala_abaixo(t))]
    # junta continuações ("P1=P2=...=P11=" + "=P13=..." + "=P25")
    titulos.sort(key=lambda t: (t.cy, t.x0))
    juntos: list[list[Tok]] = []
    for t in titulos:
        alvo = next((g for g in juntos if (g[-1].n.endswith("=") or t.n.startswith("="))
                     and abs(g[-1].x0 - t.x0) < 60 and 0 < t.cy - g[-1].cy < 3 * max(t.h, g[-1].h)), None)
        if alvo:
            alvo.append(t)
        else:
            juntos.append([t])
    return [(g[0], "".join(x.n for x in g).replace("==", "=").strip("=")) for g in juntos]


def _eh_escala(t: Tok) -> bool:
    return bool(re.match(r"E?SC[A-Z]*[1IT]:\d+", t.n)) or t.n in ("PLANTA", "CORTE") or t.n.startswith("VISTA")


RE_TITULO = re.compile(r"=?[PSV]\d+(=[PSV]\d+)*=?")


def refinar(img, toks: list[Tok], f: float) -> list[Tok]:
    """Relê ampliado 2x os pontos onde o OCR da folha costuma falhar:
    - "ESC 1:50" sem título logo acima (o título do desenho não foi lido);
    - textos com cara de lista de elementos corrompida (ex.: '==0=6===9=====').
    """
    from .ocr import _get_engine

    alturas = [t.h for t in toks if re.fullmatch(r"\d+(\.\d+)?", t.n)]
    h = statistics.median(alturas) if alturas else 26
    H, W = img.shape[:2]
    regioes = []
    lixo = [t for t in toks if t.n.count("=") >= 3 and not re.search(r"[PSV]\d", t.n) and "C=" not in t.n]
    for e in toks:
        if re.match(r"E?SC[A-Z]*[1IT]:\d+", e.n):
            caixa = (e.x0 - 1.5 * h, e.y0 - 3 * h, e.x0 + 6 * h, e.y0 - 2)
            acima = [t for t in toks if caixa[0] < t.cx < caixa[2] and caixa[1] < t.cy < caixa[3]]
            # sem título acima, ou só um texto curto que não parece título (ex.: 'V11' lido como '/11')
            if not acima or all(len(t.n) <= 5 and not RE_TITULO.fullmatch(t.n) and not _eh_escala(t)
                                and not t.n.startswith("SECAO") for t in acima):
                regioes.append(caixa)
                lixo.extend(t for t in acima if re.fullmatch(r"\W?\d{1,3}", t.n))
    for t in [t for t in lixo if "=" in t.n]:
        regioes.append((t.x0 - h, t.y0 - 0.5 * h, t.x1 + 4 * h, t.y1 + 0.5 * h))
    toks = [t for t in toks if t not in lixo]

    eng = _get_engine()
    for x0, y0, x1, y1 in regioes:
        X0, Y0 = max(0, int(x0 / f)), max(0, int(y0 / f))
        X1, Y1 = min(W, int(x1 / f)), min(H, int(y1 / f))
        if X1 - X0 < 5 or Y1 - Y0 < 5:
            continue
        crop = cv2.copyMakeBorder(img[Y0:Y1, X0:X1], 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        res, _ = eng(crop, use_cls=False)
        for quad, txt, conf in res or []:
            if not RE_TITULO.fullmatch(norm(txt)):
                continue
            xs = [(p[0] / 2 - 20 + X0) * f for p in quad]
            ys = [(p[1] / 2 - 20 + Y0) * f for p in quad]
            novo = Tok({"text": txt.strip(), "conf": conf, "box": [min(xs), min(ys), max(xs), max(ys)]}, 1.0)
            if not any(abs(t.cx - novo.cx) < h and abs(t.cy - novo.cy) < h for t in toks):
                toks.append(novo)
    return toks


def _manchas(img, f, alvo=2400):
    """'Comprime' a folha (reduz + binariza), apaga linhas muito longas e dilata a tinta;
    devolve as caixas (em coordenadas normalizadas) de cada mancha conexa."""
    escala = alvo / max(img.shape[:2])
    peq = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    tinta = (peq < 200).astype("uint8")
    for k in ((int(alvo * 0.25), 1), (1, int(alvo * 0.25))):
        longas = cv2.morphologyEx(tinta, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
        tinta[longas > 0] = 0
    tinta = cv2.dilate(tinta, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(tinta)
    k = f / escala
    return [(x * k, y * k, (x + w) * k, (y + h) * k) for x, y, w, h, _ in stats[1:]]


def detalhamentos(toks: list[Tok], tabelas: list[dict], img=None, f: float = 1.0,
                  uso: dict | None = None, faixa=None) -> dict[str, list[dict]]:
    """uso: id(token) -> onde foi usado. Textos já usados são ignorados; os consumidos aqui são registrados."""
    uso = {} if uso is None else uso
    toks = [t for t in toks if id(t) not in uso]
    alturas = [t.h for t in toks if re.fullmatch(r"\d+(\.\d+)?", t.n)]
    h_ref = statistics.median(alturas) if alturas else 22
    titulos = _titulos_detalhe(toks, tabelas, h_ref)
    if not titulos:
        return {}
    idx_por_grupo = {}
    for tab in tabelas:
        if tab["grupo"] and tab["linhas"]:
            idx_por_grupo[tab["grupo"]] = {l["n"]: (l["diam_mm"], l["c_unit_cm"]) for l in tab["linhas"]}

    # retângulo de cada desenho = título + maior mancha de tinta logo abaixo dele (a viga/sapata/pilar desenhado)
    retangulos = {}
    caixas = _manchas(img, f) if img is not None else []
    for tt, nome in titulos:
        r = [tt.x0, tt.y0, tt.x1, tt.y1]
        abaixo = [c for c in caixas if tt.y0 - h_ref < c[1] < tt.y1 + 6 * h_ref and c[0] < tt.x0 + 20 * h_ref
                  and c[2] > tt.x0 - 2 * h_ref and c[3] - c[1] < 60 * h_ref]
        if abaixo:
            c = max(abaixo, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
            r = [min(r[0], c[0]), min(r[1], c[1]), max(r[2], c[2]), max(r[3], c[3])]
        retangulos[nome] = r
    # vigas: o desenho termina no seu "SEÇÃO A-A" (sempre à direita, pouco abaixo do título)
    secoes = [t for t in toks if t.n.startswith("SECAO") and "-" in t.n]
    for sc in secoes:
        donos = [(tt, nome) for tt, nome in titulos if tt.cy < sc.cy and sc.cy - tt.cy < 20 * h_ref and tt.x0 < sc.x0]
        if donos:
            _, nome = max(donos, key=lambda p: p[0].x0)
            retangulos[nome][2] = max(retangulos[nome][2], sc.x1 + 8 * h_ref)
    # demais: até o próximo título da mesma fileira
    for tt, nome in titulos:
        if any(abs(sc.x1 + 8 * h_ref - retangulos[nome][2]) < 1 for sc in secoes):
            continue
        prox = [o.x0 for o, _ in titulos if o.x0 > tt.x1 and abs(o.cy - tt.cy) < 6 * h_ref]
        retangulos[nome][2] = max(retangulos[nome][2], min(prox) - h_ref) if prox else retangulos[nome][2] + 30 * h_ref

    def dono(t: Tok):
        """desenho ao qual o texto pertence. Os desenhos ficam em fileiras, com o título no canto superior esquerdo:
        candidatos = títulos acima e à esquerda do texto cujo desenho alcança o texto na horizontal;
        vence o da fileira mais baixa e, na mesma fileira, o mais à direita."""
        cands = [(tt, nome) for tt, nome in titulos
                 if tt.cy < t.cy + 0.5 * h_ref < tt.cy + 45 * h_ref and tt.x0 - 2 * h_ref < t.cx < retangulos[nome][2]
                 and (faixa is None or faixa(tt.cy) == faixa(t.cy))]
        if not cands:
            return None
        y_max = max(tt.cy for tt, _ in cands)
        fileira = [p for p in cands if y_max - p[0].cy < 2 * h_ref]
        return max(fileira, key=lambda p: p[0].x0)

    det: dict[str, dict] = {}
    for tt, nome in titulos:
        grupo = GRUPOS[nome.lstrip("=")[0]]
        det[nome] = {"desenho": nome, "elementos": nome.split("="), "grupo": grupo,
                     "secao_cm": None, "apoios": [], "armaduras": [], "distribuicao_estribos": [], "_soltos": []}
    for tt, nome in titulos:
        for parte in (x for x in toks if x is tt or (abs(x.x0 - tt.x0) < 60 and RE_TITULO.fullmatch(x.n)
                                                       and "=" in x.n and 0 < x.cy - tt.cy < 4 * h_ref)):
            uso[id(parte)] = f"detalhe {nome}"
    for t in toks:
        if id(t) in uso:
            continue
        d = dono(t)
        if not d:
            continue
        reg = det[d[1]]
        uso[id(t)] = f"detalhe {d[1]}"
        m_est = re.fullmatch(r"(\d+)N(\d+)C/(\d+)", t.n)
        if RE_SECAO.match(t.n) and not t.n.endswith("CM"):
            sec = "x".join(RE_SECAO.match(t.n).group(1, 2))
            reg["secao_cm"] = reg["secao_cm"] or sec
            reg.setdefault("secoes_por_trecho", []).append(sec)
        elif re.fullmatch(r"[PV]\d+", t.n) and reg["grupo"] == "Vigas" and t.n not in reg["elementos"]:
            if t.n not in reg["apoios"]:
                reg["apoios"].append(t.n)
        elif m_est:  # '23 N1 c/16' = 23 estribos N1 a cada 16 cm num trecho
            reg["distribuicao_estribos"].append({"quant": int(m_est.group(1)), "n": int(m_est.group(2)),
                                                 "espacamento_cm": int(m_est.group(3))})
        elif m_prof := re.fullmatch(r"(\d+)\(\+/?-(\d+)\)", t.n):  # sapata: profundidade 150(+/-35)
            reg["profundidade_cm"] = {"valor": int(m_prof.group(1)), "variacao": int(m_prof.group(2))}
        elif m_lance := re.fullmatch(r"(.+?)\s*-\s*(L\d+)", t.text.strip()):  # pilar: 'TERREO 1 - L1'
            reg.setdefault("lances", [])
            if {"pavimento": m_lance.group(1), "lance": m_lance.group(2)} not in reg["lances"]:
                reg["lances"].append({"pavimento": m_lance.group(1), "lance": m_lance.group(2)})
        elif re.fullmatch(r"([PV]\d+)+", t.n) and reg["grupo"] == "Vigas":  # 'P18 V12' juntos
            for e in re.findall(r"[PV]\d+", t.n):
                if e not in reg["apoios"] and e not in reg["elementos"]:
                    reg["apoios"].append(e)
        else:
            ch = _ler_chamada(t.text, idx_por_grupo.get(reg["grupo"], {}))
            if ch:
                reg["armaduras"].append(ch)
            else:
                reg["_soltos"].append(t)
    out: dict[str, list[dict]] = {}
    for reg in det.values():
        # a mesma barra pode aparecer na elevação e no corte; mantém uma de cada
        unicas = []
        for a in reg["armaduras"]:
            if a not in unicas:
                unicas.append(a)
        reg["armaduras"] = sorted(unicas, key=lambda a: a["n"])
        if reg["grupo"] != "Vigas":
            reg.pop("apoios")
        from .completo import separar_soltos
        reg["cotas"], reg["rotulos"], reg["textos"] = separar_soltos(reg.pop("_soltos"))
        out.setdefault(reg["grupo"], []).append(reg)
    # níveis: valor 'redondo' (0 ou |v| >= 100, múltiplo de 10) repetido na maioria dos desenhos do grupo
    for g in out.values():
        freq, vert = {}, {}
        for reg in g:
            for v in {c["valor"] for c in reg["cotas"] if isinstance(c["valor"], (int, float))}:
                freq[v] = freq.get(v, 0) + 1
            for c in reg["cotas"]:
                if c.get("vertical"):
                    vert[c["valor"]] = vert.get(c["valor"], 0) + 1
        # cota vai ao longo do elemento (texto girado); nível é escrito na horizontal
        niveis = {v for v, n in freq.items() if n >= max(2, 0.5 * len(g)) and v % 10 == 0 and (v == 0 or abs(v) >= 100)
                  and vert.get(v, 0) < 0.5 * n}
        for reg in g:
            achados = sorted({c["valor"] for c in reg["cotas"] if c["valor"] in niveis}, reverse=True)
            if achados:
                reg["niveis_cm"] = achados
                reg["cotas"] = [c for c in reg["cotas"] if c["valor"] not in niveis]
    for g in out.values():
        g.sort(key=lambda r: [int(x) for x in re.findall(r"\d+", r["desenho"])[:1]])
    return out


def texto_pos(t: Tok) -> dict:
    """texto + posição no papel em mm (origem no canto superior esquerdo da folha)."""
    k = 25.4 / 200  # coordenadas normalizadas = folha A1 a 200 dpi
    return {"texto": t.text, "x_mm": round(t.cx * k, 1), "y_mm": round(t.cy * k, 1)}


# ----------------------------------------------------------------------------- entrada principal

def analisar(img, tokens_brutos: list[dict], vetorial: bool = False, vetores: list[dict] | None = None) -> dict:
    """vetorial=True: tokens vieram do texto do PDF (exatos) — dispensa as releituras de OCR.
    vetores: linhas/retângulos do PDF com a camada do CAD (eixos, seção dos pilares...)."""
    from . import completo as C

    f = REF_W / img.shape[1]
    if not vetorial:  # imagem: recupera rótulos/coordenadas de eixos que o OCR perde (padrão aprendido dos PDFs)
        from . import recuperar
        from .ocr import _iou_menor
        novos = recuperar.recuperar_eixos(img, tokens_brutos, f)
        tokens_brutos = [t for t in tokens_brutos if not any(_iou_menor(t["box"], n["box"]) > 0.5 for n in novos)] + novos
    if not vetorial and not vetores and any("LOCAC" in norm(t["text"]) for t in tokens_brutos):
        from . import recuperar
        vetores = recuperar.retangulos_pilares(img)  # símbolo do pilar aprendido do PDF
    toks = [Tok(d, f) for d in tokens_brutos]
    C.VETORES = [dict(v, box=[c * f for c in v["box"]]) for v in (vetores or [])]
    if not vetorial:
        toks = refinar(img, toks, f)
    h = C._h_ref(toks)
    uso: dict[int, str] = {}  # id(texto) -> onde entrou no resultado

    # 1. carimbo
    carimbo = ler_carimbo(img, toks, f, vetorial)
    rc = C.regiao_carimbo(toks, f)
    if rc:
        dentro = sorted((t for t in toks if C._dentro(t, rc)), key=lambda t: (round(t.cy / 15), t.cx))
        carimbo["textos"] = [t.text for t in dentro]
        for t in dentro:
            uso[id(t)] = "carimbo"
    # 2. tabelas de aço
    tabelas = extrair_tabelas(toks)
    for i, tab in enumerate(tabelas):
        for t in toks:
            if id(t) not in uso and C._dentro(t, tab["_bbox"]):
                uso[id(t)] = f"tabela de aço {tab['grupo']} #{i}"
    # 3. tabelas gerais (vigas/pilares/lajes, materiais, blocos, legendas)
    gerais = C.tabelas_gerais(toks, uso, h, img, f)
    mats, blocos = C.materiais(gerais)
    # 4. desenhos com título por extenso (formas, locação, cortes, lajes, vigotas)
    mapa = C.Mapa(img, f, C.areas_lidas(toks, uso, h), h)
    faixas_det = {mapa.faixa(t.cy) for t, _ in _titulos_detalhe(toks, tabelas, h)}
    regs = C.regioes_desenhos(img, f, toks, uso, h, mapa, faixas_det)
    desenhos = C.ler_regioes(regs, C.distribuir(toks, regs, uso, h, mapa), uso, h)
    # 5. detalhamentos (vigas, pilares, sapatas) — cada desenho só alcança textos da sua faixa da folha
    detalhes = detalhamentos(toks, tabelas, img, f, uso, faixa=mapa.faixa)
    # 6. o que sobrou
    sem_regiao = [texto_pos(t) for t in toks if id(t) not in uso]

    niveis = niveis_pavimentos(toks)
    elementos = elementos_tabelados(toks, niveis) + sapatas_locacao(toks)
    classe = classificar(toks, carimbo, tabelas, detalhes)

    for tab in tabelas:
        for k in ("_pos", "_titulo", "_bbox"):
            tab.pop(k, None)
        tab["linhas_com_divergencia"] = sum(1 for l in tab["linhas"] if l["conferido"] is False)

    todos = desenhos + [d for g in detalhes.values() for d in g]
    n_cotas = sum(len(d["cotas"]) for d in todos)
    n_soltos = sum(len(d["textos"]) for d in todos)
    total = len(toks)
    cobertura = {
        "textos_na_prancha": total,
        "no_resultado": total,  # todo texto entra em algum lugar
        "estruturados": total - n_cotas - n_soltos - len(sem_regiao),  # campos com significado (inclui rótulos)
        "cotas_com_desenho": n_cotas,  # números de cota, guardados com o desenho e a posição
        "textos_soltos": n_soltos,  # texto não numérico sem campo próprio (meta: 0)
        "sem_regiao": len(sem_regiao),
    }
    cobertura["pct_estruturado"] = round(100 * cobertura["estruturados"] / max(total, 1), 1)
    # rastreio: para onde foi cada texto (usado na auditoria contra as camadas do CAD)
    cotas_ids = {(x["texto"], x["x_mm"], x["y_mm"]) for d in todos for x in d["cotas"]}
    rastreio = []
    for t in toks:
        tp = texto_pos(t)
        destino = "cota" if (tp["texto"], tp["x_mm"], tp["y_mm"]) in cotas_ids else (uso.get(id(t)) or "sem região")
        rastreio.append({"texto": t.text, "camada": t.camada, "destino": destino, "x_mm": tp["x_mm"], "y_mm": tp["y_mm"]})
    from . import modelo3d
    try:
        m3d = modelo3d.montar(desenhos, gerais, C.VETORES, h)
    except Exception as e:  # noqa: BLE001 — o 3D é complementar; não derruba a leitura
        m3d = {"erro": f"{type(e).__name__}: {e}"}
    for d in desenhos:  # posições internas usadas só pelo 3D
        for lst in d["dados"].values():
            if isinstance(lst, list):
                for e in lst:
                    if isinstance(e, dict):
                        e.pop("_px", None)
    return {
        "modelo_3d": m3d,
        "rastreio": rastreio,
        "carimbo": carimbo,
        "classificacao": classe,
        "cobertura": cobertura,
        "niveis": {str(k): v for k, v in sorted(niveis.items())},
        "elementos": elementos,
        "desenhos": desenhos,
        "detalhamentos": detalhes,
        "tabelas_aco": tabelas,
        "tabelas_gerais": gerais,
        "materiais": mats,
        "blocos_enchimento": blocos,
        "sem_regiao": sem_regiao,
        "totais": _totais(tabelas),
    }


def _totais(tabelas) -> dict:
    peso, conc, forma = {}, {}, 0.0
    for t in tabelas:
        for aco, kg in t.get("peso_total_kg", {}).items():
            peso[aco] = round(peso.get(aco, 0) + kg, 1)
        c = t.get("concreto")
        if c and c.get("volume_m3"):
            k = c.get("classe") or "?"
            conc[k] = round(conc.get(k, 0) + c["volume_m3"], 2)
        forma += t.get("forma_m2") or 0
    return {"aco_kg": peso, "aco_total_kg": round(sum(peso.values()), 1),
            "concreto_m3": conc, "forma_m2": round(forma, 2)}
