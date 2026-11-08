"""Casos de uso do tradutor. Cada método é uma coisa que quem usa o serviço pede; as regras vêm do domínio e o mundo
de fora entra pelas portas."""

from __future__ import annotations

import asyncio
import time
import unicodedata
import uuid
from collections.abc import Callable

from canteiro_cad.dominio import contrato, materiais, pacote
from canteiro_cad.dominio.erros import (
    PedidoInvalido,
    ProjetoSemModelo,
    SemModelo3D,
    TraducaoNaoEncontrada,
)
from canteiro_cad.dominio.traducao import Status, Traducao, extensao_aceita, id_valido

from .portas import CatalogoDeInsumos, EspelhoCad, LeitorDePranchas, Notificador, RepositorioDeTraducoes

MAX_IDS_POR_PROJETO = 30
UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


class Tradutor:
    def __init__(
        self,
        repositorio: RepositorioDeTraducoes,
        leitor: LeitorDePranchas,
        notificador: Notificador,
        espelho: EspelhoCad,
        catalogo: CatalogoDeInsumos | None = None,
        *,
        max_bytes: int,
        retencao_horas: float,
        relogio: Callable[[], float] = time.time,
        novo_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ):
        self.repo, self.leitor, self.notificador, self.espelho_cad = repositorio, leitor, notificador, espelho
        self.catalogo = catalogo
        self.max_bytes, self.retencao_horas = max_bytes, retencao_horas
        self.agora, self.novo_id = relogio, novo_id
        self._em_curso: set[asyncio.Task] = set()  # referência forte: tarefa solta pode ser coletada no meio

    # ------------------------------------------------------------------ uma prancha

    async def enviar(
        self,
        nome: str | None,
        conteudo: bytes,
        *,
        callback_url: str | None = None,
        aguardar: float = 0,
        aviso: Callable[[Traducao], dict] | None = None,
    ) -> tuple[Traducao, dict | None]:
        """Guarda a prancha e começa a ler. Com `aguardar`, espera até esse tanto e, se ficou pronta, já devolve o
        resultado (PDF do CAD fica pronto em segundos; imagem passa pelo OCR e demora minutos)."""
        ext = extensao_aceita(nome, conteudo, self.max_bytes)
        t = Traducao(id=self.novo_id(), nome=nome, tipo=ext[1:], criada_em=self.agora(), callback_url=callback_url)
        self.repo.guardar_prancha(t.id, ext, conteudo)
        self.repo.salvar(t)
        t = t.iniciar(self.agora())
        self.repo.salvar(t)
        tarefa = asyncio.ensure_future(self._concluir(t, aviso))
        self._em_curso.add(tarefa)
        tarefa.add_done_callback(self._em_curso.discard)
        if aguardar:
            try:
                await asyncio.wait_for(asyncio.shield(tarefa), timeout=aguardar)
            except TimeoutError:
                pass
        t = self.consultar(t.id)
        return t, (contrato.resultado(self.repo.resultado(t.id), t.id) if t.status == Status.CONCLUIDA else None)

    async def _concluir(self, t: Traducao, aviso: Callable[[Traducao], dict] | None) -> None:
        d = await self.leitor.ler(t.id)
        if d.ok:
            t = t.concluir(self.agora(), d.segundos)
        else:
            t = t.falhar(self.agora(), d.segundos, d.erro or "erro desconhecido")
            self.repo.registrar_falha(t.id, d.detalhe)
        if self.repo.obter(t.id) is None:
            return  # apagada enquanto lia: não ressuscita
        self.repo.salvar(t)
        if t.callback_url and aviso:
            await self.notificador.avisar(t.callback_url, aviso(t))

    def consultar(self, tid: str) -> Traducao:
        t = self.repo.obter(tid) if id_valido(tid) else None
        if t is None:
            raise TraducaoNaoEncontrada()
        return t

    def _resultado_bruto(self, tid: str) -> dict:
        self.consultar(tid).exigir_resultado()
        return self.repo.resultado(tid)

    def resultado(self, tid: str, incluir_rastreio: bool = False) -> dict:
        return contrato.resultado(self._resultado_bruto(tid), tid, incluir_rastreio)

    def modelo3d(self, tid: str) -> dict:
        m = contrato.modelo3d(self._resultado_bruto(tid), tid)
        if m is None:
            raise SemModelo3D()
        return m

    def planilha(self, tid: str) -> tuple[bytes, str]:
        """A planilha da prancha e o nome para baixar."""
        t = self.consultar(tid)
        t.exigir_resultado()
        xlsx = self.repo.planilha(tid)
        if xlsx is None:
            raise SemModelo3D("Esta tradução não tem planilha (o espelho do CAD não gera uma).")
        base = (t.nome or "prancha").rsplit(".", 1)[0]
        return xlsx, f"{base}_traduzido.xlsx"

    def apagar(self, tid: str) -> None:
        self.consultar(tid)
        self.repo.apagar(tid)

    # ------------------------------------------------------------------ o projeto (várias pranchas)

    def _folhas(self, ids: list[str]) -> tuple[list[tuple[str, dict]], list[dict], list[str]]:
        if not ids or len(ids) > MAX_IDS_POR_PROJETO or len(set(ids)) != len(ids):
            raise PedidoInvalido(f"Envie de 1 a {MAX_IDS_POR_PROJETO} ids diferentes, separados por vírgula.")
        folhas, andamento, sumidas = [], [], []
        for tid in ids:
            t = self.repo.obter(tid) if id_valido(tid) else None
            if t is None:
                sumidas.append(
                    tid
                )  # leitura apagada (retenção) ou de outro ambiente: sai do pacote sem derrubar o resto
            elif t.status == Status.CONCLUIDA:
                folhas.append((tid, self.repo.resultado(tid)))
            else:
                andamento.append({"id": tid, "status": str(t.status), "nome": t.nome, "erro": t.erro})
        return folhas, andamento, sumidas

    def projeto(self, ids: list[str]) -> dict:
        """Junta as folhas de um projeto: o pacote (o que cada parte alimenta, quem cobriu, o que falta), as
        conferências entre folhas, os quantitativos e o modelo 3D enriquecido. Não guarda nada."""
        folhas, andamento, sumidas = self._folhas(ids)
        out = pacote.combinar(folhas)
        out["em_andamento"] = andamento
        out["nao_encontradas"] = sumidas
        return out

    def espelho(self, ids: list[str]) -> tuple[bytes, str]:
        """O modelo do pacote para editar no CAD, já com a última edição aplicada, e o nome do arquivo."""
        out = self.projeto(ids)
        if not out.get("modelo3d"):
            raise ProjetoSemModelo()
        corpo = self.espelho_cad.exportar(out["modelo3d"], out.get("obra"), ids)
        cliente = (out.get("obra") or {}).get("cliente") or "projeto"
        # o nome vai num cabeçalho HTTP, que só leva ASCII: o "É" de um nome quebrava o download
        ascii_ = unicodedata.normalize("NFKD", cliente).encode("ascii", "ignore").decode()
        return corpo, "espelho-" + ("".join(c for c in ascii_ if c.isalnum())[:30] or "projeto") + ".dxf"

    def materiais(self, ids: list[str], uf: str) -> dict:
        """O que o projeto pede para a estrutura sair do papel, cada material com o insumo que existe no mercado
        (SINAPI) e o preço de referência na UF da obra. É o "precisa" da conta de compras, não a lista do que falta."""
        uf = (uf or "").upper()
        if uf not in UFS:
            raise PedidoInvalido("Informe a UF da obra com duas letras (SP, MG...).")
        folhas, andamento, sumidas = self._folhas(ids)
        lista, avisos = materiais.levantar(folhas)
        referencia = self.catalogo.referencia() if self.catalogo else None
        if referencia is None:
            avisos.append(
                "Sem o catálogo do SINAPI neste serviço: os materiais saem sem código e sem preço de referência"
            )
        itens, total = [], 0
        for m in lista:
            r = self.catalogo.correspondente(m, uf) if self.catalogo and referencia else None
            item = m.para_dict()
            item["referencia"] = None
            if r:
                valor = round(r.preco_centavos * m.quantidade) if r.preco_centavos is not None else None
                item["referencia"] = {"codigo": r.codigo, "descricao": r.descricao, "unidade": r.unidade,
                                      "preco_centavos": r.preco_centavos, "total_centavos": valor}  # fmt: skip
                total += valor or 0
            itens.append(item)
        return {"referencia": {**referencia, "uf": uf} if referencia else None, "itens": itens,
                "total_referencia_centavos": total, "avisos": avisos, "em_andamento": andamento,
                "nao_encontradas": sumidas}  # fmt: skip

    # ------------------------------------------------------------------ manutenção

    def limpar_expiradas(self) -> int:
        """Apaga as traduções mais velhas que a retenção; devolve quantas saíram."""
        agora, n = self.agora(), 0
        for t in list(self.repo.todas()):
            if t.expirou(agora, self.retencao_horas):
                self.repo.apagar(t.id)
                n += 1
        return n
