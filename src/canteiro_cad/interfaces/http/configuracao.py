"""Configuração do serviço, toda por variável de ambiente (todas opcionais; os nomes são os da versão 1.0).

TRADUTOR_DADOS           pasta dos arquivos e resultados (padrão ./dados_servico)
TRADUTOR_WORKERS         processos de leitura em paralelo (padrão 2)
TRADUTOR_API_KEYS        chaves aceitas no cabeçalho X-API-Key, separadas por vírgula (vazio = sem autenticação)
TRADUTOR_MAX_MB          tamanho máximo do arquivo (padrão 60)
TRADUTOR_RETENCAO_HORAS  apaga traduções mais antigas que isso (padrão 72)
TRADUTOR_CORS            origens liberadas, separadas por vírgula (padrão *)
TRADUTOR_WEBHOOK_SEGREDO segredo para assinar os callbacks (cabeçalho X-Tradutor-Assinatura)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _lista(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass(frozen=True)
class Configuracao:
    dados: Path
    workers: int
    chaves: frozenset[str]
    max_bytes: int
    retencao_horas: float
    cors: list[str]
    segredo_webhook: bytes
    sinapi_auto: bool = True

    @classmethod
    def do_ambiente(cls, env: dict[str, str] | None = None) -> Configuracao:
        e = os.environ if env is None else env
        return cls(
            dados=Path(e.get("TRADUTOR_DADOS", "dados_servico")),
            workers=int(e.get("TRADUTOR_WORKERS", "2")),
            chaves=frozenset(_lista(e.get("TRADUTOR_API_KEYS", ""))),
            max_bytes=int(float(e.get("TRADUTOR_MAX_MB", "60")) * 1024 * 1024),
            retencao_horas=float(e.get("TRADUTOR_RETENCAO_HORAS", "72")),
            cors=_lista(e.get("TRADUTOR_CORS", "*")),
            segredo_webhook=e.get("TRADUTOR_WEBHOOK_SEGREDO", "").encode(),
            sinapi_auto=e.get("TRADUTOR_SINAPI_AUTO", "1") != "0",
        )
