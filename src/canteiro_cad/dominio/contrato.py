"""Contrato de saída do serviço (versão 1.0).

- `resultado(r)`: a leitura completa da prancha, com metadados de versão (sem o rastreio interno, salvo pedido).
- `modelo3d(r)`: o esqueleto estrutural num formato neutro para motores 3D: lista de elementos com
  id, tipo, geometria primitiva (caixa ou prisma de polígono) e propriedades. Unidades em cm.
"""

from __future__ import annotations

from .versao import VERSAO_CONTRATO, VERSAO_SERVICO

SISTEMA_COORDENADAS = {
    "unidade": "cm",
    "x": "horizontal da planta, crescendo com os eixos numerados (1, 2, 3...)",
    "y": "vertical da planta, crescendo dos eixos de baixo para os de cima (coordenadas da locação)",
    "z": "para cima; z = 0 é o nível 0 do projeto",
    "origem": "a mesma das coordenadas escritas na planta de locação",
}


def resultado(r: dict, tid: str, incluir_rastreio: bool = False) -> dict:
    out = {"versao_contrato": VERSAO_CONTRATO, "versao_servico": VERSAO_SERVICO, "id": tid}
    out.update({k: v for k, v in r.items() if k != "rastreio" or incluir_rastreio})
    if isinstance(out.get("modelo_3d"), dict) and out["modelo_3d"].get("pilares"):
        out["modelo_3d"] = modelo3d(r, tid)
    return out


def modelo3d(r: dict, tid: str) -> dict | None:
    m = r.get("modelo_3d")
    if not isinstance(m, dict) or not m.get("pilares"):
        return None
    nomes = {int(k): v for k, v in (r.get("niveis") or {}).items()}
    el = []
    for p in m["pilares"]:
        el.append(
            {
                "id": p["elemento"],
                "tipo": "pilar",
                "geometria": {
                    "forma": "caixa",
                    "centro": [p["x"], p["y"]],
                    "dimensoes": [p["dx"], p["dy"]],
                    "z0": p["z0"],
                    "z1": p["z1"],
                },
                "propriedades": {
                    "secao_cm": p.get("secao_cm"),
                    "morre": p.get("morre", False),
                    "situacao": f"morre no nível {p['z1']}" if p.get("morre") else "passa",
                    **({"armaduras": p["armaduras"]} if p.get("armaduras") else {}),
                },
            }
        )
    for s in m["sapatas"]:
        el.append(
            {
                "id": f"S-{s['elemento']}",
                "tipo": "sapata",
                "geometria": {
                    "forma": "caixa",
                    "centro": [s["x"], s["y"]],
                    "dimensoes": [s["dx"], s["dy"]],
                    "z0": s["z0"],
                    "z1": s["z1"],
                },
                "propriedades": {
                    "pilar": s["elemento"],
                    "h0_cm": s.get("h0_cm"),
                    "dimensao_em_planta_estimada": bool(s.get("estimada")),
                    **({"origem_medida": s["origem_medida"]} if s.get("origem_medida") else {}),
                    **({"armaduras": s["armaduras"]} if s.get("armaduras") else {}),
                },
            }
        )
    cont = {}
    for v in m["vigas"]:
        cont[v["nivel"]] = cont.get(v["nivel"], 0) + 1
        el.append(
            {
                "id": f"V-{v['nivel']}-{cont[v['nivel']]:03d}",
                "tipo": "viga",
                "geometria": {
                    "forma": "caixa",
                    "centro": [v["x"], v["y"]],
                    "dimensoes": [v["dx"], v["dy"]],
                    "z0": v["z0"],
                    "z1": v["z1"],
                },
                "propriedades": {
                    "nivel_cm": v["nivel"],
                    "comprimento_cm": max(v["dx"], v["dy"]),
                    "largura_cm": min(v["dx"], v["dy"]),
                    "altura_cm": round(v["z1"] - v["z0"], 1),
                    "observacao": "trecho de viga reconstruído do traçado da forma",
                },
            }
        )
    for laje in m["lajes"]:
        el.append(
            {
                "id": laje["elemento"],
                "tipo": "laje",
                "geometria": {"forma": "prisma", "poligono": laje["poligono"], "z0": laje["z0"], "z1": laje["z1"]},
                "propriedades": {"area_m2": laje["area_m2"], "espessura_cm": round(laje["z1"] - laje["z0"], 1)},
            }
        )
    zs = [e["geometria"]["z0"] for e in el] + [e["geometria"]["z1"] for e in el]
    x0, y0, x1, y1 = m["caixa"]
    return {
        "versao_contrato": VERSAO_CONTRATO,
        "id": tid,
        "sistema_coordenadas": SISTEMA_COORDENADAS,
        "niveis": [{"cota_cm": n, "nome": nomes.get(n)} for n in m["niveis"]],
        "limites": {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "z0": min(zs), "z1": max(zs)},
        "elementos": el,
        "resumo": {t: sum(1 for e in el if e["tipo"] == t) for t in ("pilar", "sapata", "viga", "laje")},
        "calibracao_formas": m.get("formas", []),
        "avisos": m.get("avisos", []),
    }
