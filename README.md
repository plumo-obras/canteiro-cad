# canteiro-cad

Microsserviço do Plumo que **traduz pranchas de cálculo estrutural** (PDF exportado do CAD ou imagem) em dados
estruturados, no **pacote do projeto** (o que cada prancha cobre e o que falta) e no **modelo 3D do esqueleto da obra**
(sapatas, pilares, vigas por nível, lajes) que a tela *Projeto 3D* do [canteiro-web](https://github.com/plumo-obras/canteiro-web)
desenha. Também faz a ida e volta com o CAD: o modelo sai em DXF, a pessoa edita e o DXF salvo volta para o modelo.
Padrão Eberick/AutoCAD.

- Fluxo, erros e exemplos de cliente: [`docs/integracao-prumo.md`](docs/integracao-prumo.md)
- Contrato do 3D: [`docs/modelo3d.schema.json`](docs/modelo3d.schema.json) · OpenAPI: [`docs/openapi.json`](docs/openapi.json)

## Subir

```bash
docker compose up -d --build        # sozinho: http://localhost:8000/docs
```

No produto inteiro, com os repositórios clonados lado a lado (`canteiro-api/ canteiro-agente/ canteiro-web/
canteiro-cad/`), de dentro do canteiro-api:

```bash
docker compose -f docker-compose.yml -f docker-compose.completo.yml up -d --build
```

O navegador nunca fala com este serviço: o Next do canteiro-web repassa por `/srv/tradutor/*`, confere a sessão e põe a
chave (`TRADUTOR_CHAVE` lá = uma das `TRADUTOR_API_KEYS` aqui). O serviço não conhece usuário, obra nem banco.

| Variável | Padrão | |
|---|---|---|
| `TRADUTOR_API_KEYS` | vazio (sem autenticação) | chaves aceitas em `X-API-Key`, separadas por vírgula |
| `TRADUTOR_WORKERS` | 2 | processos de leitura em paralelo (imagem ocupa um núcleo por minutos) |
| `TRADUTOR_MAX_MB` | 60 | maior arquivo aceito |
| `TRADUTOR_RETENCAO_HORAS` | 72 | depois disso a tradução é apagada |
| `TRADUTOR_CORS` | `*` | origens liberadas |
| `TRADUTOR_WEBHOOK_SEGREDO` | vazio | assina o callback (`X-Tradutor-Assinatura: sha256=…`) |
| `TRADUTOR_DADOS` | `/dados` na imagem | onde ficam pranchas, resultados e o catálogo do SINAPI (volume) |
| `TRADUTOR_SINAPI_AUTO` | 1 | sem catálogo do SINAPI, baixa o mês mais novo da Caixa ao subir |

## Materiais do projeto e o SINAPI

`GET /v1/projetos/materiais?ids=...&uf=SP` devolve o que o projeto pede para a estrutura sair do papel: o aço por
categoria e bitola (a bitola do CAD vai para a fabricada da NBR 7480; um Ø digitado errado vira a real mais próxima,
com o ajuste anotado), o concreto por classe, a área de forma, os blocos de enchimento e as vigotas. Cada material vem
com o insumo do **SINAPI** que é o mesmo produto (código, descrição, unidade) e o preço de referência na UF, em
centavos. O que o SINAPI não vende avulso (bloco de EPS de laje, vigota) fica sem código, e a lista diz isso.

É o "precisa" da conta de compras: o que falta comprar é a API do Plumo que calcula (precisa − saldo − a caminho).

O catálogo é o arquivo mensal da Caixa (`SINAPI-AAAA-MM-formato-xlsx.zip`, aba ISD). O serviço baixa sozinho ao subir
quando não há catálogo; para trocar o mês:

```bash
uv run atualizar-sinapi                      # o mês mais novo publicado
uv run atualizar-sinapi --mes 2026-09        # um mês específico
uv run atualizar-sinapi --arquivo SINAPI.zip # sem internet: o ZIP já baixado
```

## Arquitetura

Clean Architecture com o domínio no centro. Cada camada só importa as de dentro, e `tests/test_arquitetura.py` confere
isso no código.

```
src/canteiro_cad/
  dominio/          regras puras, só biblioteca padrão
    traducao.py       a entidade Tradução: formatos aceitos, ciclo de vida (na fila → lendo → concluída/falhou), retenção
    pacote.py         o pacote do projeto: o que cada folha cobre, o que falta, conferências entre folhas, quantitativos
    contrato.py       o resultado e o modelo 3D no contrato 1.0 (o que o Plumo consome)
    espelho.py        o espelho no CAD: camada de cada elemento, onde vai o id, o que mudou na volta
    materiais.py      o levantamento: aço por bitola da NBR 7480, concreto por classe, forma, enchimento
    erros.py          erros com a mensagem para quem usa; a interface escolhe o código
  aplicacao/
    portas.py         o que os casos de uso pedem de fora: repositório, leitor, notificador, espelho
    casos_de_uso.py   enviar, consultar, resultado, modelo 3D, planilha, projeto, espelho, apagar, limpar expiradas
  infraestrutura/   adaptadores das portas
    motor/            a leitura da prancha: PDF pelas camadas do CAD (exato) ou imagem pelo OCR
    leitor.py         o motor em processos separados
    repositorio_disco.py · dxf.py (ezdxf) · notificador_http.py · excel.py
    catalogo_sinapi.py · baixar_sinapi.py   o SINAPI da Caixa e as regras de correspondência
  interfaces/
    http/             FastAPI: rotas, autenticação, erro do domínio → código HTTP, configuração
    cli/              identificar (ler pranchas sem o serviço) e gerar_dataset
```

O **motor** (`infraestrutura/motor/`) é o leitor validado nos PDFs de exemplo e fica fora do formatador: qualquer
mudança nele passa pela régua abaixo antes de entrar.

## Desenvolver

```bash
uv sync --extra dev -p 3.11
uv run pytest -q                                   # domínio, casos de uso, API, adaptadores, camadas (sem PDFs)
uv run ruff check src tests ferramentas && uv run ruff format --check src tests
uv run uvicorn canteiro_cad.interfaces.http.app:criar_app --factory --reload
uv run identificar-pranchas prancha.pdf --saida resultado   # sem o serviço
```

**Ponta a ponta e a régua.** Os PDFs de exemplo são de cliente e não entram no repositório. Com eles numa pasta local:

```bash
EXEMPLOS_PDF=/pasta/dos/pdfs uv run pytest tests/ponta_a_ponta -q
uv run identificar-pranchas /pasta/dos/pdfs/2.pdf --forcar-ocr --saida /tmp/r   # a leitura por OCR...
uv run python ferramentas/avaliar.py /pasta/dos/pdfs/2.pdf /tmp/r/2.json        # ...contra o texto exato do PDF
uv run python ferramentas/auditar_camadas.py /pasta/dos/pdfs/*.pdf              # regras de imagem x camadas do CAD
```

Sem a pasta, esses testes pulam (é o caso do CI).
