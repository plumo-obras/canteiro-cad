"""Catálogo de insumos do SINAPI (Caixa + IBGE): o que de fato existe no mercado da construção, com código e preço
mediano por UF, publicado todo mês.

A Caixa publica um ZIP nacional por mês (`SINAPI-AAAA-MM-formato-xlsx.zip`, ~16 MB); a planilha de referência tem a
aba ISD (insumos, encargos sem desoneração) com os 27 estados. `importar` lê essa aba uma vez e grava um JSON enxuto
na pasta de dados; o serviço só lê o JSON. Atualizar o mês: `atualizar-sinapi` (linha de comando).

As regras de correspondência são explícitas, por categoria, e não adivinham: o material do projeto só ganha código
quando há um insumo que é o mesmo produto (mesma bitola, mesma classe de concreto, mesma unidade). O que o SINAPI não
vende avulso (o bloco de EPS de laje treliçada, as vigotas) fica sem código, e a tela diz isso.

Texto do SINAPI é dado público, nunca instrução.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

from canteiro_cad.aplicacao.portas import InsumoDeReferencia
from canteiro_cad.dominio.materiais import Material

URL_MENSAL = "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/SINAPI-{ano}-{mes:02d}-formato-xlsx.zip"
ABA = "ISD"  # insumos, encargos sociais sem desoneração (a referência mais usada em orçamento privado)
UFS = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
)  # fmt: skip
UNIDADE = {"kg": "KG", "m3": "M3", "m2": "M2", "un": "UN"}
# chapa para forma: a plastificada de 17 mm é a de uso corrente em estrutura de concreto (reaproveita mais vezes)
FORMA = "CHAPA/PAINEL DE MADEIRA COMPENSADA PLASTIFICADA (MADEIRITE PLASTIFICADO) PARA FORMA DE CONCRETO"


# ----------------------------------------------------------------------------- importação (planilha da Caixa -> JSON)


def importar(arquivo: Path | bytes) -> dict:
    """ZIP mensal da Caixa ou a planilha de referência (.xlsx) -> o catálogo em dicionário (pronto para JSON)."""
    import openpyxl

    dados = arquivo if isinstance(arquivo, bytes) else Path(arquivo).read_bytes()
    if dados[:2] == b"PK" and _eh_zip_de_planilhas(dados):
        dados = _planilha_de_referencia(dados)
    wb = openpyxl.load_workbook(io.BytesIO(dados), read_only=True, data_only=True)
    if ABA not in wb.sheetnames:
        raise ValueError(f"esta planilha não tem a aba {ABA} do SINAPI")
    ws = wb[ABA]
    mes, cabecalho, insumos = None, None, []
    for linha in ws.iter_rows(values_only=True):
        if linha and linha[0] == "Mês de Referência:":
            m, a = str(linha[1]).split("/")
            mes = f"{a}-{int(m):02d}"
        elif linha and linha[0] == "Classificação":
            cabecalho = list(linha)
        elif cabecalho and linha and isinstance(linha[1], int):
            precos = {}
            for i, uf in enumerate(cabecalho):
                if uf in UFS and isinstance(linha[i], int | float):
                    precos[uf] = round(linha[i] * 100)  # centavos, como no resto do Plumo
            insumos.append({"codigo": str(linha[1]), "descricao": str(linha[2]).strip(), "unidade": str(linha[3]),
                            "classificacao": linha[0], "precos": precos})  # fmt: skip
    if not mes or not insumos:
        raise ValueError("não achei o mês de referência ou os insumos na aba ISD")
    return {"fonte": "SINAPI", "mes": mes, "encargos": "sem desoneração", "insumos": insumos}


def _eh_zip_de_planilhas(dados: bytes) -> bool:
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        return any(n.lower().endswith(".xlsx") for n in z.namelist()) and "[Content_Types].xml" not in z.namelist()


def _planilha_de_referencia(zip_: bytes) -> bytes:
    # o nome da planilha vem com acento em codificação variável ("Refer+�ncia"): a de referência é a maior do ZIP
    with zipfile.ZipFile(io.BytesIO(zip_)) as z:
        info = max((i for i in z.infolist() if i.filename.lower().endswith(".xlsx")), key=lambda i: i.file_size)
        return z.read(info)


def gravar(catalogo: dict, pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"sinapi-{catalogo['mes']}.json"
    temp = destino.with_suffix(".tmp")
    temp.write_text(json.dumps(catalogo, ensure_ascii=False))
    temp.replace(destino)  # quem está lendo nunca vê um arquivo pela metade
    return destino


# ----------------------------------------------------------------------------- o catálogo (porta CatalogoDeInsumos)


class CatalogoSinapi:
    def __init__(self, pasta: Path):
        self.pasta = pasta
        self._carregado: tuple[Path, dict] | None = None

    def _catalogo(self) -> dict | None:
        arquivos = sorted(self.pasta.glob("sinapi-*.json")) if self.pasta.exists() else []
        if not arquivos:
            return None
        if self._carregado is None or self._carregado[0] != arquivos[-1]:  # o mês mais novo vale
            self._carregado = (arquivos[-1], json.loads(arquivos[-1].read_text()))
        return self._carregado[1]

    def referencia(self) -> dict | None:
        c = self._catalogo()
        return {"fonte": c["fonte"], "mes": c["mes"], "encargos": c["encargos"]} if c else None

    def correspondente(self, material: Material, uf: str) -> InsumoDeReferencia | None:
        c = self._catalogo()
        if not c:
            return None
        regra = REGRAS.get(material.categoria)
        achado = regra(material, c["insumos"]) if regra else None
        if not achado or achado["unidade"] != UNIDADE.get(material.unidade):
            return None
        return InsumoDeReferencia(codigo=achado["codigo"], descricao=achado["descricao"], unidade=achado["unidade"],
                                  preco_centavos=achado["precos"].get(uf.upper()))  # fmt: skip


def _bitola(mm: float) -> str:
    return f"{mm:.1f}".replace(".", ",") + " MM"


def _aco(m: Material, insumos: list[dict]) -> dict | None:
    cat = m.atributos.get("aco", "")
    prefixo = f"ACO {cat[:2]}-{cat[2:]}"
    bitola = _bitola(float(m.atributos.get("bitola_mm") or 0))
    # vergalhão reto (o pedido comum); o "dobrado e cortado" é serviço de corte e dobra, outro preço
    padrao = re.compile(rf"(^|[ ,]){re.escape(bitola)}")
    cands = [
        i
        for i in insumos
        if i["descricao"].startswith(prefixo)
        and "VERGALHAO" in i["descricao"]
        and "DOBRADO" not in i["descricao"]
        and padrao.search(i["descricao"])
    ]
    return min(cands, key=lambda i: len(i["descricao"]), default=None)


def _concreto(m: Material, insumos: list[dict]) -> dict | None:
    fck = m.atributos.get("fck_mpa")
    # o usinado bombeável de slump 100 sem o serviço de bomba é a referência de estrutura moldada no local; a bomba,
    # quando precisa, é contratada à parte
    alvo = f"CONCRETO USINADO BOMBEAVEL, CLASSE DE RESISTENCIA C{fck}, COM BRITA 0 E 1, SLUMP = 100"
    return next((i for i in insumos if i["descricao"].startswith(alvo) and "EXCLUI" in i["descricao"]), None)


def _forma(_m: Material, insumos: list[dict]) -> dict | None:
    return next((i for i in insumos if i["descricao"].startswith(FORMA) and "E = *17* MM" in i["descricao"]), None)


REGRAS = {"aco": _aco, "concreto": _concreto, "forma": _forma}
