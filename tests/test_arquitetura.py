"""A regra das camadas, conferida no código: cada camada só importa as de dentro.

    dominio  <-  aplicacao  <-  infraestrutura  <-  interfaces

O domínio não importa framework, disco, rede nem biblioteca de leitura; a aplicação só conhece o domínio (o mundo de
fora entra pelas portas). Quebrar isso costuma ser o primeiro passo para a regra de negócio parar no lugar errado.
"""

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1] / "src" / "canteiro_cad"
CAMADAS = ["dominio", "aplicacao", "infraestrutura", "interfaces"]
# o domínio é Python puro: só a biblioteca padrão
LIVRES_NO_DOMINIO = {"__future__", "copy", "dataclasses", "enum", "math", "re", "statistics", "unicodedata", "typing"}


def _importa(arquivo: Path) -> set[str]:
    nomes = set()
    for no in ast.walk(ast.parse(arquivo.read_text())):
        if isinstance(no, ast.Import):
            nomes |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            nomes.add(no.module)
    return nomes


def _arquivos(camada: str):
    return sorted((RAIZ / camada).rglob("*.py"))


@pytest.mark.parametrize("camada", CAMADAS)
def test_camada_so_importa_as_de_dentro(camada):
    proibidas = CAMADAS[CAMADAS.index(camada) + 1 :]
    for arq in _arquivos(camada):
        for nome in _importa(arq):
            for p in proibidas:
                assert not nome.startswith(f"canteiro_cad.{p}"), f"{arq.relative_to(RAIZ)} importa {nome}"


def test_dominio_e_python_puro():
    for arq in _arquivos("dominio"):
        for nome in _importa(arq):
            raiz = nome.split(".")[0]
            assert raiz == "canteiro_cad" or raiz in LIVRES_NO_DOMINIO, f"{arq.relative_to(RAIZ)} importa {nome}"
