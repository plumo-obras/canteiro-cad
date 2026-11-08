import pytest

from canteiro_cad.dominio.traducao import Status, Traducao
from canteiro_cad.infraestrutura.repositorio_disco import RepositorioEmDisco


def test_guarda_le_lista_e_apaga(tmp_path):
    repo = RepositorioEmDisco(tmp_path)
    t = Traducao(id="abc", nome="1.pdf", tipo="pdf", criada_em=1.0)
    repo.guardar_prancha("abc", ".pdf", b"%PDF")
    repo.salvar(t.iniciar(2.0))
    assert repo.obter("abc").status == Status.PROCESSANDO
    assert repo.prancha("abc").read_bytes() == b"%PDF"
    assert [x.id for x in repo.todas()] == ["abc"]
    assert repo.planilha("abc") is None
    repo.apagar("abc")
    assert repo.obter("abc") is None and not (tmp_path / "abc").exists()


def test_formato_da_versao_1_0_continua_legivel(tmp_path):
    # o volume de quem já rodava o serviço: trabalho.json gravado pela versão antiga
    (tmp_path / "velho").mkdir()
    (tmp_path / "velho" / "trabalho.json").write_text(
        '{"id": "velho", "status": "concluida", "nome": "1.pdf", "tipo": "pdf", "criada_em": 5.0, '
        '"callback_url": null, "iniciada_em": 5.1, "concluida_em": 9.0, "segundos": 3.9}'
    )
    t = RepositorioEmDisco(tmp_path).obter("velho")
    assert t.status == Status.CONCLUIDA and t.segundos == 3.9


def test_id_nunca_sai_da_pasta(tmp_path):
    repo = RepositorioEmDisco(tmp_path)
    assert repo.obter("../fora") is None
    with pytest.raises(ValueError):
        repo.pasta("../fora")
