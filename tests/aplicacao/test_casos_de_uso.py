import asyncio

import pytest

from canteiro_cad.aplicacao.casos_de_uso import Tradutor
from canteiro_cad.dominio.erros import (
    PedidoInvalido,
    ProjetoSemModelo,
    SemModelo3D,
    TraducaoEmAndamento,
    TraducaoNaoEncontrada,
)
from canteiro_cad.dominio.traducao import Status, Traducao
from tests.falsos import LOCACAO, EspelhoFalso, LeitorFalso, NotificadorFalso, RepositorioEmMemoria


def montar(**kw):
    repo = RepositorioEmMemoria()
    leitor = LeitorFalso(repo, {"locacao.pdf": LOCACAO, "Cliente É.pdf": LOCACAO}, falhar={"ruim.png"})
    notif, esp = NotificadorFalso(), EspelhoFalso()
    ids = iter(f"t{i}" for i in range(1, 100))
    relogio = kw.pop("relogio", lambda: 1000.0)
    return (
        Tradutor(
            repo, leitor, notif, esp, max_bytes=1024, retencao_horas=72, relogio=relogio, novo_id=lambda: next(ids)
        ),
        repo,
        leitor,
        notif,
        esp,
    )


async def test_enviar_e_aguardar_devolve_o_resultado_no_contrato():
    tr, repo, *_ = montar()
    t, resultado = await tr.enviar("locacao.pdf", b"%PDF", aguardar=5)
    assert t.status == Status.CONCLUIDA and resultado["id"] == "t1" and resultado["versao_contrato"] == "1.0"
    assert repo.pranchas["t1"] == (".pdf", b"%PDF")


async def test_sem_aguardar_volta_em_andamento_e_conclui_depois():
    tr, repo, *_ = montar()
    t, resultado = await tr.enviar("locacao.pdf", b"%PDF")
    assert t.status == Status.PROCESSANDO and resultado is None
    with pytest.raises(TraducaoEmAndamento):
        tr.resultado("t1")
    await asyncio.sleep(0)  # a leitura roda em segundo plano
    await asyncio.sleep(0)
    assert tr.consultar("t1").status == Status.CONCLUIDA


async def test_falha_guarda_o_rastro_e_avisa_o_callback():
    tr, repo, _, notif, _ = montar()
    t, _ = await tr.enviar(
        "ruim.png",
        b"png",
        callback_url="https://cliente.inventado/aviso",
        aguardar=5,
        aviso=lambda x: {"id": x.id, "status": str(x.status)},
    )
    assert t.status == Status.FALHOU and "ilegível" in t.erro
    assert repo.falhas["t1"].startswith("Traceback")
    assert notif.avisos == [("https://cliente.inventado/aviso", {"id": "t1", "status": "falhou"})]


async def test_apagada_durante_a_leitura_nao_volta():
    tr, repo, *_ = montar()
    await tr.enviar("locacao.pdf", b"%PDF")
    tr.apagar("t1")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert repo.obter("t1") is None


def test_id_invalido_ou_inexistente_e_nao_encontrada():
    tr, *_ = montar()
    for tid in ("../etc", "naoexiste"):
        with pytest.raises(TraducaoNaoEncontrada):
            tr.consultar(tid)


async def test_modelo3d_e_planilha():
    tr, *_ = montar()
    await tr.enviar("locacao.pdf", b"%PDF", aguardar=5)
    assert tr.modelo3d("t1")["resumo"]["pilar"] == 1
    assert tr.planilha("t1") == (b"PK-planilha", "locacao_traduzido.xlsx")


async def test_prancha_sem_locacao_nao_tem_modelo3d():
    tr, *_ = montar()
    await tr.enviar("outra.pdf", b"%PDF", aguardar=5)
    with pytest.raises(SemModelo3D):
        tr.modelo3d("t1")


async def test_projeto_separa_concluidas_em_andamento_e_sumidas():
    tr, repo, *_ = montar()
    await tr.enviar("locacao.pdf", b"%PDF", aguardar=5)
    repo.salvar(Traducao(id="t9", nome="foto.png", tipo="png", criada_em=1.0, status=Status.PROCESSANDO))
    out = tr.projeto(["t1", "t9", "sumiu"])
    assert out["traducoes"] == ["t1"] and out["nao_encontradas"] == ["sumiu"]
    assert out["em_andamento"] == [{"id": "t9", "status": "processando", "nome": "foto.png", "erro": None}]
    assert out["modelo3d"]["resumo"]["pilar"] == 1


@pytest.mark.parametrize("ids", [[], ["a", "a"], [f"t{i}" for i in range(31)]])
def test_projeto_recusa_lista_ruim(ids):
    tr, *_ = montar()
    with pytest.raises(PedidoInvalido):
        tr.projeto(ids)


async def test_espelho_tem_nome_ascii_e_exige_modelo():
    tr, _, _, _, esp = montar()
    with pytest.raises(ProjetoSemModelo):
        tr.espelho(["naoexiste"])
    await tr.enviar("Cliente É.pdf", b"%PDF", aguardar=5)
    corpo, nome = tr.espelho(["t1"])
    assert corpo.startswith(b"0") and nome == "espelho-ClienteInventado.dxf"
    assert esp.pedidos[0][2] == ["t1"]


async def test_limpar_expiradas():
    agora = [1000.0]
    tr, repo, *_ = montar(relogio=lambda: agora[0])
    await tr.enviar("locacao.pdf", b"%PDF", aguardar=5)
    assert tr.limpar_expiradas() == 0
    agora[0] += 73 * 3600
    assert tr.limpar_expiradas() == 1 and repo.obter("t1") is None
