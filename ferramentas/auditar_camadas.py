"""Audita as REGRAS (as mesmas usadas para PNG) contra as camadas reais do CAD gravadas no PDF.

Roda a análise sem camadas e sem vetores (como se fosse imagem) e compara o destino de cada texto
com a camada do CAD. Uso: uv run python ferramentas/auditar_camadas.py arquivo.pdf [...]
"""

import collections
import sys
from pathlib import Path

from canteiro_cad.infraestrutura.motor import analisar, fonte_pdf


def categoria_camada(c):
    n = analisar.norm(c or "")
    if "COTA" in n or n == "TEXTOSARMADURAS":
        return "cota"
    if "DESCRICAODAARMADURA" in n:
        return "armadura"
    if "RELACAODOACO" in n:
        return "tabela de aço"
    if "TITULO" in n:
        return "título"
    return "outro"


def categoria_destino(d, texto):
    if d == "cota":
        return "cota"
    if d.startswith("tabela de aço"):
        return "tabela de aço"
    if d.startswith("detalhe"):
        return "armadura/detalhe"
    return d.split(" ")[0]


for arq in sys.argv[1:]:
    tokens, img = fonte_pdf.ler_pdf(arq)
    camadas = {(t["text"], round(t["box"][0]), round(t["box"][1])): t["camada"] for t in tokens}
    sem = [{k: v for k, v in t.items() if k != "camada"} for t in tokens]  # esconde as camadas
    r = analisar.analisar(img, sem, vetorial=True)
    mat = collections.Counter()
    erros = collections.defaultdict(list)
    k = 25.4 / 200
    for t, x in zip(sorted(tokens, key=lambda t: (t["box"][1], t["box"][0])), r["rastreio"]):
        pass
    # casa rastreio <-> token pela posição
    idx = {}
    for t in tokens:
        cx, cy = (t["box"][0] + t["box"][2]) / 2 * k, (t["box"][1] + t["box"][3]) / 2 * k
        idx[(t["text"], round(cx, 1), round(cy, 1))] = t["camada"]
    for x in r["rastreio"]:
        cam = idx.get((x["texto"], x["x_mm"], x["y_mm"]))
        esperado = categoria_camada(cam)
        obtido = categoria_destino(x["destino"], x["texto"])
        mat[(esperado, obtido)] += 1
        ok = {
            "cota": obtido == "cota",
            "armadura": obtido == "armadura/detalhe",
            "tabela de aço": obtido == "tabela de aço",
        }.get(esperado, True)
        if not ok:
            erros[(esperado, obtido)].append(f"{x['texto']} [{cam}]")
    print(f"\n== {Path(arq).name}")
    for esp in ("cota", "armadura", "tabela de aço"):
        tot = sum(v for (e, _), v in mat.items() if e == esp)
        okn = sum(
            v
            for (e, o), v in mat.items()
            if e == esp
            and (
                (esp == "cota" and o == "cota")
                or (esp == "armadura" and o == "armadura/detalhe")
                or (esp == "tabela de aço" and o == "tabela de aço")
            )
        )
        if tot:
            print(f"  {esp:14s}: {okn}/{tot} classificados certo")
    falsas_cotas = sum(v for (e, o), v in mat.items() if o == "cota" and e != "cota")
    print(f"  falsas cotas (classificado cota, camada diz outra coisa): {falsas_cotas}")
    for (e, o), lst in sorted(erros.items(), key=lambda kv: -len(kv[1]))[:6]:
        print(f"   esperado {e} -> foi para {o}: {len(lst)}  ex.: {lst[:5]}")
