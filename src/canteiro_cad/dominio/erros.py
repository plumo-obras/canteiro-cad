"""Erros do domínio, com a mensagem para quem usa o serviço. A interface (HTTP, linha de comando) decide o código."""

from __future__ import annotations


class ErroDoTradutor(Exception):
    """Base: a mensagem já está em linguagem de gente."""


class TraducaoNaoEncontrada(ErroDoTradutor):
    def __init__(self) -> None:
        super().__init__("Tradução não encontrada.")


class TraducaoEmAndamento(ErroDoTradutor):
    def __init__(self, status: str) -> None:
        super().__init__(f"Tradução ainda em andamento (status: {status}).")


class TraducaoFalhou(ErroDoTradutor):
    def __init__(self, erro: str | None) -> None:
        super().__init__(f"A tradução falhou: {erro}")


class SemModelo3D(ErroDoTradutor):
    def __init__(self, mensagem: str = "Esta prancha não tem planta de locação: não há modelo 3D.") -> None:
        super().__init__(mensagem)


class ProjetoSemModelo(ErroDoTradutor):
    def __init__(self) -> None:
        super().__init__("Ainda não há modelo: envie a locação e as formas do projeto.")


class PedidoInvalido(ErroDoTradutor):
    """O pedido não faz sentido (ids repetidos, lista vazia...)."""


class ArquivoRecusado(ErroDoTradutor):
    """O arquivo não pode ser lido; `motivo` diz o porquê: "formato", "vazio" ou "grande"."""

    def __init__(self, motivo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.motivo = motivo
