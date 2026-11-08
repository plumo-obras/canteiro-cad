"""API HTTP do tradutor de pranchas estruturais.

Fluxo: POST /v1/traducoes (arquivo) -> 202 + id  ->  GET /v1/traducoes/{id} até 'concluida'
       -> GET /v1/traducoes/{id}/resultado  |  /modelo3d  |  /excel
Opcional: ?aguardar=N (segundos) devolve o resultado direto se ficar pronto a tempo (bom para PDF);
          callback_url recebe um POST quando terminar (assinado com HMAC-SHA256 se houver segredo).
Projeto: GET /v1/projetos?ids=a,b,c junta as folhas; GET /v1/projetos/espelho.dxf?ids=... o modelo para o CAD.

Aqui só se traduz HTTP <-> casos de uso: validar o pedido, chamar o Tradutor e dar o código certo a cada erro do
domínio. A configuração está em `configuracao.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from canteiro_cad.aplicacao.casos_de_uso import Tradutor
from canteiro_cad.dominio.erros import (
    ArquivoRecusado,
    ErroDoTradutor,
    PedidoInvalido,
    ProjetoSemModelo,
    SemModelo3D,
    TraducaoEmAndamento,
    TraducaoFalhou,
    TraducaoNaoEncontrada,
)
from canteiro_cad.dominio.traducao import Status, Traducao
from canteiro_cad.dominio.versao import VERSAO_CONTRATO, VERSAO_SERVICO
from canteiro_cad.infraestrutura.dxf import EspelhoDxf
from canteiro_cad.infraestrutura.leitor import LeitorEmProcessos
from canteiro_cad.infraestrutura.notificador_http import NotificadorHttp
from canteiro_cad.infraestrutura.repositorio_disco import RepositorioEmDisco

from .configuracao import Configuracao

CODIGO = {
    TraducaoNaoEncontrada: 404,
    SemModelo3D: 404,
    TraducaoEmAndamento: 409,
    ProjetoSemModelo: 409,
    TraducaoFalhou: 422,
    PedidoInvalido: 422,
}
CODIGO_RECUSA = {"formato": 415, "vazio": 400, "grande": 413}


def _publico(t: Traducao, base: str) -> dict:
    """A tradução como o cliente vê: sem a URL do callback, com os links quando concluída."""
    x = {
        "id": t.id,
        "status": str(t.status),
        "nome": t.nome,
        "tipo": t.tipo,
        "criada_em": t.criada_em,
        "iniciada_em": t.iniciada_em,
        "concluida_em": t.concluida_em,
        "segundos": t.segundos,
        "erro": t.erro,
    }
    if t.status == Status.CONCLUIDA:
        x["links"] = {k: f"{base}v1/traducoes/{t.id}/{k}" for k in ("resultado", "modelo3d", "excel")}
    return x


def _ids(ids: str) -> list[str]:
    return [i.strip() for i in ids.split(",") if i.strip()]


def montar_tradutor(cfg: Configuracao) -> tuple[Tradutor, LeitorEmProcessos]:
    """Liga os casos de uso aos adaptadores de verdade (disco, processos, DXF, callback HTTP)."""
    repo = RepositorioEmDisco(cfg.dados)
    leitor = LeitorEmProcessos(repo, cfg.workers)
    tradutor = Tradutor(
        repo,
        leitor,
        NotificadorHttp(cfg.segredo_webhook),
        EspelhoDxf(),
        max_bytes=cfg.max_bytes,
        retencao_horas=cfg.retencao_horas,
    )
    return tradutor, leitor


def criar_app(cfg: Configuracao | None = None, tradutor: Tradutor | None = None) -> FastAPI:
    cfg = cfg or Configuracao.do_ambiente()
    leitor = None
    if tradutor is None:
        tradutor, leitor = montar_tradutor(cfg)

    @contextlib.asynccontextmanager
    async def ciclo(_app: FastAPI) -> AsyncIterator[None]:
        async def limpar_de_hora_em_hora() -> None:
            while True:
                await asyncio.to_thread(tradutor.limpar_expiradas)
                await asyncio.sleep(3600)

        limpeza = asyncio.create_task(limpar_de_hora_em_hora())
        try:
            yield
        finally:
            limpeza.cancel()
            if leitor is not None:
                leitor.encerrar()

    app = FastAPI(
        title="Tradutor de pranchas estruturais",
        version=VERSAO_SERVICO,
        description="Lê pranchas de cálculo estrutural (PDF do CAD ou imagem) e devolve os dados estruturados "
        "e o modelo 3D do esqueleto estrutural. Contrato de saída versão " + VERSAO_CONTRATO + ".",
        lifespan=ciclo,
    )
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ErroDoTradutor)
    async def _erro_do_dominio(_req: Request, e: ErroDoTradutor) -> JSONResponse:
        codigo = CODIGO_RECUSA.get(e.motivo, 400) if isinstance(e, ArquivoRecusado) else CODIGO.get(type(e), 400)
        return JSONResponse({"detail": str(e)}, status_code=codigo)

    def autenticar(request: Request) -> None:
        if cfg.chaves and request.headers.get("x-api-key") not in cfg.chaves:
            raise HTTPException(401, "Envie uma chave válida no cabeçalho X-API-Key.")

    protegido = [Depends(autenticar)]

    @app.get("/v1/saude", tags=["serviço"])
    def saude() -> dict:
        return {
            "status": "ok",
            "versao_servico": VERSAO_SERVICO,
            "versao_contrato": VERSAO_CONTRATO,
            "workers": cfg.workers,
        }

    @app.post("/v1/traducoes", status_code=202, tags=["traduções"], dependencies=protegido)
    async def criar(
        request: Request,
        arquivo: UploadFile = File(..., description="PDF do CAD, PNG ou JPG da prancha, ou o DXF do espelho"),
        callback_url: str | None = Form(None, description="URL que recebe um POST quando terminar"),
        aguardar: float = Query(0, ge=0, le=120, description="Segundos para esperar e já devolver o resultado"),
    ):
        base = str(request.base_url)
        t, resultado = await tradutor.enviar(
            arquivo.filename,
            await arquivo.read(),
            callback_url=callback_url,
            aguardar=aguardar,
            aviso=lambda x: _publico(x, base),
        )
        if resultado is not None:
            return JSONResponse(resultado, status_code=200)
        return JSONResponse(_publico(t, base), status_code=202, headers={"Location": f"{base}v1/traducoes/{t.id}"})

    @app.get("/v1/traducoes/{tid}", tags=["traduções"], dependencies=protegido)
    def status(tid: str, request: Request) -> dict:
        return _publico(tradutor.consultar(tid), str(request.base_url))

    @app.get("/v1/traducoes/{tid}/resultado", tags=["traduções"], dependencies=protegido)
    def resultado(tid: str, incluir_rastreio: bool = Query(False, description="Inclui para onde foi cada texto")):
        return tradutor.resultado(tid, incluir_rastreio)

    @app.get("/v1/traducoes/{tid}/modelo3d", tags=["traduções"], dependencies=protegido)
    def modelo3d(tid: str):
        return tradutor.modelo3d(tid)

    @app.get("/v1/traducoes/{tid}/excel", tags=["traduções"], dependencies=protegido)
    def excel(tid: str) -> Response:
        corpo, nome = tradutor.planilha(tid)
        nome_ascii = nome.encode("ascii", "ignore").decode() or "prancha_traduzido.xlsx"
        return Response(
            corpo,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nome_ascii}"'},
        )

    @app.delete("/v1/traducoes/{tid}", status_code=204, tags=["traduções"], dependencies=protegido)
    def apagar(tid: str) -> None:
        tradutor.apagar(tid)

    @app.get("/v1/projetos", tags=["projeto"], dependencies=protegido)
    def projeto(
        ids: str = Query(..., description="ids das traduções do mesmo projeto, separados por vírgula (até 30)"),
    ):
        """Junta as folhas de um projeto: checklist do pacote (o que cada parte alimenta, quem cobriu, o que falta),
        conferências entre folhas, quantitativos somados e o modelo 3D enriquecido. Não guarda nada."""
        return tradutor.projeto(_ids(ids))

    @app.get("/v1/projetos/espelho.dxf", tags=["projeto"], dependencies=protegido)
    def espelho_dxf(
        ids: str = Query(..., description="ids das traduções do projeto, separados por vírgula"),
    ) -> Response:
        """O modelo do pacote em DXF para editar no CAD (CADCraft, AutoCAD...). Se o pacote já tem uma edição do CAD,
        o espelho sai com ela aplicada: dá para editar, subir, baixar de novo e continuar."""
        corpo, nome = tradutor.espelho(_ids(ids))
        return Response(
            corpo, media_type="application/dxf", headers={"Content-Disposition": f'attachment; filename="{nome}"'}
        )

    return app
