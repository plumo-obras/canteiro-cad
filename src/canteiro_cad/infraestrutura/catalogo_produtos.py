"""Catálogo de insumos pelo canteiro-products (o microsserviço do Plumo com as bases oficiais de custos).

É a mesma porta do catálogo local do SINAPI, com as mesmas regras de correspondência: o serviço de produtos devolve os
candidatos de uma busca por termos e a regra da categoria escolhe o que é o mesmo produto (mesma bitola, mesma classe,
mesma unidade). Com isso o tradutor não guarda nem baixa o SINAPI: quem mantém a base em dia é o serviço de produtos.

Serviço fora do ar vira "sem código" no material, nunca erro na lista.
"""

from __future__ import annotations

import time

import httpx

from canteiro_cad.aplicacao.portas import InsumoDeReferencia
from canteiro_cad.dominio.materiais import Material

from .catalogo_sinapi import FORMA, REGRAS, UNIDADE

BASE = "sinapi"
CACHE_REFERENCIA_S = 600  # o mês muda uma vez por mês; não precisa perguntar a cada material


def _termos(m: Material) -> str | None:
    """A busca que traz os candidatos da regra; a regra é quem decide."""
    if m.categoria == "aco":
        cat = m.atributos.get("aco", "")
        bitola = f"{float(m.atributos.get('bitola_mm') or 0):.1f}".replace(".", " ")
        return f"aco {cat[:2]} {cat[2:]} {bitola} vergalhao"
    if m.categoria == "concreto":
        return f"concreto usinado bombeavel c{m.atributos.get('fck_mpa')} slump 100 exclui"
    if m.categoria == "forma":
        return FORMA.split("(")[0] + " forma concreto 17"
    return None


class CatalogoProdutos:
    def __init__(self, url: str, chave: str = "", timeout: float = 10):
        self.url, self.timeout = url.rstrip("/"), timeout
        self.cabecalhos = {"X-API-Key": chave} if chave else {}
        self._referencia: tuple[float, dict | None] | None = None

    def _get(self, caminho: str, **params) -> object:
        r = httpx.get(f"{self.url}{caminho}", params=params, headers=self.cabecalhos, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def referencia(self) -> dict | None:
        agora = time.monotonic()
        if self._referencia and agora - self._referencia[0] < CACHE_REFERENCIA_S:
            return self._referencia[1]
        try:
            base = next((b for b in self._get("/v1/bases") if b["base"] == BASE), None)
            ref = (
                {"fonte": "SINAPI", "mes": base["meses"][0], "encargos": "sem desoneração"}
                if base and base["meses"]
                else None
            )
        except httpx.HTTPError:
            ref = None
        self._referencia = (agora, ref)
        return ref

    def correspondente(self, material: Material, uf: str) -> InsumoDeReferencia | None:
        regra, termos = REGRAS.get(material.categoria), _termos(material)
        if not regra or not termos:
            return None
        try:
            achados = self._get("/v1/itens", q=termos, tipo="insumo", base=BASE, uf=uf.upper(), limite=50)["itens"]
        except httpx.HTTPError:
            return None
        cands = [{"codigo": i["codigo"], "descricao": i["descricao"], "unidade": i["unidade"],
                  "precos": {uf.upper(): i["preco_centavos"]} if i["preco_centavos"] is not None else {}}
                 for i in achados]  # fmt: skip
        achado = regra(material, cands)
        if not achado or achado["unidade"] != UNIDADE.get(material.unidade):
            return None
        return InsumoDeReferencia(codigo=achado["codigo"], descricao=achado["descricao"], unidade=achado["unidade"],
                                  preco_centavos=achado["precos"].get(uf.upper()))  # fmt: skip
