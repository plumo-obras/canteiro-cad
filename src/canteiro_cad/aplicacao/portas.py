"""Portas: o que os casos de uso pedem do mundo de fora. A infraestrutura implementa; os testes trocam por versões em
memória. Nada aqui sabe de FastAPI, disco, processo ou DXF."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from canteiro_cad.dominio.traducao import Traducao


@dataclass(frozen=True)
class Desfecho:
    """Como terminou a leitura de uma prancha."""

    ok: bool
    segundos: float | None = None
    erro: str | None = None
    detalhe: str = ""  # o rastro técnico da falha, guardado para depuração e nunca devolvido ao cliente


class RepositorioDeTraducoes(Protocol):
    def salvar(self, t: Traducao) -> None: ...

    def obter(self, tid: str) -> Traducao | None: ...

    def todas(self) -> Iterable[Traducao]: ...

    def guardar_prancha(self, tid: str, extensao: str, conteudo: bytes) -> None: ...

    def resultado(self, tid: str) -> dict: ...

    def planilha(self, tid: str) -> bytes | None: ...

    def registrar_falha(self, tid: str, detalhe: str) -> None: ...

    def apagar(self, tid: str) -> None: ...


class LeitorDePranchas(Protocol):
    async def ler(self, tid: str) -> Desfecho:
        """Lê a prancha guardada para `tid` e deixa o resultado no repositório. Não levanta: falha vira Desfecho."""
        ...


class Notificador(Protocol):
    async def avisar(self, url: str, corpo: dict) -> None:
        """Avisa quem pediu (callback). Falhar não pode derrubar nada: o cliente ainda consulta o status."""
        ...


class EspelhoCad(Protocol):
    def exportar(self, modelo: dict, obra: dict | None, ids_base: list[str]) -> bytes:
        """O modelo em planta no formato que o CAD abre (DXF)."""
        ...
