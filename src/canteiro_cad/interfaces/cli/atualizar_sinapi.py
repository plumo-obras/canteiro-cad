#!/usr/bin/env python3
"""Atualiza o catálogo do SINAPI usado na lista de materiais.

Uso:
    atualizar-sinapi                         # o mês mais novo publicado pela Caixa
    atualizar-sinapi --mes 2026-09           # um mês específico
    atualizar-sinapi --arquivo SINAPI.zip    # o ZIP (ou a planilha de referência) já baixado
A pasta padrão é a do serviço ($TRADUTOR_DADOS/catalogo).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from canteiro_cad.infraestrutura import baixar_sinapi, catalogo_sinapi


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mes", help="AAAA-MM")
    ap.add_argument("--arquivo", type=Path, help="ZIP da Caixa ou a planilha de referência")
    ap.add_argument("--pasta", type=Path, default=Path(os.environ.get("TRADUTOR_DADOS", "dados_servico")) / "catalogo")
    a = ap.parse_args()
    if a.arquivo:
        destino = catalogo_sinapi.gravar(catalogo_sinapi.importar(a.arquivo), a.pasta)
    else:
        destino = baixar_sinapi.baixar(a.pasta, a.mes)
    print(f"Catálogo gravado em {destino}", file=sys.stderr)


if __name__ == "__main__":
    main()
