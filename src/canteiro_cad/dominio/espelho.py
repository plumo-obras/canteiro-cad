"""Regras do espelho do modelo no CAD, sem depender de biblioteca de DXF.

O espelho é o modelo do pacote desenhado em planta: um polígono por elemento, numa camada por tipo e nível, e o id
escrito dentro dele. Aqui ficam as decisões: em que camada vai cada elemento, onde vai o id (sem encavalar com os
vizinhos e sempre dentro do polígono, porque é por ele que o id volta quando o CAD descarta o XDATA) e o que mudou
quando o espelho editado volta. Ler e escrever o arquivo DXF é da infraestrutura.
"""

from __future__ import annotations

import math


def camada(e: dict) -> str:
    t, p = e["tipo"], e.get("propriedades", {})
    if t == "pilar":
        return "PRUMO-PILARES-MORREM" if p.get("morre") else "PRUMO-PILARES"
    if t == "sapata":
        return "PRUMO-SAPATAS"
    nivel = p.get("nivel_cm", e["geometria"]["z1"])
    return f"PRUMO-{'VIGAS' if t == 'viga' else 'LAJES'}-{int(round(nivel))}"


def contorno(g: dict) -> list[tuple[float, float]]:
    if g["forma"] == "prisma":
        return [tuple(p) for p in g["poligono"]]
    (cx, cy), (dx, dy) = g["centro"], g["dimensoes"]
    return [
        (cx - dx / 2, cy - dy / 2),
        (cx + dx / 2, cy - dy / 2),
        (cx + dx / 2, cy + dy / 2),
        (cx - dx / 2, cy + dy / 2),
    ]


def rotulos(
    e: dict, pts: list[tuple[float, float]], niveis_viga: list[str]
) -> list[tuple[tuple[float, float], float, float]]:
    """Lugares possíveis para o id do elemento, do preferido ao último: (ponto, altura do texto, rotação em graus).

    No centro do polígono os ids se encavalavam: a sapata S-P1 tem o mesmo centro do pilar P1, e a viga do térreo e a
    da cobertura caem na mesma linha da planta. Então o pilar fica no centro, a sapata embaixo, dentro da borda, e a
    viga ao longo dela, girada, começando num ponto diferente para cada nível. Sempre dentro do polígono.
    """
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    tipo = e["tipo"]
    if tipo == "pilar":
        return [((cx, cy), max(2.0, min(6.0, min(dx, dy) * 0.45)), 0.0)]
    if tipo == "sapata":
        alt = max(3.0, min(10.0, dy * 0.15))
        return [((cx, cy - dy / 2 + alt * 1.2), alt, 0.0), ((cx, cy + dy / 2 - alt * 1.2), alt, 0.0)]
    if tipo == "viga":
        # eixo da viga: a aresta mais longa (vale também para viga inclinada)
        a, b = max(
            zip(pts, pts[1:] + pts[:1], strict=True),
            key=lambda ab: (ab[1][0] - ab[0][0]) ** 2 + (ab[1][1] - ab[0][1]) ** 2,
        )
        vx, vy = b[0] - a[0], b[1] - a[1]
        comp = math.hypot(vx, vy) or 1.0
        ux, uy = vx / comp, vy / comp
        alt = max(2.0, min(6.0, area(pts) / comp * 0.7))
        rot = math.degrees(math.atan2(uy, ux))
        if rot > 90:  # texto sempre legível (da esquerda para a direita, de baixo para cima)
            rot -= 180
        elif rot <= -90:
            rot += 180
        i = niveis_viga.index(camada(e)) if camada(e) in niveis_viga else 0
        inicio = (i + 1) / (len(niveis_viga) + 1) - 0.5  # térreo a 1/3 do vão, cobertura a 2/3...
        fs = [inicio] + [k / 10 for k in (0, -1, 1, -2, 2, -3, 3, -4, 4)]
        return [((cx + ux * comp * f, cy + uy * comp * f), alt, rot) for f in fs]
    return [((cx, cy), 12.0, 0.0)]


def caixa_texto(texto: str, p: tuple[float, float], alt: float, rot: float) -> tuple[float, float, float, float]:
    """Caixa aproximada (alinhada aos eixos) que o texto ocupa na planta."""
    larg, r = len(texto) * alt * 0.8, math.radians(rot)
    mx = abs(larg / 2 * math.cos(r)) + abs(alt / 2 * math.sin(r))
    my = abs(larg / 2 * math.sin(r)) + abs(alt / 2 * math.cos(r))
    return p[0] - mx, p[1] - my, p[0] + mx, p[1] + my


def bate(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def area(pts):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True))) / 2


def dentro(p: tuple[float, float], pts: list[tuple[float, float]]) -> bool:
    """O ponto cai dentro do polígono (paridade do raio horizontal)."""
    x, y, d = p[0], p[1], False
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            d = not d
    return d


def aplicar(modelo: dict, espelho: dict) -> tuple[dict, list[dict]]:
    """Aplica o espelho editado sobre o modelo do pacote. Devolve o modelo novo e a lista do que mudou."""
    base = {e["id"]: e for e in modelo["elementos"]}
    vistos, out, mud = set(), [], []
    for ed in espelho["elementos"]:
        orig = base.get(ed["id"])
        g = dict(ed["geometria"])
        if orig:
            og = orig["geometria"]
            g["z0"] = og["z0"] if g.get("z0") is None else g["z0"]
            g["z1"] = og["z1"] if g.get("z1") is None else g["z1"]
            props = dict(orig["propriedades"])
            if g["forma"] == "caixa" and og["forma"] == "caixa":
                dc = ((g["centro"][0] - og["centro"][0]) ** 2 + (g["centro"][1] - og["centro"][1]) ** 2) ** 0.5
                if dc >= 1:
                    mud.append(
                        {
                            "id": ed["id"],
                            "tipo": ed["tipo"],
                            "mudanca": "movido",
                            "texto": f"{ed['id']} movido {dc:.0f} cm",
                        }
                    )
                if any(abs(a - b) >= 1 for a, b in zip(sorted(g["dimensoes"]), sorted(og["dimensoes"]), strict=True)):
                    antes = "x".join(f"{v:g}" for v in sorted(og["dimensoes"]))
                    depois = "x".join(f"{v:g}" for v in sorted(g["dimensoes"]))
                    mud.append(
                        {
                            "id": ed["id"],
                            "tipo": ed["tipo"],
                            "mudanca": "redimensionado",
                            "texto": f"{ed['id']}: {antes} → {depois} cm",
                        }
                    )
                    if ed["tipo"] == "pilar":
                        props["secao_cm"] = depois
                        props.pop("armaduras", None)  # a armação do detalhamento era para a seção antiga
                        props["armacao_desatualizada"] = True
            elif g["forma"] == "prisma" and og["forma"] == "prisma":
                a0, a1 = area([tuple(p) for p in og["poligono"]]), area([tuple(p) for p in g["poligono"]])
                if abs(a1 - a0) / max(a0, 1) > 0.01:
                    mud.append(
                        {
                            "id": ed["id"],
                            "tipo": ed["tipo"],
                            "mudanca": "redimensionado",
                            "texto": f"{ed['id']}: área {a0 / 1e4:.2f} → {a1 / 1e4:.2f} m²",
                        }
                    )
                    props["area_m2"] = round(a1 / 1e4, 2)
            vistos.add(ed["id"])
        else:
            # elemento novo: altura pelo nível da camada e pelos vizinhos do mesmo tipo
            mesmos = [
                e
                for e in modelo["elementos"]
                if e["tipo"] == ed["tipo"]
                and (
                    ed["nivel_cm"] is None or e["propriedades"].get("nivel_cm", e["geometria"]["z1"]) == ed["nivel_cm"]
                )
            ]
            ref = mesmos[0]["geometria"] if mesmos else {"z0": 0, "z1": ed["nivel_cm"] or 0}
            g["z0"] = ref["z0"] if g.get("z0") is None else g["z0"]
            g["z1"] = ref["z1"] if g.get("z1") is None else g["z1"]
            props = {"novo_no_cad": True}
            if ed["tipo"] == "pilar" and g["forma"] == "caixa":
                props["secao_cm"] = "x".join(f"{v:g}" for v in sorted(g["dimensoes"]))
            if ed["nivel_cm"] is not None:
                props["nivel_cm"] = ed["nivel_cm"]
            if ed["tipo"] == "laje":
                props["area_m2"] = round(area([tuple(p) for p in g["poligono"]]) / 1e4, 2)
            mud.append(
                {
                    "id": ed["id"],
                    "tipo": ed["tipo"],
                    "mudanca": "novo",
                    "texto": f"{ed['tipo']} novo desenhado no CAD ({ed['id']})",
                }
            )
        if ed["tipo"] == "pilar":
            props["morre"] = ed["morre"]
        out.append({"id": ed["id"], "tipo": ed["tipo"], "geometria": g, "propriedades": props})
    for eid, e in base.items():
        if eid not in vistos:
            mud.append({"id": eid, "tipo": e["tipo"], "mudanca": "removido", "texto": f"{eid} removido no CAD"})
    novo = dict(modelo)
    novo["elementos"] = out
    novo["resumo"] = {t: sum(1 for e in out if e["tipo"] == t) for t in ("pilar", "sapata", "viga", "laje")}
    return novo, mud
