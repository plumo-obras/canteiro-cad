"""Repositório das traduções em disco: uma pasta por tradução, no mesmo formato desde a versão 1.0 (o volume de quem já
rodava o serviço continua valendo).

    <dados>/<id>/trabalho.json   a tradução (status, datas, erro)
    <dados>/<id>/prancha.<ext>   o arquivo enviado
    <dados>/<id>/resultado.json  a leitura (o motor grava, em outro processo)
    <dados>/<id>/resultado.xlsx  a planilha
    <dados>/<id>/erro.txt        o rastro da falha, para depuração
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path

from canteiro_cad.dominio.traducao import Traducao, id_valido


class RepositorioEmDisco:
    def __init__(self, dados: Path):
        self.dados = dados.resolve()
        self.dados.mkdir(parents=True, exist_ok=True)
        self._trava = threading.Lock()

    def pasta(self, tid: str) -> Path:
        # o id vira caminho: só passa o que o domínio aceita, para nunca sair da pasta de dados
        if not id_valido(tid):
            raise ValueError("id inválido")
        return self.dados / tid

    def salvar(self, t: Traducao) -> None:
        p = self.pasta(t.id)
        p.mkdir(parents=True, exist_ok=True)
        with self._trava:
            (p / "trabalho.json").write_text(json.dumps(t.para_dict(), ensure_ascii=False))

    def obter(self, tid: str) -> Traducao | None:
        try:
            return Traducao.de_dict(json.loads((self.pasta(tid) / "trabalho.json").read_text()))
        except (ValueError, OSError, KeyError):
            return None

    def todas(self) -> Iterator[Traducao]:
        for p in self.dados.iterdir():
            t = self.obter(p.name) if p.is_dir() else None
            if t is not None:
                yield t

    def guardar_prancha(self, tid: str, extensao: str, conteudo: bytes) -> None:
        p = self.pasta(tid)
        p.mkdir(parents=True, exist_ok=True)
        (p / f"prancha{extensao}").write_bytes(conteudo)

    def prancha(self, tid: str) -> Path:
        return next(self.pasta(tid).glob("prancha.*"))

    def resultado(self, tid: str) -> dict:
        return json.loads((self.pasta(tid) / "resultado.json").read_text())

    def planilha(self, tid: str) -> bytes | None:
        a = self.pasta(tid) / "resultado.xlsx"
        return a.read_bytes() if a.exists() else None

    def registrar_falha(self, tid: str, detalhe: str) -> None:
        (self.pasta(tid) / "erro.txt").write_text(detalhe)

    def apagar(self, tid: str) -> None:
        shutil.rmtree(self.pasta(tid), ignore_errors=True)
