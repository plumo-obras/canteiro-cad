"""Baixa o SINAPI do mês na Caixa e grava o catálogo. A Caixa publica o mês M por volta do dia 10 de M+1, então quem
não diz o mês pega o mais novo que já saiu, voltando até 6 meses."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from . import catalogo_sinapi

# o portal da Caixa responde em loop de redirecionamento para quem não parece navegador
CABECALHOS = {"User-Agent": "Mozilla/5.0 (canteiro-cad; catalogo SINAPI)"}


def meses_candidatos(hoje: date, quantos: int = 6) -> list[tuple[int, int]]:
    a, m = hoje.year, hoje.month
    out = []
    for _ in range(quantos):
        m -= 1
        if m == 0:
            a, m = a - 1, 12
        out.append((a, m))
    return out


def baixar(pasta: Path, mes: str | None = None, hoje: date | None = None, timeout: float = 120) -> Path:
    """Grava `sinapi-AAAA-MM.json` em `pasta`; devolve o caminho. Levanta se nenhum mês candidato existir."""
    if mes:
        a, m = (int(x) for x in mes.split("-"))
        candidatos = [(a, m)]
    else:
        candidatos = meses_candidatos(hoje or date.today())
    erros = []
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=CABECALHOS) as c:
        for a, m in candidatos:
            url = catalogo_sinapi.URL_MENSAL.format(ano=a, mes=m)
            r = c.get(url)
            if r.status_code == 200 and r.content[:2] == b"PK":
                return catalogo_sinapi.gravar(catalogo_sinapi.importar(r.content), pasta)
            erros.append(f"{a}-{m:02d}: {r.status_code}")
    dica = (
        " A Caixa limita downloads repetidos (429): tente mais tarde ou baixe o ZIP no navegador e use"
        " `atualizar-sinapi --arquivo`."
        if any(e.endswith(": 429") for e in erros)
        else ""
    )
    raise RuntimeError("SINAPI não encontrado na Caixa (" + ", ".join(erros) + ")." + dica)
