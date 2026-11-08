#!/usr/bin/env python3
"""Identifica pranchas de cálculo estrutural (PDF do CAD, PNG/JPG) direto pela linha de comando, sem o serviço.

Uso:
    python -m canteiro_cad.interfaces.cli.identificar prancha1.pdf prancha2.png [--saida resultado] [--sem-cache]
        [--forcar-ocr]

PDF exportado do CAD é lido direto (texto exato, < 1 s). PNG/JPG ou PDF escaneado passam pelo OCR.
Gera <saida>/<arquivo>.json para cada prancha e <saida>/resultado.xlsx consolidado.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from canteiro_cad.infraestrutura.excel import exportar_excel
from canteiro_cad.infraestrutura.motor.leitura import processar


def imprimir_resumo(r: dict):
    c, k, t = r["carimbo"], r["classificacao"], r["totais"]
    print(f"\n=== {r['arquivo']} — Folha {c.get('folha')} ===")
    print(f"Tipo: {k['tipo']}" + (f" | Pavimento: {k['pavimento']}" if k["pavimento"] else ""))
    print(
        f"Cliente: {c.get('cliente')}\nLocal: {c.get('local')}\nData: {c.get('data')} | "
        f"Resp.: {c.get('responsavel')} (CREA {c.get('crea')})"
    )
    print("Conteúdo:", "; ".join(k["conteudos"]))
    for tab in r["tabelas_aco"]:
        div = tab["linhas_com_divergencia"]
        print(
            f"  Tabela {tab['grupo'] or '?'}: {len(tab['linhas'])} linhas"
            f"{f' ({div} com divergência!)' if div else ' (todas conferidas)' if tab['linhas'] else ''}"
            f" | peso {tab.get('peso_total_kg')} | concreto {tab.get('concreto')} | forma {tab.get('forma_m2')} m²"
        )
    print(
        f"Totais: aço {t['aco_kg']} = {t['aco_total_kg']} kg | concreto {t['concreto_m3']} m³ | "
        f"forma {t['forma_m2']} m²"
    )
    print(
        f"Elementos tabelados: {len(r['elementos'])} | Detalhamentos: "
        + ", ".join(f"{g}: {len(v)}" for g, v in r["detalhamentos"].items())
    )
    for d in r.get("desenhos", []):
        partes = ", ".join(f"{len(v)} {k.replace('_', ' ')}" for k, v in d["dados"].items() if isinstance(v, list))
        print(
            f"  Desenho: {d['titulo']} ({d['escala']}) — {partes or 'sem dados estruturados'}; "
            f"{len(d['cotas'])} cotas, {len(d['textos'])} textos soltos"
        )
        cot = d["dados"].get("cotas_entre_eixos")
        if cot:
            ok = sum(c["confere"] for c in cot)
            print(f"    cotas entre eixos conferidas: {ok}/{len(cot)}")
    for tg in r.get("tabelas_gerais", []):
        print(f"  Tabela '{tg['titulo']}': {len(tg['linhas'])} linhas")
    cb = r.get("cobertura")
    if cb:
        print(
            f"Cobertura: {cb['no_resultado']}/{cb['textos_na_prancha']} textos no resultado — "
            f"{cb['estruturados']} em campos ({cb['pct_estruturado']}%), {cb['cotas_com_desenho']} cotas com o desenho "
            f"de origem, {cb['textos_soltos']} textos soltos, {cb['sem_regiao']} sem região"
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivos", nargs="+", type=Path)
    ap.add_argument("--saida", type=Path, default=Path("resultado"))
    ap.add_argument("--sem-cache", action="store_true", help="refaz o OCR mesmo se já houver cache")
    ap.add_argument("--forcar-ocr", action="store_true", help="usa OCR mesmo em PDF com texto (para comparação)")
    a = ap.parse_args()
    a.saida.mkdir(parents=True, exist_ok=True)

    resultados = []
    with tempfile.TemporaryDirectory() as tmp:
        for arq in a.arquivos:
            print(f"Processando {arq} ...", file=sys.stderr)
            r = processar(arq, not a.sem_cache, Path(tmp), a.forcar_ocr)
            resultados.append(r)
            (a.saida / f"{arq.stem}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))
            imprimir_resumo(r)
    exportar_excel(resultados, a.saida / "resultado.xlsx")
    print(f"\nArquivos gerados em {a.saida.resolve()}/")


if __name__ == "__main__":
    main()
