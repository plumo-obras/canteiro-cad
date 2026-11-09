from canteiro_cad.dominio.pacote import combinar


def folha(arquivo, numero, **extra):
    base = {"arquivo": arquivo, "carimbo": {"folha": numero}, "classificacao": {"pavimento": "Térreo"}, "desenhos": []}
    return {**base, **extra}


def forma(*vigas):
    dados = {"vigas": [{"elemento": v} for v in vigas], "lajes": []}
    return folha("f.pdf", "1", desenhos=[{"tipo": "forma", "titulo": "FORMA DO PAVIMENTO TÉRREO", "dados": dados}])


def conferencias_de_vigas(f):
    vigas = folha("v.pdf", "2", detalhamentos={"Vigas": [{"desenho": "V1"}]})
    return [c for c in combinar([("a", f), ("b", vigas)])["conferencias"] if c["texto"].startswith("Vigas da forma")]


def test_forma_sem_vigas_lidas_avisa_em_vez_de_conferir_zero():
    # antes: "Vigas da forma TÉRREO com armação detalhada: 0/0", marcada como confere
    assert conferencias_de_vigas(forma()) == [
        {"ok": False, "texto": "Vigas da forma TÉRREO: nenhuma viga lida na forma, não deu para conferir"}
    ]


def test_forma_com_vigas_continua_conferida():
    conf = conferencias_de_vigas(forma("V1", "V2"))
    assert len(conf) == 1
    assert conf[0]["ok"] is False and "1/2" in conf[0]["texto"]
