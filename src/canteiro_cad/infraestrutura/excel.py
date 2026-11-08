"""A planilha da prancha traduzida (Excel): uma aba por assunto, para quem confere fora do sistema."""

from __future__ import annotations

import json
from pathlib import Path


def exportar_excel(resultados: list[dict], destino: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    abas = {
        "Pranchas": [
            "arquivo",
            "folha",
            "tipo",
            "pavimento",
            "conteudos",
            "cliente",
            "local",
            "data",
            "responsavel",
            "crea",
            "aco_total_kg",
            "concreto_m3",
            "forma_m2",
        ],
        "Elementos": [
            "arquivo",
            "elemento",
            "tipo",
            "secao_cm",
            "nivel_cm",
            "pavimento",
            "laje_tipo",
            "altura_cm",
            "sapata_h0_cm",
            "sapata_h1_cm",
            "sapata_df_cm",
            "carga_adicional_kgf_m2",
            "carga_acidental_kgf_m2",
            "origem",
        ],
        "Armaduras por desenho": [
            "arquivo",
            "grupo",
            "desenho",
            "secao_cm",
            "apoios",
            "quant",
            "n",
            "diam_mm",
            "comprimento_cm",
            "espacamento_cm",
        ],
        "Relação do aço": ["arquivo", "grupo", "aco", "n", "diam_mm", "quant", "c_unit_cm", "c_total_cm", "conferido"],
        "Resumo do aço": [
            "arquivo",
            "grupo",
            "aco",
            "diam_mm",
            "comprimento_m",
            "peso_kg_mais_10pct",
            "calc_comprimento_m",
            "calc_peso_kg",
        ],
    }
    ws0 = wb.active
    sheets = {}
    for i, (nome, cols) in enumerate(abas.items()):
        ws = ws0 if i == 0 else wb.create_sheet()
        ws.title = nome
        ws.append(cols)
        for cel in ws[1]:
            cel.font = Font(bold=True)
        sheets[nome] = ws

    for r in resultados:
        c, k, t = r["carimbo"], r["classificacao"], r["totais"]
        sheets["Pranchas"].append(
            [
                r["arquivo"],
                c.get("folha"),
                k["tipo"],
                k["pavimento"],
                "; ".join(k["conteudos"]),
                c.get("cliente"),
                c.get("local"),
                c.get("data"),
                c.get("responsavel"),
                c.get("crea"),
                t["aco_total_kg"],
                json.dumps(t["concreto_m3"]),
                t["forma_m2"],
            ]
        )
        for e in r["elementos"]:
            s = e.get("sapata") or {}
            sheets["Elementos"].append(
                [
                    r["arquivo"],
                    e["elemento"],
                    e["tipo"],
                    e.get("secao_cm"),
                    e.get("nivel_cm"),
                    e.get("pavimento"),
                    e.get("laje_tipo"),
                    e.get("altura_cm"),
                    s.get("h0_cm"),
                    s.get("h1_cm"),
                    s.get("df_cm"),
                    e.get("carga_adicional_kgf_m2"),
                    e.get("carga_acidental_kgf_m2"),
                    e["origem"],
                ]
            )
        for g, dets in r["detalhamentos"].items():
            for d in dets:
                for a in d["armaduras"] or [{}]:
                    sheets["Armaduras por desenho"].append(
                        [
                            r["arquivo"],
                            g,
                            d["desenho"],
                            d.get("secao_cm"),
                            " ".join(d.get("apoios", [])),
                            a.get("quant"),
                            a.get("n"),
                            a.get("diam_mm"),
                            a.get("comprimento_cm"),
                            a.get("espacamento_cm"),
                        ]
                    )
        vermelho = PatternFill("solid", fgColor="FFC7CE")
        for tab in r["tabelas_aco"]:
            for lin in tab["linhas"]:
                ws = sheets["Relação do aço"]
                ws.append(
                    [
                        r["arquivo"],
                        tab["grupo"],
                        lin["aco"],
                        lin["n"],
                        lin["diam_mm"],
                        lin["quant"],
                        lin["c_unit_cm"],
                        lin["c_total_cm"],
                        str(lin["conferido"]),
                    ]
                )
                if lin["conferido"] is False:
                    for cel in ws[ws.max_row]:
                        cel.fill = vermelho
            calc = {(x["aco"], x["diam_mm"]): x for x in tab["resumo_calculado"]}
            for x in tab["resumo"]:
                cx = calc.get((x["aco"], x["diam_mm"]), {})
                sheets["Resumo do aço"].append(
                    [
                        r["arquivo"],
                        tab["grupo"],
                        x["aco"],
                        x["diam_mm"],
                        x["comprimento_m"],
                        x["peso_kg_mais_10pct"],
                        cx.get("comprimento_m"),
                        cx.get("peso_kg_mais_10pct"),
                    ]
                )
    _abas_completas(wb, resultados)
    for ws in wb.worksheets:
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(
                45, max(10, max(len(str(c.value or "")) for c in col) + 2)
            )
    wb.save(destino)


def _abas_completas(wb, resultados):
    """Abas com tudo o que a prancha contém (locação, formas, cortes, lajes, vigotas, tabelas, textos soltos)."""
    from openpyxl.styles import Font

    def aba(nome, cols, linhas):
        ws = wb.create_sheet(nome[:31])
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True)
        for lin in linhas:
            ws.append(lin)

    loc_p, loc_e, cotas, formas, cortes, lajes, vigotas, mats, blocos, gerais, estribos, soltos, cob = (
        [] for _ in range(13)
    )
    for r in resultados:
        a = r["arquivo"]
        cb = r.get("cobertura", {})
        cob.append(
            [
                a,
                cb.get("textos_na_prancha"),
                cb.get("no_resultado"),
                cb.get("estruturados"),
                cb.get("cotas_com_desenho"),
                cb.get("textos_soltos"),
                cb.get("sem_regiao"),
                cb.get("pct_estruturado"),
            ]
        )
        for d in r.get("desenhos", []):
            dd, t = d["dados"], d["titulo"]
            for p in dd.get("pilares", []) if d["tipo"] == "locacao" else []:
                s = p.get("sapata") or {}
                ce = p.get("centro_cm") or {}

                def rf(r):
                    return f"{r['eixo']} {r['deslocamento_cm']:+g}" if r else None

                loc_p.append(
                    [
                        a,
                        p["elemento"],
                        p.get("secao_cm"),
                        p.get("eixo_x"),
                        p.get("eixo_y"),
                        p.get("x_cm"),
                        p.get("y_cm"),
                        p.get("posicao"),
                        s.get("h0_cm"),
                        s.get("h1_cm"),
                        s.get("df_cm"),
                        ce.get("x"),
                        ce.get("y"),
                        rf(p.get("ref_x")),
                        rf(p.get("ref_y")),
                        p.get("secao_desenhada_cm"),
                        p.get("secao_confere"),
                        p.get("posicao_geometria"),
                    ]
                )
            for e in dd.get("eixos_numerados", []):
                loc_e.append([a, "numerado (x)", e["eixo"], e["coord_cm"]])
            for e in dd.get("eixos_letras", []):
                loc_e.append([a, "letra (y)", e["eixo"], e["coord_cm"]])
            for c in dd.get("cotas_entre_eixos", []):
                cotas.append([a, c["entre"], c["distancia_cm"], c["cota_escrita"], "sim" if c["confere"] else "NÃO"])
            if d["tipo"] == "forma":
                for v in dd.get("vigas", []):
                    formas.append([a, t, "Viga", v["elemento"], v.get("secao_cm"), None])
                for p in dd.get("pilares", []):
                    formas.append([a, t, "Pilar", p["elemento"], p.get("secao_cm"), p.get("situacao")])
                for laje in dd.get("lajes", []):
                    formas.append([a, t, "Laje", laje["elemento"], None, laje.get("detalhe")])
            if d["tipo"] == "corte":
                for n in dd.get("niveis", []):
                    cortes.append([a, t, "nível", n["nivel"], n["cota_cm"]])
                for e in dd.get("elementos", []):
                    cortes.append([a, t, "elemento", e["elemento"], "morre" if e.get("morre") else None])
            for laje in dd.get("lajes", []) if d["tipo"] == "armacao_lajes" else []:
                lajes.append([a, t, laje["elemento"], laje.get("altura_cm")])
            for v in dd.get("vigotas", []):
                vigotas.append([a, t, v["vigota"], v["comprimento_cm"]])
            for x in d["cotas"]:
                soltos.append([a, t, "cota", x["texto"], x["x_mm"], x["y_mm"]])
            for x in d["textos"]:
                soltos.append([a, t, "texto", x["texto"], x["x_mm"], x["y_mm"]])
        for _g, dets in r["detalhamentos"].items():
            for d in dets:
                for e in d.get("distribuicao_estribos", []):
                    estribos.append([a, d["desenho"], e["quant"], e["n"], e["espacamento_cm"]])
                for x in d.get("cotas", []):
                    soltos.append([a, f"detalhe {d['desenho']}", "cota", x["texto"], x["x_mm"], x["y_mm"]])
                for x in d.get("textos", []):
                    soltos.append([a, f"detalhe {d['desenho']}", "texto", x["texto"], x["x_mm"], x["y_mm"]])
        for x in r.get("sem_regiao", []):
            soltos.append([a, "(sem região)", "texto", x["texto"], x["x_mm"], x["y_mm"]])
        for m in r.get("materiais", []):
            mats.append([a, m["elemento"], m["fck_kgf_cm2"], m["ecs_kgf_cm2"]])
        for b in r.get("blocos_enchimento", []):
            blocos.append([a, b["nome"], b["descricao"], b["hb_cm"], b["bx_cm"], b["by_cm"], b["quantidade"]])
        for tg in r.get("tabelas_gerais", []):
            for i, lin in enumerate(tg["linhas"], 1):
                gerais.append([a, tg["titulo"], i] + list(lin))
        for i, texto in enumerate(r["carimbo"].get("textos", []), 1):
            gerais.append([a, "Carimbo", i, texto])

    aba(
        "Locação - pilares",
        [
            "arquivo",
            "pilar",
            "secao_cm",
            "eixo_x",
            "eixo_y",
            "x_cm",
            "y_cm",
            "posicao",
            "sapata_h0_cm",
            "sapata_h1_cm",
            "sapata_df_cm",
            "centro_x_cm",
            "centro_y_cm",
            "ref_x (eixo + desloc.)",
            "ref_y (eixo + desloc.)",
            "secao_desenhada_cm",
            "secao_confere",
            "origem_geometria",
        ],
        loc_p,
    )
    aba("Locação - eixos", ["arquivo", "tipo", "eixo", "coord_cm"], loc_e)
    aba("Cotas entre eixos", ["arquivo", "entre", "distancia_pelas_coords_cm", "cota_escrita_cm", "confere"], cotas)
    aba("Formas", ["arquivo", "desenho", "tipo", "elemento", "secao_cm", "situacao/detalhe"], formas)
    aba("Cortes", ["arquivo", "corte", "item", "nome", "valor"], cortes)
    aba("Lajes (armação)", ["arquivo", "desenho", "laje", "altura_cm"], lajes)
    aba("Vigotas", ["arquivo", "desenho", "vigota", "comprimento_cm"], vigotas)
    aba("Estribos por trecho", ["arquivo", "desenho", "quant", "n", "espacamento_cm"], estribos)
    aba("Materiais", ["arquivo", "elemento", "fck_kgf_cm2", "ecs_kgf_cm2"], mats)
    aba("Blocos de enchimento", ["arquivo", "nome", "descricao", "hb_cm", "bx_cm", "by_cm", "quantidade"], blocos)
    aba("Tabelas gerais e carimbo", ["arquivo", "tabela", "linha", "celulas..."], gerais)
    aba("Cotas e textos soltos", ["arquivo", "desenho de origem", "tipo", "texto", "x_mm", "y_mm"], soltos)
    aba(
        "Cobertura",
        [
            "arquivo",
            "textos_na_prancha",
            "no_resultado",
            "estruturados",
            "cotas_com_desenho",
            "textos_soltos",
            "sem_regiao",
            "pct_estruturado",
        ],
        cob,
    )
