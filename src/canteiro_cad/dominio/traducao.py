"""A tradução de uma prancha: a entidade que o serviço guarda e o ciclo de vida dela.

Uma prancha entra (PDF do CAD, imagem ou o DXF do espelho editado), espera na fila, é lida e termina concluída ou com
falha. O resultado da leitura fica guardado junto e vale por um tempo (retenção): depois disso a tradução some, e quem
usa o serviço precisa mandar a prancha de novo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .erros import ArquivoRecusado, TraducaoEmAndamento, TraducaoFalhou

# formatos que o motor sabe ler -> tipo de mídia (o DXF é o espelho editado no CAD, que volta para o modelo)
FORMATOS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".dxf": "application/dxf",
}
# o id vira nome de pasta e entra em URL: só letras e números, curto, para nunca sair da pasta de dados
_ID = re.compile(r"^[A-Za-z0-9]{1,40}$")


class Status(StrEnum):
    NA_FILA = "na_fila"
    PROCESSANDO = "processando"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"


def id_valido(tid: str) -> bool:
    return bool(_ID.match(tid or ""))


def extensao_aceita(nome: str | None, conteudo: bytes, max_bytes: int) -> str:
    """Confere o arquivo antes de guardar; devolve a extensão (com ponto) ou recusa com o motivo para a pessoa."""
    ext = ("." + nome.rsplit(".", 1)[-1].lower()) if nome and "." in nome else ""
    if ext not in FORMATOS:
        raise ArquivoRecusado("formato", f"Formato '{ext or '?'}' não suportado. Envie PDF, PNG, JPG ou TIFF.")
    if not conteudo:
        raise ArquivoRecusado("vazio", "Arquivo vazio.")
    if len(conteudo) > max_bytes:
        raise ArquivoRecusado("grande", f"Arquivo maior que {max_bytes // 1024 // 1024} MB.")
    return ext


@dataclass(frozen=True)
class Traducao:
    id: str
    nome: str | None
    tipo: str  # extensão sem o ponto: pdf, png, dxf...
    criada_em: float
    status: Status = Status.NA_FILA
    callback_url: str | None = None
    iniciada_em: float | None = None
    concluida_em: float | None = None
    segundos: float | None = None
    erro: str | None = None
    extra: dict = field(default_factory=dict, compare=False)  # campos de versões futuras, preservados ao regravar

    # ------------------------------------------------------------------ transições (cada uma devolve uma nova)

    def iniciar(self, agora: float) -> Traducao:
        return replace(self, status=Status.PROCESSANDO, iniciada_em=agora)

    def concluir(self, agora: float, segundos: float | None) -> Traducao:
        return replace(self, status=Status.CONCLUIDA, concluida_em=agora, segundos=segundos, erro=None)

    def falhar(self, agora: float, segundos: float | None, erro: str) -> Traducao:
        return replace(self, status=Status.FALHOU, concluida_em=agora, segundos=segundos, erro=erro)

    # ------------------------------------------------------------------ perguntas

    @property
    def terminou(self) -> bool:
        return self.status in (Status.CONCLUIDA, Status.FALHOU)

    def expirou(self, agora: float, retencao_horas: float) -> bool:
        return self.criada_em < agora - retencao_horas * 3600

    def exigir_resultado(self) -> None:
        """O resultado só existe para a tradução concluída; antes disso, diz em que pé ela está."""
        if self.status == Status.FALHOU:
            raise TraducaoFalhou(self.erro)
        if self.status != Status.CONCLUIDA:
            raise TraducaoEmAndamento(self.status)

    # ------------------------------------------------------------------ persistência (formato do trabalho.json)

    def para_dict(self) -> dict:
        d = {
            **self.extra,
            "id": self.id,
            "status": str(self.status),
            "nome": self.nome,
            "tipo": self.tipo,
            "criada_em": self.criada_em,
            "callback_url": self.callback_url,
        }
        for k in ("iniciada_em", "concluida_em", "segundos", "erro"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        return d

    @classmethod
    def de_dict(cls, d: dict) -> Traducao:
        conhecidos = {
            "id",
            "status",
            "nome",
            "tipo",
            "criada_em",
            "callback_url",
            "iniciada_em",
            "concluida_em",
            "segundos",
            "erro",
        }
        return cls(
            id=d["id"],
            nome=d.get("nome"),
            tipo=d.get("tipo", ""),
            criada_em=d.get("criada_em", 0.0),
            status=Status(d.get("status", Status.NA_FILA)),
            callback_url=d.get("callback_url"),
            iniciada_em=d.get("iniciada_em"),
            concluida_em=d.get("concluida_em"),
            segundos=d.get("segundos"),
            erro=d.get("erro"),
            extra={k: v for k, v in d.items() if k not in conhecidos},
        )
