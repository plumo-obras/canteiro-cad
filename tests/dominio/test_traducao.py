import pytest

from canteiro_cad.dominio.erros import ArquivoRecusado, TraducaoEmAndamento, TraducaoFalhou
from canteiro_cad.dominio.traducao import Status, Traducao, extensao_aceita, id_valido

MB = 1024 * 1024


def test_ciclo_de_vida():
    t = Traducao(id="a1", nome="1.pdf", tipo="pdf", criada_em=100.0)
    assert t.status == Status.NA_FILA and not t.terminou
    t = t.iniciar(101.0)
    assert t.status == Status.PROCESSANDO and t.iniciada_em == 101.0
    with pytest.raises(TraducaoEmAndamento):
        t.exigir_resultado()
    c = t.concluir(105.0, 4.0)
    assert c.terminou and c.segundos == 4.0
    c.exigir_resultado()  # concluída: não levanta
    f = t.falhar(105.0, 1.0, "ValueError: ilegível")
    with pytest.raises(TraducaoFalhou, match="ilegível"):
        f.exigir_resultado()


def test_expira_pela_retencao():
    t = Traducao(id="a1", nome=None, tipo="pdf", criada_em=0.0)
    assert not t.expirou(71 * 3600, 72) and t.expirou(73 * 3600, 72)


def test_ida_e_volta_do_formato_guardado_preserva_campos_desconhecidos():
    d = {
        "id": "a1",
        "status": "concluida",
        "nome": "1.pdf",
        "tipo": "pdf",
        "criada_em": 1.0,
        "callback_url": None,
        "segundos": 2.0,
        "campo_de_versao_futura": 7,
    }
    t = Traducao.de_dict(d)
    assert t.status == Status.CONCLUIDA and t.para_dict()["campo_de_versao_futura"] == 7


@pytest.mark.parametrize("tid,ok", [("abc123", True), ("../x", False), ("", False), ("a" * 41, False), ("a-b", False)])
def test_id_que_vira_pasta(tid, ok):
    assert id_valido(tid) is ok


@pytest.mark.parametrize(
    "nome,conteudo,motivo",
    [
        ("x.docx", b"oi", "formato"),
        (None, b"oi", "formato"),
        ("x.pdf", b"", "vazio"),
        ("x.pdf", b"0" * (MB + 1), "grande"),
    ],
)
def test_arquivo_recusado(nome, conteudo, motivo):
    with pytest.raises(ArquivoRecusado) as e:
        extensao_aceita(nome, conteudo, MB)
    assert e.value.motivo == motivo


def test_arquivo_aceito_devolve_a_extensao():
    assert extensao_aceita("Prancha.PDF", b"%PDF", MB) == ".pdf"
    assert extensao_aceita("espelho.dxf", b"0", MB) == ".dxf"
