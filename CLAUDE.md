# canteiro-cad

Microsserviço do Plumo que lê pranchas de cálculo estrutural (PDF do CAD ou imagem) e devolve os dados, o pacote do
projeto e o modelo 3D; também faz a ida e volta do espelho no CAD (DXF). Quem consome é o
[canteiro-web](https://github.com/plumo-obras/canteiro-web), pelo repasse `/srv/tradutor/*`; o produto inteiro sobe
pelo `docker-compose.completo.yml` do [canteiro-api](https://github.com/plumo-obras/canteiro-api).

Leia antes de codar: `README.md` (camadas e comandos) e `docs/integracao-prumo.md` (contrato e fluxo).

## Regras da casa

**O repositório é PÚBLICO.** Nada de segredo, prancha ou dado de cliente em arquivo, teste ou log. Os PDFs de exemplo
ficam fora (`EXEMPLOS_PDF`); teste novo usa modelo inventado (`tests/falsos.py`) com nomes fictícios.

**Camadas: de fora só se importa para dentro.** `dominio` (Python puro) ← `aplicacao` (casos de uso + portas) ←
`infraestrutura` (adaptadores) ← `interfaces` (HTTP, linha de comando). Regra de negócio nova vai no domínio; o que
fala com disco, processo, rede ou biblioteca de leitura é adaptador de uma porta. `tests/test_arquitetura.py` barra
import na direção errada.

**O motor de leitura não muda sem a régua.** `infraestrutura/motor/` foi validado nos PDFs de exemplo (100% das vigas,
barras, linhas de tabela e pilares) e fica fora do formatador. Mexeu nele ou numa dependência travada no `pyproject`:
rode `tests/ponta_a_ponta` e `ferramentas/avaliar.py` com os PDFs antes de abrir o PR.

**O contrato é do Plumo.** Mudou o formato de resultado, modelo 3D ou pacote: suba `VERSAO_CONTRATO`
(`dominio/versao.py`), atualize `docs/modelo3d.schema.json` e `docs/openapi.json` e abra o ajuste no canteiro-web
(`lib/tradutor.ts`) junto. Campo novo opcional não muda a versão.

**O serviço não sabe de usuário.** Autenticação é a chave do serviço (`X-API-Key`); quem confere sessão, obra e papel
é o Next. Não ponha regra de permissão aqui.

**Comentário explica por quê, não o quê.** Português do Brasil no código e nas mensagens.

## Comandos

```bash
uv sync --extra dev -p 3.11
uv run pytest -q
uv run ruff check src tests ferramentas && uv run ruff format --check src tests
uv run uvicorn canteiro_cad.interfaces.http.app:criar_app --factory --reload
docker compose up -d --build                                           # sozinho, http://localhost:8000/docs
EXEMPLOS_PDF=/pasta uv run pytest tests/ponta_a_ponta -q               # com as pranchas de verdade
```
