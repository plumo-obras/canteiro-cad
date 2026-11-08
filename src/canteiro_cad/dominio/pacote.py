"""Pacote do projeto estrutural: junta as folhas traduzidas de um mesmo projeto.

O projeto estrutural chega como um conjunto de pranchas, e cada parte do conjunto é responsável por um pedaço do
modelo (padrão de mercado no Brasil: Eberick, TQS, CypeCAD). Uma mesma folha costuma trazer várias partes (ex.:
"formas e locação" na mesma prancha), então cada folha é reconhecida pelo conteúdo e marca todas as partes que cobre.

Sem estado: recebe os resultados das traduções e devolve o checklist, as conferências entre folhas, os quantitativos
somados e o modelo 3D enriquecido (sapatas com a medida real, pilares e sapatas com a armação).
"""

from __future__ import annotations

import copy
import re
import statistics
import unicodedata

from . import contrato
from .versao import VERSAO_CONTRATO

# papel no pacote -> (nome, pelo que é responsável, obrigatório para o 3D)
PAPEIS = [
    ("locacao", "Locação de pilares e fundações", "posição de cada pilar, eixos e profundidade das sapatas", True),
    ("formas", "Formas dos pavimentos", "vigas, lajes e níveis de cada pavimento", True),
    ("fundacoes", "Detalhamento das fundações", "medida real das sapatas e o aço delas", False),
    ("pilares", "Armação dos pilares", "o aço de cada pilar e os lances", False),
    ("vigas", "Armação das vigas", "o aço das vigas de cada pavimento", False),
    ("lajes", "Armação das lajes / vigotas", "o aço das lajes e as vigotas", False),
    ("cortes", "Cortes", "níveis e pé-direito, para conferência", False),
]
NAO_LIDOS = ["escadas", "reservatório", "blocos sobre estacas", "muros de arrimo"]


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _mesmo_pavimento(a: str, b: str) -> bool:
    a, b = _n(a), _n(b)
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def _expande(nome: str) -> list[str]:
    return [p for p in nome.split("=") if p]


def papeis_da_folha(r: dict) -> dict[str, list[str]]:
    """O que esta folha cobre: papel -> detalhes (pavimentos, quando o papel é por pavimento)."""
    tipos = {d["tipo"] for d in r.get("desenhos", [])}
    det = r.get("detalhamentos", {})
    pav = (r.get("classificacao") or {}).get("pavimento") or ""
    out: dict[str, list[str]] = {}
    if "locacao" in tipos:
        out["locacao"] = []
    formas = [d for d in r.get("desenhos", []) if d["tipo"] == "forma"]
    if formas:
        out["formas"] = [re.sub(r"(?i)^forma do pavimento\s*", "", f["titulo"]).strip() for f in formas]
    if det.get("Sapatas"):
        out["fundacoes"] = []
    if det.get("Pilares"):
        out["pilares"] = []
    if det.get("Vigas"):
        out["vigas"] = [pav] if pav else []
    if tipos & {"armacao_lajes", "vigotas"}:
        out["lajes"] = [pav] if pav else []
    if "corte" in tipos:
        out["cortes"] = []
    return out


def _trios(cotas: list[dict], tol: float = 2.0) -> list[float]:
    """Cotas 'a b a' alinhadas (borda, miolo, borda) = um lado da sapata na planta."""
    cs = [c for c in cotas if isinstance(c.get("valor"), (int, float))]
    lados = []
    for eixo, outro in (("y_mm", "x_mm"), ("x_mm", "y_mm")):
        linhas: dict[float, list[dict]] = {}
        for c in cs:
            k = next((k for k in linhas if abs(k - c[eixo]) <= tol), c[eixo])
            linhas.setdefault(k, []).append(c)
        for lin in linhas.values():
            lin.sort(key=lambda c: c[outro])
            for a, b, d in zip(lin, lin[1:], lin[2:], strict=False):  # trincas vizinhas
                if a["valor"] == d["valor"] and b["valor"] > a["valor"] and d[outro] - a[outro] < 40:
                    lados.append(a["valor"] + b["valor"] + d["valor"])
    return lados


def medidas_sapatas(desenhos: list[dict]) -> dict[str, dict]:
    """Medida em planta de cada sapata. A cota só vale se conferir com o aço (lado = barra + folga); sem cota que
    confira, o lado sai do comprimento da barra mais a folga medida nas outras sapatas da mesma folha."""
    folgas, brutos = [], []
    for d in desenhos:
        barras = sorted({a["comprimento_cm"] for a in d.get("armaduras", [])})[:2]
        lados = _trios(d.get("cotas", []))
        brutos.append((d, barras, lados))
        for lado in lados:
            for b in barras:
                if 0 < lado - b <= 10:
                    folgas.append(lado - b)
    folga = statistics.median(folgas) if folgas else 4
    out = {}
    for d, barras, lados in brutos:
        if len(barras) < 2:
            continue
        medida, origem = [], []
        for b in barras:
            achado = next((lado for lado in lados if abs(lado - b - folga) <= 2), None)
            medida.append(achado if achado is not None else b + folga)
            origem.append("cota" if achado is not None else "aço")
        h0 = next(
            (
                c["valor"]
                for c in d.get("cotas", [])
                if c.get("valor") in (15, 20, 25, 30, 40)
                and c.get("x_mm", 0) > max((x.get("x_mm", 0) for x in d.get("cotas", [])), default=0) - 15
            ),
            None,
        )
        for s in _expande(d["desenho"]):
            out[s] = {
                "lados_cm": sorted(medida),
                "origem": "cotas da planta"
                if origem == ["cota", "cota"]
                else ("cotas e aço" if "cota" in origem else "comprimento do aço"),
                "armaduras": d.get("armaduras", []),
                "h0_cm": h0,
                "desenho": d["desenho"],
            }
    return out


def combinar(folhas: list[tuple[str, dict]]) -> dict:
    """folhas: [(id_da_traducao, resultado)]. Espelhos editados no CAD (DXF) entram por último, sobre o modelo."""
    espelhos = [(t, r) for t, r in folhas if r.get("fonte") == "dxf-espelho"]
    folhas = [(t, r) for t, r in folhas if r.get("fonte") != "dxf-espelho"]
    cobertura: dict[str, list[dict]] = {p[0]: [] for p in PAPEIS}
    for tid, r in folhas:
        c = r.get("carimbo") or {}
        for papel, detalhes in papeis_da_folha(r).items():
            cobertura[papel].append(
                {"id": tid, "arquivo": r.get("arquivo"), "folha": c.get("folha"), "detalhes": detalhes}
            )

    # pavimentos do projeto (pelas formas) para os papéis que são por pavimento
    pavimentos = [p for f in cobertura["formas"] for p in f["detalhes"]]
    com_lajes = [
        re.sub(r"(?i)^forma do pavimento\s*", "", d["titulo"]).strip()
        for _, r in folhas
        for d in r.get("desenhos", [])
        if d["tipo"] == "forma" and d["dados"].get("lajes")
    ]
    pacote = []
    for papel, nome, responsavel, obrig in PAPEIS:
        arqs = cobertura[papel]
        faltam = []
        if papel in ("vigas", "lajes") and pavimentos and arqs:
            tem = [p for a in arqs for p in a["detalhes"]]
            alvo = pavimentos if papel == "vigas" else com_lajes  # laje só onde a forma tem laje
            faltam = [p for p in alvo if not any(_mesmo_pavimento(p, t) for t in tem)]
        situacao = "faltando" if not arqs else ("parcial" if faltam else "coberto")
        pacote.append(
            {
                "papel": papel,
                "nome": nome,
                "responsavel_por": responsavel,
                "obrigatorio_para_3d": obrig,
                "situacao": situacao,
                "arquivos": arqs,
                "faltam_pavimentos": faltam,
            }
        )

    conferencias = []
    # mesmo projeto?
    chaves = {
        (_n((r.get("carimbo") or {}).get("cliente") or ""), _n((r.get("carimbo") or {}).get("local") or ""))
        for _, r in folhas
    }
    conferencias.append(
        {
            "ok": len(chaves) == 1,
            "texto": "Todas as folhas são do mesmo projeto (cliente e local do carimbo)"
            if len(chaves) == 1
            else "Há folhas de projetos diferentes (cliente ou local do carimbo não batem)",
        }
    )
    folhas_num = sorted(str((r.get("carimbo") or {}).get("folha") or "?") for _, r in folhas)
    repetidas = sorted({f for f in folhas_num if folhas_num.count(f) > 1})
    if repetidas:
        conferencias.append({"ok": False, "texto": f"Folha(s) enviada(s) mais de uma vez: {', '.join(repetidas)}"})

    loc = next((r for _, r in folhas if any(d["tipo"] == "locacao" for d in r.get("desenhos", []))), None)
    pil_loc = []
    if loc:
        dloc = next(d for d in loc["desenhos"] if d["tipo"] == "locacao")
        pil_loc = [p["elemento"] for p in dloc["dados"]["pilares"]]
    det_pil = {
        p for _, r in folhas for d in r.get("detalhamentos", {}).get("Pilares", []) for p in _expande(d["desenho"])
    }
    if pil_loc and det_pil:
        sem = [p for p in pil_loc if p not in det_pil]
        conferencias.append(
            {
                "ok": not sem,
                "texto": f"Pilares da locação com armação detalhada: {len(pil_loc) - len(sem)}/{len(pil_loc)}"
                + (f" (sem detalhe: {', '.join(sem)})" if sem else ""),
            }
        )
    desenhos_sap = [d for _, r in folhas for d in r.get("detalhamentos", {}).get("Sapatas", [])]
    sapatas = medidas_sapatas(desenhos_sap) if desenhos_sap else {}
    if pil_loc and sapatas:
        sem = [p for p in pil_loc if "S" + p[1:] not in sapatas]
        conferencias.append(
            {
                "ok": not sem,
                "texto": f"Pilares com sapata detalhada (S12 sob o P12): {len(pil_loc) - len(sem)}/{len(pil_loc)}"
                + (f" (sem sapata: {', '.join(sem)})" if sem else ""),
            }
        )
        if loc:
            dloc = next(d for d in loc["desenhos"] if d["tipo"] == "locacao")
            difs = [
                p["elemento"]
                for p in dloc["dados"]["pilares"]
                if (s := sapatas.get("S" + p["elemento"][1:]))
                and s.get("h0_cm")
                and (p.get("sapata") or {}).get("h0_cm")
                and s["h0_cm"] != p["sapata"]["h0_cm"]
            ]
            conferencias.append(
                {
                    "ok": not difs,
                    "texto": "h0 das sapatas igual na locação e no detalhamento"
                    if not difs
                    else f"h0 diferente entre locação e detalhamento: {', '.join(difs)}",
                }
            )
    # vigas da forma x vigas detalhadas, por pavimento
    for _, r in folhas:
        for f in [d for d in r.get("desenhos", []) if d["tipo"] == "forma"]:
            pav = re.sub(r"(?i)^forma do pavimento\s*", "", f["titulo"]).strip()
            det = {
                v
                for _, r2 in folhas
                if _mesmo_pavimento(pav, (r2.get("classificacao") or {}).get("pavimento") or "")
                for d in r2.get("detalhamentos", {}).get("Vigas", [])
                for v in _expande(d["desenho"])
            }
            if not det:
                continue
            da_forma = [v["elemento"] for v in f["dados"]["vigas"]]
            sem = [v for v in da_forma if v not in det]
            conferencias.append(
                {
                    "ok": not sem,
                    "texto": f"Vigas da forma {pav} com armação detalhada: {len(da_forma) - len(sem)}/{len(da_forma)}"
                    + (f" (sem detalhe nas folhas enviadas: {', '.join(sem)})" if sem else ""),
                }
            )

    # quantitativos somados (cada folha de detalhamento traz a sua tabela de aço)
    aco, conc, forma, por_folha = {}, {}, 0.0, []
    for _, r in folhas:
        t = r.get("totais") or {}
        if not t.get("aco_total_kg") and not t.get("concreto_m3"):
            continue
        for k, v in (t.get("aco_kg") or {}).items():
            aco[k] = round(aco.get(k, 0) + v, 1)
        for k, v in (t.get("concreto_m3") or {}).items():
            conc[k] = round(conc.get(k, 0) + v, 2)
        forma += t.get("forma_m2") or 0
        por_folha.append(
            {
                "folha": (r.get("carimbo") or {}).get("folha"),
                "arquivo": r.get("arquivo"),
                "aco_total_kg": t.get("aco_total_kg"),
                "concreto_m3": t.get("concreto_m3"),
                "forma_m2": t.get("forma_m2"),
            }
        )
    quant = {
        "aco_kg": aco,
        "aco_total_kg": round(sum(aco.values()), 1),
        "concreto_m3": conc,
        "concreto_total_m3": round(sum(conc.values()), 2),
        "forma_m2": round(forma, 2),
        "por_folha": por_folha,
    }

    modelo = None
    if loc and isinstance(loc.get("modelo_3d"), dict) and loc["modelo_3d"].get("pilares"):
        base = copy.deepcopy(loc)
        m = base["modelo_3d"]
        arm_pil = {
            p: d["armaduras"]
            for _, r in folhas
            for d in r.get("detalhamentos", {}).get("Pilares", [])
            for p in _expande(d["desenho"])
        }
        dims_p = {p["elemento"]: (p["dx"], p["dy"]) for p in m["pilares"]}
        reais = 0
        for s in m["sapatas"]:
            info = sapatas.get("S" + s["elemento"][1:])
            if not info:
                continue
            a, b = info["lados_cm"]
            dx, dy = dims_p.get(s["elemento"], (1, 2))
            # o lado maior da sapata acompanha o lado maior do pilar
            s["dx"], s["dy"] = (b, a) if dx >= dy else (a, b)
            s["estimada"] = False
            s["origem_medida"] = info["origem"]
            s["armaduras"] = info["armaduras"]
            reais += 1
        for p in m["pilares"]:
            if p["elemento"] in arm_pil:
                p["armaduras"] = arm_pil[p["elemento"]]
        if reais:
            m["avisos"] = [a for a in m.get("avisos", []) if "estimad" not in a]
            if reais < len(m["sapatas"]):
                m["avisos"].append(
                    f"{len(m['sapatas']) - reais} sapata(s) sem detalhamento nas folhas enviadas: tamanho estimado."
                )
        modelo = contrato.modelo3d(base, "+".join(t for t, _ in folhas))

    edicoes = None
    if espelhos:
        tid_e, re_ = espelhos[-1]  # a edição mais recente vale; as anteriores ficam no histórico do CAD
        if modelo:
            from . import espelho as E

            modelo, mudancas = E.aplicar(modelo, re_["espelho"])
            edicoes = {"id": tid_e, "arquivo": re_.get("arquivo"), "mudancas": mudancas}
            conferencias.append(
                {
                    "ok": True,
                    "texto": f"Modelo editado no CAD ({re_.get('arquivo')}): "
                    + (
                        f"{len(mudancas)} mudança(s) aplicada(s)"
                        if mudancas
                        else "nenhuma mudança em relação às pranchas"
                    ),
                }
            )
            if any(m["mudanca"] == "redimensionado" and m["tipo"] == "pilar" for m in mudancas):
                conferencias.append(
                    {
                        "ok": False,
                        "texto": "Pilar com seção mudada no CAD: a armação do detalhamento era para a seção antiga",
                    }
                )
        else:
            conferencias.append(
                {"ok": False, "texto": "Espelho do CAD enviado, mas falta a locação/formas para aplicar as edições"}
            )

    return {
        "versao_contrato": VERSAO_CONTRATO,
        "traducoes": [t for t, _ in folhas] + [t for t, _ in espelhos],
        "edicoes_cad": edicoes,
        "obra": {
            k: (folhas[0][1].get("carimbo") or {}).get(k) for k in ("cliente", "local", "responsavel", "crea", "data")
        }
        if folhas
        else {},
        "pacote": pacote,
        "nao_lidos_ainda": NAO_LIDOS,
        "conferencias": conferencias,
        "quantitativos": quant,
        "modelo3d": modelo,
        "pronto_para_3d": all(p["situacao"] != "faltando" for p in pacote if p["obrigatorio_para_3d"]),
    }
