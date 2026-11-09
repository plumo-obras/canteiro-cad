"""Região de desenho com título que não diz o tipo ("COBERTURA - L4", "ESPERA P1"): o motor testa os leitores e só
aceita o tipo cujo leitor achou o que define aquele desenho. Textos inventados."""

from canteiro_cad.infraestrutura.motor.analisar import Tok
from canteiro_cad.infraestrutura.motor.completo import ler_regioes

H = 20


def tok(texto, x, y, w=None, h=H):
    return Tok({"text": texto, "conf": 1.0, "box": [x, y, x + (w or 11 * len(texto)), y + h]}, 1.0)


def tipo(toks):
    r = {"titulo": "SEM TIPO NO TÍTULO", "tipo": "desenho", "escala": "1:50", "_manchas": set()}
    return ler_regioes([r], {id(r): toks}, {}, H)[0]["tipo"]


def test_detalhe_com_rotulos_de_pilar_nao_vira_locacao_nem_forma():
    toks = []
    for i in range(6):
        toks += [tok(f"P{i + 1}", 200 + 300 * i, 400), tok("14x30 cm", 200 + 300 * i, 430)]
    toks.append(tok("L4", 2200, 400))  # um rótulo de laje solto não faz do detalhe uma forma
    assert tipo(toks) not in ("locacao", "forma", "corte")


def test_locacao_sem_titulo_com_eixos_e_coordenadas_continua_locacao():
    toks = [tok("A", 100, 300), tok("2569.32", 2000, 300), tok("B", 100, 600), tok("2366.39", 2000, 600)]
    for i, (n, c) in enumerate((("1", "7.49"), ("2", "223.13"), ("3", "398.69"))):
        x = 300 + 400 * i
        toks += [tok(n, x, 1000), tok(c, x - 4, 800, w=18, h=120)]  # coordenada escrita na vertical, acima
    assert tipo(toks) == "locacao"


def test_locacao_sem_coordenada_nao_e_aceita_no_palpite():
    toks = [tok("A", 100, 300), tok("B", 100, 600)] + [tok(n, 300 + 400 * i, 1000) for i, n in enumerate("123")]
    toks += [tok("P1", 400, 320), tok("P2", 800, 620)]
    assert tipo(toks) != "locacao"


def test_forma_sem_titulo_com_vigas_e_pilares_continua_forma():
    toks = [tok("V1", 300, 200), tok("V2", 300, 800), tok("P1", 100, 200), tok("P2", 900, 800)]
    assert tipo(toks) == "forma"


def test_corte_sem_titulo_com_dois_niveis_continua_corte():
    toks = [tok("310", 100, 200), tok("COBERTURA", 100, 230), tok("0", 100, 600), tok("TERREO", 100, 630)]
    assert tipo(toks) == "corte"


def test_escala_nao_conta_como_nivel_de_corte():
    # "ESC 1:30" com um número acima parecia um nível; com ele, o detalhe virava corte de dois níveis
    toks = [tok("33", 100, 200), tok("ESC 1:30", 100, 230), tok("50", 600, 200), tok("VAR", 600, 230)]
    assert tipo(toks) != "corte"
