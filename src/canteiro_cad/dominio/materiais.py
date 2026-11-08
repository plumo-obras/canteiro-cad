"""Os materiais que o projeto estrutural pede: o que se compra para a estrutura sair do papel.

Sai das folhas traduzidas do projeto: o aço das tabelas de armação (por categoria e bitola), o concreto e a forma dos
totais de cada folha, os blocos de enchimento e as vigotas das lajes. É o levantamento do projeto, não a lista de
compras: o que falta comprar é a conta da API (precisa − saldo − a caminho), que recebe esta lista como o "precisa".

A bitola que o CAD escreveu nem sempre é uma que existe: a NBR 7480 fixa as bitolas fabricadas, e um "Ø 9" digitado
errado vira a bitola real mais próxima, com o ajuste anotado para quem confere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# NBR 7480: bitolas fabricadas (mm) e massa linear nominal (kg/m)
BITOLAS = {
    "CA50": (6.3, 8.0, 10.0, 12.5, 16.0, 20.0, 25.0, 32.0, 40.0),
    "CA60": (4.2, 5.0, 6.0, 7.0, 8.0, 9.5),
}
MASSA_KG_POR_M = {
    4.2: 0.109, 5.0: 0.154, 6.0: 0.222, 6.3: 0.245, 7.0: 0.302, 8.0: 0.395, 9.5: 0.558,
    10.0: 0.617, 12.5: 0.963, 16.0: 1.578, 20.0: 2.466, 25.0: 3.853, 32.0: 6.313, 40.0: 9.865,
}  # fmt: skip
# a mesma perda que o quadro de aço do projeto já soma no total (corte, ponta, emenda)
PERDA_ACO = 0.10
# bitola mais longe que isso da fabricada não é erro de digitação: é outra coisa, e não se corrige calado
TOLERANCIA_BITOLA_MM = 1.0


@dataclass(frozen=True)
class Material:
    chave: str  # estável entre leituras: "aco:CA50:10.0", "concreto:C30"...
    categoria: str  # aco | concreto | forma | enchimento | vigota
    especificacao: str  # como se pede no fornecedor: "Aço CA-50 Ø 10,0 mm"
    unidade: str
    quantidade: float
    origem: list[str] = field(default_factory=list)  # folhas de onde saiu
    ajuste: str | None = None  # o que foi corrigido do que estava no CAD
    nota: str | None = None  # o que quem compra precisa saber sobre a quantidade
    atributos: dict = field(default_factory=dict)  # o que o catálogo usa para achar o insumo (bitola, classe...)

    def para_dict(self) -> dict:
        return {
            "chave": self.chave,
            "categoria": self.categoria,
            "especificacao": self.especificacao,
            "unidade": self.unidade,
            "quantidade": self.quantidade,
            "origem": self.origem,
            "ajuste": self.ajuste,
            "nota": self.nota,
            "atributos": self.atributos,
        }


def bitola_fabricada(aco: str, diametro_mm: float) -> tuple[float | None, str | None]:
    """A bitola da NBR 7480 para o que o CAD escreveu, e o ajuste feito (None se já era fabricada)."""
    tabela = BITOLAS.get(_categoria_aco(aco))
    if not tabela or not diametro_mm:
        return None, None
    # no empate (Ø 9 entre 8 e 10) fica a maior: em armadura, a barra mais grossa é o lado seguro
    perto = min(tabela, key=lambda b: (abs(b - diametro_mm), -b))
    if abs(perto - diametro_mm) < 1e-6:
        return perto, None
    if abs(perto - diametro_mm) > TOLERANCIA_BITOLA_MM:
        return None, None
    return perto, f"Ø {_mm(diametro_mm)} não é bitola fabricada (NBR 7480): considerado Ø {_mm(perto)}"


def levantar(folhas: list[tuple[str, dict]]) -> tuple[list[Material], list[str]]:
    """folhas: [(id, resultado da tradução)]. Devolve os materiais e os avisos do que não deu para levantar."""
    avisos: list[str] = []
    aco: dict[tuple[str, float], dict] = {}
    concreto: dict[str, dict] = {}
    forma = {"m2": 0.0, "origem": []}
    blocos: dict[str, dict] = {}
    vigotas: dict[str, dict] = {}

    for _tid, r in folhas:
        if r.get("fonte") == "dxf-espelho":
            continue  # a edição no CAD muda a geometria, não o quadro de aço nem os totais do detalhamento
        nome = _nome_folha(r)
        for tab in r.get("tabelas_aco") or []:
            for lin in tab.get("linhas") or []:
                cat = _categoria_aco(lin.get("aco") or "")
                bitola, ajuste = bitola_fabricada(cat, float(lin.get("diam_mm") or 0))
                if bitola is None:
                    avisos.append(f"{nome}: aço {lin.get('aco')} Ø {lin.get('diam_mm')} sem bitola fabricada próxima")
                    continue
                x = aco.setdefault((cat, bitola), {"m": 0.0, "origem": [], "ajustes": set()})
                x["m"] += (lin.get("c_total_cm") or 0) / 100
                _junta(x["origem"], nome)
                if ajuste:
                    x["ajustes"].add(ajuste)
        for classe, m3 in ((r.get("totais") or {}).get("concreto_m3") or {}).items():
            c = _classe_concreto(classe)
            if not c:
                avisos.append(f"{nome}: concreto '{classe}' sem classe de resistência reconhecida")
                continue
            x = concreto.setdefault(c, {"m3": 0.0, "origem": []})
            x["m3"] += m3
            _junta(x["origem"], nome)
        f = (r.get("totais") or {}).get("forma_m2") or 0
        if f:
            forma["m2"] += f
            _junta(forma["origem"], nome)
        for b in r.get("blocos_enchimento") or []:
            x = blocos.setdefault(b["nome"], {**b, "quantidade": 0, "origem": []})
            x["quantidade"] += b.get("quantidade") or 0
            _junta(x["origem"], nome)
        for d in r.get("desenhos") or []:
            for v in (d.get("dados") or {}).get("vigotas") or []:
                x = vigotas.setdefault(v["vigota"], {"comprimentos": [], "origem": []})
                x["comprimentos"].append(v.get("comprimento_cm"))
                _junta(x["origem"], nome)

    out: list[Material] = []
    for (cat, bitola), x in sorted(aco.items()):
        kg = round(x["m"] * MASSA_KG_POR_M[bitola] * (1 + PERDA_ACO), 1)
        out.append(Material(
            chave=f"aco:{cat}:{bitola}", categoria="aco",
            especificacao=f"Aço {cat[:2]}-{cat[2:]} Ø {_mm(bitola)} mm", unidade="kg", quantidade=kg,
            origem=x["origem"], ajuste="; ".join(sorted(x["ajustes"])) or None,
            atributos={"aco": cat, "bitola_mm": bitola, "metros": round(x["m"], 1), "perda": PERDA_ACO},
        ))  # fmt: skip
    for c, x in sorted(concreto.items()):
        out.append(Material(
            chave=f"concreto:C{c}", categoria="concreto", especificacao=f"Concreto usinado C{c} (fck {c} MPa)",
            unidade="m3", quantidade=round(x["m3"], 2), origem=x["origem"], atributos={"fck_mpa": c},
        ))  # fmt: skip
    if forma["m2"]:
        out.append(Material(
            chave="forma:chapa", categoria="forma", especificacao="Forma de madeira (área de contato)",
            unidade="m2", quantidade=round(forma["m2"], 2), origem=forma["origem"],
            nota="Área de contato das formas; com o reaproveitamento das chapas (3 a 4 usos), compra-se menos",
        ))  # fmt: skip
    for nome, b in sorted(blocos.items()):
        out.append(Material(
            chave=f"enchimento:{nome}", categoria="enchimento", especificacao=b.get("descricao") or f"Bloco {nome}",
            unidade="un", quantidade=b["quantidade"], origem=b["origem"],
            atributos={k: b.get(k) for k in ("hb_cm", "bx_cm", "by_cm")},
        ))  # fmt: skip
    if vigotas:
        # a planta de vigotas dá o tipo e o vão de cada uma, não quantas comprar (isso é do projeto do fornecedor da
        # laje): o item entra para ninguém esquecer dele, com quantidade a confirmar, e não vai sozinho para Compras
        out.append(Material(
            chave="vigota:planta", categoria="vigota",
            especificacao=f"Vigotas pré-moldadas ({len(vigotas)} tipos da planta de vigotas)", unidade="un",
            quantidade=0, origem=sorted({o for v in vigotas.values() for o in v["origem"]}),
            nota="Quantidade a confirmar com o fornecedor da laje",
            atributos={"tipos": {t: [c for c in v["comprimentos"] if c] for t, v in sorted(vigotas.items())}},
        ))  # fmt: skip
    return out, avisos


def _categoria_aco(aco: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", aco.upper())


def _classe_concreto(classe: str) -> int | None:
    m = re.search(r"(\d{2})", classe or "")
    return int(m.group(1)) if m else None


def _mm(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def _nome_folha(r: dict) -> str:
    folha = (r.get("carimbo") or {}).get("folha")
    return f"Folha {folha}" if folha else (r.get("arquivo") or "folha")


def _junta(lista: list[str], nome: str) -> None:
    if nome not in lista:
        lista.append(nome)
