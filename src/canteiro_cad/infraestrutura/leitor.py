"""Leitor das pranchas em processos separados: cada processo tem o seu motor de OCR, e uma imagem grande ocupa um
núcleo por minutos sem travar a API."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from canteiro_cad.aplicacao.portas import Desfecho

from .repositorio_disco import RepositorioEmDisco


def traduzir(caminho: str, pasta: str, nome: str) -> dict:
    """Roda no processo filho: lê a prancha e grava o resultado na pasta da tradução. Nunca levanta."""
    inicio = time.time()
    pasta_p = Path(pasta)
    try:
        if caminho.lower().endswith(".dxf"):
            # o espelho editado no CAD: leitura exata do DXF, sem OCR; o pacote aplica as mudanças sobre o modelo
            from . import dxf

            esp = dxf.ler(Path(caminho).read_bytes())
            if not esp["elementos"]:
                raise ValueError(
                    "este DXF não tem as camadas PRUMO-* do espelho; baixe o espelho no Projeto 3D e edite nele"
                )
            r = {
                "arquivo": nome,
                "fonte": "dxf-espelho",
                "espelho": esp,
                "carimbo": {},
                "desenhos": [],
                "detalhamentos": {},
                "tabelas_aco": [],
                "totais": {},
                "classificacao": {
                    "tipo": "Espelho editado no CAD",
                    "pavimento": None,
                    "conteudos": [f"{len(esp['elementos'])} elementos do modelo"],
                },
            }
            (pasta_p / "resultado.json").write_text(json.dumps(r, ensure_ascii=False))
            return {"ok": True, "segundos": round(time.time() - inicio, 2)}
        from .excel import exportar_excel
        from .motor.leitura import processar

        with tempfile.TemporaryDirectory() as tmp:
            r = processar(Path(caminho), True, Path(tmp))
        r["arquivo"] = nome
        (pasta_p / "resultado.json").write_text(json.dumps(r, ensure_ascii=False))
        exportar_excel([r], pasta_p / "resultado.xlsx")
        return {"ok": True, "segundos": round(time.time() - inicio, 2)}
    except Exception as e:  # noqa: BLE001 — qualquer falha do motor vira desfecho, não derruba o processo
        return {
            "ok": False,
            "erro": f"{type(e).__name__}: {e}",
            "detalhe": traceback.format_exc()[-2000:],
            "segundos": round(time.time() - inicio, 2),
        }


class LeitorEmProcessos:
    def __init__(self, repositorio: RepositorioEmDisco, workers: int):
        self.repo, self.workers = repositorio, workers
        self._pool: ProcessPoolExecutor | None = None

    def _executor(self) -> ProcessPoolExecutor:
        if self._pool is None:  # só cria os processos na primeira prancha (subir a API fica leve)
            self._pool = ProcessPoolExecutor(max_workers=self.workers)
        return self._pool

    async def ler(self, tid: str) -> Desfecho:
        t = self.repo.obter(tid)
        args = (str(self.repo.prancha(tid)), str(self.repo.pasta(tid)), (t.nome if t else None) or "prancha")
        r = await asyncio.get_running_loop().run_in_executor(self._executor(), traduzir, *args)
        return Desfecho(ok=r["ok"], segundos=r.get("segundos"), erro=r.get("erro"), detalhe=r.get("detalhe", ""))

    def encerrar(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
