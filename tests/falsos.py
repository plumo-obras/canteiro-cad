"""Versões em memória das portas, para testar os casos de uso e a API sem disco, processo nem motor de leitura."""

from __future__ import annotations

from canteiro_cad.aplicacao.portas import Desfecho
from canteiro_cad.dominio.traducao import Traducao


class RepositorioEmMemoria:
    def __init__(self) -> None:
        self.traducoes: dict[str, Traducao] = {}
        self.pranchas: dict[str, tuple[str, bytes]] = {}
        self.resultados: dict[str, dict] = {}
        self.planilhas: dict[str, bytes] = {}
        self.falhas: dict[str, str] = {}

    def salvar(self, t):
        self.traducoes[t.id] = t

    def obter(self, tid):
        return self.traducoes.get(tid)

    def todas(self):
        return list(self.traducoes.values())

    def guardar_prancha(self, tid, extensao, conteudo):
        self.pranchas[tid] = (extensao, conteudo)

    def resultado(self, tid):
        return self.resultados[tid]

    def planilha(self, tid):
        return self.planilhas.get(tid)

    def registrar_falha(self, tid, detalhe):
        self.falhas[tid] = detalhe

    def apagar(self, tid):
        for d in (self.traducoes, self.pranchas, self.resultados, self.planilhas, self.falhas):
            d.pop(tid, None)


class LeitorFalso:
    """Devolve o resultado combinado para cada nome de arquivo; `falhar` lista os nomes que dão erro."""

    def __init__(self, repo: RepositorioEmMemoria, resultados: dict[str, dict] | None = None, falhar=()):
        self.repo, self.por_nome, self.falhar, self.lidas = repo, resultados or {}, set(falhar), []

    async def ler(self, tid):
        nome = self.repo.obter(tid).nome
        self.lidas.append(nome)
        if nome in self.falhar:
            return Desfecho(ok=False, segundos=0.1, erro="ValueError: prancha ilegível", detalhe="Traceback ...")
        self.repo.resultados[tid] = {"arquivo": nome, **self.por_nome.get(nome, {})}
        self.repo.planilhas[tid] = b"PK-planilha"
        return Desfecho(ok=True, segundos=0.2)


class NotificadorFalso:
    def __init__(self) -> None:
        self.avisos: list[tuple[str, dict]] = []

    async def avisar(self, url, corpo):
        self.avisos.append((url, corpo))


class EspelhoFalso:
    def __init__(self) -> None:
        self.pedidos = []

    def exportar(self, modelo, obra, ids_base):
        self.pedidos.append((modelo, obra, ids_base))
        return b"0\nSECTION\n"


# uma folha de locação mínima no formato bruto do motor: o bastante para o contrato montar o modelo 3D
LOCACAO = {
    "fonte": "pdf-vetorial",
    "carimbo": {"cliente": "Cliente Inventado", "folha": "01"},
    "classificacao": {"tipo": "Locação", "pavimento": None, "conteudos": ["locação"]},
    "desenhos": [{"tipo": "locacao", "titulo": "Locação de pilares", "dados": {"pilares": [{"elemento": "P1"}]}}],
    "detalhamentos": {},
    "tabelas_aco": [],
    "totais": {},
    "modelo_3d": {
        "pilares": [{"elemento": "P1", "x": 0, "y": 0, "dx": 15, "dy": 30, "z0": -150, "z1": 310, "secao_cm": "15x30"}],
        "sapatas": [{"elemento": "P1", "x": 0, "y": 0, "dx": 80, "dy": 80, "z0": -150, "z1": -120, "estimada": True}],
        "vigas": [],
        "lajes": [],
        "niveis": [0, 310],
        "caixa": [-40, -40, 40, 40],
    },
}
