"""Região de desenho com título que não diz o tipo ("COBERTURA - L4", "ESPERA P1"): o motor testa os leitores, mas
não pode adivinhar locação, nem chamar de forma ou corte o que não tem o que os define. Textos inventados."""

from canteiro_cad.infraestrutura.motor.analisar import Tok
from canteiro_cad.infraestrutura.motor.completo import ler_regioes


def tok(texto, x, y, h=20):
    return Tok({"text": texto, "conf": 1.0, "box": [x, y, x + 11 * len(texto), y + h]}, 1.0)


def ler(titulo, toks):
    r = {"titulo": titulo, "tipo": "desenho", "escala": "1:50", "_manchas": set()}
    return ler_regioes([r], {id(r): toks}, {}, 20)[0]


def test_detalhe_com_rotulos_de_pilar_nao_vira_locacao():
    # rótulos de pilar com seção, como num detalhamento: o leitor de locação estrutura isso, mas não é locação
    toks = []
    for i in range(6):
        toks += [tok(f"P{i + 1}", 200 + 300 * i, 400), tok("14x30 cm", 200 + 300 * i, 430)]
    assert ler("COBERTURA - L4", toks)["tipo"] not in ("locacao", "forma", "corte")
