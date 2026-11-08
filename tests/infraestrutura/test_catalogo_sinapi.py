"""O catálogo do SINAPI com uma planilha no formato da Caixa (aba ISD), montada no teste com linhas do SINAPI
(dado público). As regras precisam achar o mesmo produto, não um parecido."""

import io
import zipfile
from datetime import date

import openpyxl
import pytest

from canteiro_cad.dominio.materiais import Material
from canteiro_cad.infraestrutura import baixar_sinapi
from canteiro_cad.infraestrutura.catalogo_sinapi import CatalogoSinapi, gravar, importar

LINHAS = [
    ("MATERIAL", 34, "ACO CA-50, 10,0 MM, VERGALHAO", "KG", 6.69, 7.10),
    ("MATERIAL", 43055, "ACO CA-50, 12,5 MM OU 16,0 MM, VERGALHAO", "KG", 5.80, None),
    ("MATERIAL", 43061, "ACO CA-60, 4,2 MM OU 5,0 MM, DOBRADO E CORTADO", "KG", 6.64, 6.64),
    ("MATERIAL", 43059, "ACO CA-60, 4,2 MM, OU 5,0 MM, OU 6,0 MM, OU 7,0 MM, VERGALHAO", "KG", 6.33, 6.40),
    ("MATERIAL", 1525, "CONCRETO USINADO BOMBEAVEL, CLASSE DE RESISTENCIA C30, BRITA 0 E 1, SLUMP = 100 +/- 20 MM, "
     "COM BOMBEAMENTO (DISPONIBILIZACAO DE BOMBA), SEM O LANCAMENTO (NBR 8953)", "M3", 553.97, 560.0),
    ("MATERIAL", 34494, "CONCRETO USINADO BOMBEAVEL, CLASSE DE RESISTENCIA C30, COM BRITA 0 E 1, SLUMP = 100 +/- 20 "
     "MM, EXCLUI SERVICO DE BOMBEAMENTO (NBR 8953)", "M3", 512.63, 520.0),
    ("MATERIAL", 1345, "CHAPA/PAINEL DE MADEIRA COMPENSADA PLASTIFICADA (MADEIRITE PLASTIFICADO) PARA FORMA DE "
     "CONCRETO, DE 2200 X 1100 MM, E = *17* MM", "M2", 69.08, 70.0),
]  # fmt: skip


def _planilha() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ISD"
    ws.append(["SINAPI - Sistema Nacional de Pesquisa de Custos e Índices da Construção Civil"])
    ws.append(["Mês de Referência:", "09/2026"])
    ws.append(["Classificação", "Código do\nInsumo", "Descrição do Insumo", "Unidade", "Origem de\nPreço", "SP", "MG"])
    for cls, cod, desc, un, sp, mg in LINHAS:
        ws.append([cls, cod, desc, un, "C", sp, mg])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _zip_da_caixa() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SINAPI_mao_de_obra_2026_09.xlsx", b"x" * 10)
        z.writestr("SINAPI_Referência_2026_09.xlsx", _planilha())  # a maior é a de referência
    return buf.getvalue()


@pytest.fixture
def catalogo(tmp_path):
    gravar(importar(_zip_da_caixa()), tmp_path)
    return CatalogoSinapi(tmp_path)


def _aco(cat, mm):
    return Material(chave="", categoria="aco", especificacao="", unidade="kg", quantidade=1,
                    atributos={"aco": cat, "bitola_mm": mm})  # fmt: skip


def test_importa_o_zip_mensal_em_centavos(tmp_path):
    c = importar(_zip_da_caixa())
    assert c["mes"] == "2026-09" and len(c["insumos"]) == len(LINHAS)
    assert c["insumos"][0]["precos"] == {"SP": 669, "MG": 710}
    assert gravar(c, tmp_path).name == "sinapi-2026-09.json"


def test_aco_acha_a_bitola_certa_e_nao_o_dobrado(catalogo):
    assert catalogo.correspondente(_aco("CA50", 10.0), "SP").codigo == "34"
    assert catalogo.correspondente(_aco("CA50", 16.0), "SP").codigo == "43055"  # "12,5 MM OU 16,0 MM"
    assert catalogo.correspondente(_aco("CA60", 5.0), "SP").codigo == "43059"  # vergalhão, não "dobrado e cortado"
    assert catalogo.correspondente(_aco("CA50", 8.0), "SP") is None  # não está nesta planilha: sem palpite


def test_concreto_sem_bombeamento_e_forma(catalogo):
    c30 = Material("", "concreto", "", "m3", 1, atributos={"fck_mpa": 30})
    assert catalogo.correspondente(c30, "SP").codigo == "34494"
    forma = Material("", "forma", "", "m2", 1)
    r = catalogo.correspondente(forma, "MG")
    assert r.codigo == "1345" and r.preco_centavos == 7000


def test_uf_sem_preco_e_unidade_diferente(catalogo):
    assert catalogo.correspondente(_aco("CA50", 12.5), "MG").preco_centavos is None
    errado = Material("", "aco", "", "un", 1, atributos={"aco": "CA50", "bitola_mm": 10.0})
    assert catalogo.correspondente(errado, "SP") is None
    assert catalogo.referencia() == {"fonte": "SINAPI", "mes": "2026-09", "encargos": "sem desoneração"}


def test_sem_catalogo(tmp_path):
    c = CatalogoSinapi(tmp_path / "vazio")
    assert c.referencia() is None and c.correspondente(_aco("CA50", 10.0), "SP") is None


def test_meses_candidatos_voltam_desde_o_mes_anterior():
    assert baixar_sinapi.meses_candidatos(date(2026, 2, 5), 3) == [(2026, 1), (2025, 12), (2025, 11)]
