from canteiro_cad.dominio.pacote import combinar


def folha(arquivo, folha, **extra):
    return {
        "arquivo": arquivo,
        "carimbo": {"folha": folha},
        "classificacao": {"pavimento": "Térreo"},
        "desenhos": [],
        **extra,
    }


def test_forma_sem_vigas_lidas_nao_gera_conferencia_vazia():
    forma = folha(
        "f.pdf",
        "1",
        desenhos=[{"tipo": "forma", "titulo": "FORMA DO PAVIMENTO TÉRREO", "dados": {"vigas": [], "lajes": []}}],
    )
    vigas = folha("v.pdf", "2", detalhamentos={"Vigas": [{"desenho": "V1"}]})
    textos = [c["texto"] for c in combinar([("a", forma), ("b", vigas)])["conferencias"]]
    assert not any(t.startswith("Vigas da forma") for t in textos)  # antes: "0/0", marcada como "confere"


def test_forma_com_vigas_continua_conferida():
    forma = folha(
        "f.pdf",
        "1",
        desenhos=[
            {
                "tipo": "forma",
                "titulo": "FORMA DO PAVIMENTO TÉRREO",
                "dados": {"vigas": [{"elemento": "V1"}, {"elemento": "V2"}], "lajes": []},
            }
        ],
    )
    vigas = folha("v.pdf", "2", detalhamentos={"Vigas": [{"desenho": "V1"}]})
    conf = [
        c for c in combinar([("a", forma), ("b", vigas)])["conferencias"] if c["texto"].startswith("Vigas da forma")
    ]
    assert conf == [{"ok": False, "texto": conf[0]["texto"]}] and "1/2" in conf[0]["texto"]
