# Tradutor de pranchas — integração com o Prumo

Microsserviço que lê pranchas de cálculo estrutural (PDF exportado do CAD ou imagem) e devolve:

- **resultado** — tudo o que está na prancha, estruturado (carimbo, tabelas de aço, locação, formas,
  cortes, detalhamentos, cotas…), contrato `1.0`;
- **modelo3d** — o esqueleto estrutural em formato neutro para o motor 3D do Prumo;
- **excel** — planilha com todas as abas.

O Prumo cuida do design/renderização 3D; o serviço só entrega a geometria e os dados.

## Subir

```bash
docker compose up -d --build          # http://localhost:8000  ·  documentação: http://localhost:8000/docs
# ou sem Docker:
uv run uvicorn canteiro_cad.interfaces.http.app:criar_app --factory --port 8000
```

Variáveis: `TRADUTOR_API_KEYS` (chaves aceitas em `X-API-Key`), `TRADUTOR_WORKERS`, `TRADUTOR_MAX_MB`,
`TRADUTOR_RETENCAO_HORAS`, `TRADUTOR_CORS`, `TRADUTOR_WEBHOOK_SEGREDO`, `TRADUTOR_DADOS` (detalhes em `src/canteiro_cad/interfaces/http/configuracao.py`).

## Fluxo

| Passo | Chamada | Resposta |
|---|---|---|
| 1. Enviar | `POST /v1/traducoes` (multipart: `arquivo`, opcional `callback_url`) | `202` + `{id, status}` e cabeçalho `Location` |
| 1b. Enviar e esperar | `POST /v1/traducoes?aguardar=60` | `200` + resultado completo, se ficar pronto a tempo (PDF: ~10–20 s) |
| 2. Acompanhar | `GET /v1/traducoes/{id}` | `status`: `na_fila` · `processando` · `concluida` · `falhou` (+ `links` quando concluída) |
| 2b. Ou ser avisado | `callback_url` recebe `POST` com o mesmo corpo do passo 2 | assinado em `X-Tradutor-Assinatura: sha256=…` (HMAC do corpo) se houver segredo |
| 3. Dados | `GET /v1/traducoes/{id}/resultado` | contrato completo |
| 3. 3D | `GET /v1/traducoes/{id}/modelo3d` | ver abaixo; `404` se a prancha não tiver planta de locação |
| 3. Planilha | `GET /v1/traducoes/{id}/excel` | `.xlsx` |
| 4. Apagar | `DELETE /v1/traducoes/{id}` | `204` (também apaga sozinho após `TRADUTOR_RETENCAO_HORAS`) |

Erros: `401` chave inválida · `404` não existe · `409` ainda processando · `413` arquivo grande ·
`415` formato · `422` a tradução falhou (mensagem em `erro`).

Tempo medido: PDF do CAD ~17 s no contêiner. Imagem (OCR) ~1,5 min nativo no Mac, mas **~8 min no contêiner
Linux ARM do Docker Desktop** (o ONNX Runtime ali é ~2× mais lento por bloco e a VM limita). Em produção, meça no
servidor alvo; cada tradução usa vários núcleos — ajuste `TRADUTOR_WORKERS` ao número de núcleos/4 ou menos.

## Pacote do projeto (várias folhas)

O projeto estrutural chega em várias pranchas, e cada parte do pacote é responsável por um pedaço do modelo. Envie
cada prancha por `POST /v1/traducoes` (sem dizer o que ela é) e junte com:

`GET /v1/projetos?ids=id1,id2,id3` (1 a 30 ids; não guarda nada)

| Parte (`papel`) | Responsável por | Para o 3D |
|---|---|---|
| `locacao` | posição de cada pilar, eixos, profundidade das sapatas | necessária |
| `formas` | vigas, lajes e níveis de cada pavimento | necessária |
| `fundacoes` | medida real das sapatas e o aço delas | completa |
| `pilares` | aço de cada pilar e lances | completa |
| `vigas` | aço das vigas de cada pavimento (cobertura conferida por pavimento) | completa |
| `lajes` | aço das lajes e vigotas | completa |
| `cortes` | níveis e pé-direito, para conferência | opcional |

Uma prancha costuma cobrir várias partes (ex.: formas + locação + cortes na mesma folha); o tradutor reconhece pelo
conteúdo. A resposta traz `pacote` (situação de cada parte: `coberto`/`parcial`/`faltando`, por quais arquivos, e
os pavimentos que faltam), `conferencias` entre folhas (mesmo projeto, pilares e sapatas detalhados, h0 igual,
vigas da forma sem armação), `quantitativos` somados, `modelo3d` enriquecido (sapata com a medida real — pela cota,
conferida com o aço — e armação de pilares e sapatas), `pronto_para_3d` e `em_andamento` (folhas ainda sendo lidas).

## Espelho no CAD (DXF, ida e volta)

- **Ida:** `GET /v1/projetos/espelho.dxf?ids=...` devolve o modelo do pacote em DXF (planta, cm), com uma camada por
  tipo e nível: `PRUMO-PILARES`, `PRUMO-PILARES-MORREM`, `PRUMO-SAPATAS`, `PRUMO-VIGAS-<nível>`, `PRUMO-LAJES-<nível>`.
  Cada elemento é uma polilinha fechada; o id vai no texto da camada `PRUMO-IDS` (dentro do polígono) e no XDATA
  `PRUMO` (id, z0, z1). Testado no CADCraft 0.18 (abre, edita e salva preservando camadas e XDATA).
- **Volta:** o DXF salvo entra pelo mesmo `POST /v1/traducoes` (`.dxf`). Junto no pacote (`/v1/projetos`), a edição
  mais recente é aplicada sobre o modelo das pranchas e listada em `edicoes_cad.mudancas` (`movido`,
  `redimensionado`, `novo`, `removido`). Pilar com seção mudada perde a armação do detalhamento (marcado
  `armacao_desatualizada`). Polilinha nova sem id vira `NOVO-<tipo>-n`. O id é lido do XDATA ou, se o CAD não o
  guardar, do texto mais próximo com o padrão da camada.
- O espelho baixado de novo já sai com as edições: dá para editar em rodadas.

## CAD dentro do Prumo (vista 2D) e 3D ↔ 2D

A tela Projeto 3D do canteiro-web tem duas vistas do mesmo modelo: **3D** (three.js) e **2D · editar no CAD**, que é
o CADCraft compilado do código-fonte (v0.18.0, WASM) e servido pelo próprio Next em `/cadcraft` (só esse caminho pode
ser embutido, e só na mesma origem). O CAD roda no modo hospedeiro (`?host=parent`) e conversa com a página por
`postMessage`:

- `cadcraft:open` — o Prumo entrega o espelho (`/v1/projetos/espelho.dxf`) ao abrir a vista 2D;
- `cadcraft:save` — Salvar/Ctrl+S no CAD devolve o DXF para o Prumo, que o envia ao tradutor (`POST /v1/traducoes`)
  e recarrega o pacote: a edição aparece no 3D. Exportações (PNG, PDF) vão para o computador;
- `cadcraft:execute` → `cadcraft:executed` — **patch nosso** (`canteiro-web/scripts/cadcraft-prumo.patch`): roda um
  comando do catálogo do CAD (`zoom`, `zoom.extents`, `select`, `move`…) e responde com o resultado. O patch também
  dá nome ao desenho aberto pelo hospedeiro, para o `qsave` entregar em vez de pedir caminho.

**3D → 2D:** clicar num elemento no 3D e abrir o 2D faz o CAD enquadrar o elemento (`zoom` janela) e selecioná-lo
(`select` janela, só o que está inteiro dentro: o polígono e o id). **2D → 3D:** salvar no CAD aplica a edição no
modelo e volta ao 3D com ela.

Compilar: `canteiro-web/scripts/cadcraft.sh` (precisa de Rust com o alvo `wasm32-unknown-unknown` e `trunk`); clona a
v0.18.0, aplica o patch, compila e copia para `public/cadcraft/` (fora do git, com as licenças do CADCraft).

## Materiais do projeto (SINAPI)

`GET /v1/projetos/materiais?ids=a,b,c&uf=SP` → `{referencia: {fonte, mes, encargos, uf} | null, itens: [...],
total_referencia_centavos, avisos, em_andamento, nao_encontradas}`. Cada item: `chave` (estável: `aco:CA50:10.0`,
`concreto:C30`, `forma:chapa`, `enchimento:<nome>`, `vigota:planta`), `categoria`, `especificacao`, `unidade`,
`quantidade`, `origem` (folhas), `ajuste` (correção do que veio do CAD), `nota` (o que quem compra precisa saber) e
`referencia` (`{codigo, descricao, unidade, preco_centavos, total_centavos}` do SINAPI, ou `null`). Item com
`quantidade` 0 (vigotas) é para confirmar com o fornecedor, não para comprar como está.

## Contrato do modelo 3D (`docs/modelo3d.schema.json`)

```jsonc
{
  "versao_contrato": "1.0",
  "sistema_coordenadas": { "unidade": "cm", "x": "...", "y": "...", "z": "para cima; z = 0 é o nível 0" },
  "niveis":   [ { "cota_cm": 0, "nome": "Terreo 1" }, { "cota_cm": 310, "nome": "Cobertura" } ],
  "limites":  { "x0": -142.5, "y0": -142.5, "x1": 1577, "y1": 2727, "z0": -150, "z1": 310 },
  "elementos": [
    { "id": "P1",  "tipo": "pilar",  "geometria": { "forma": "caixa", "centro": [234, 2569.4], "dimensoes": [15, 30], "z0": -115, "z1": 310 },
      "propriedades": { "secao_cm": "15x30", "morre": false } },
    { "id": "S-P1", "tipo": "sapata", "geometria": { "forma": "caixa", ... }, "propriedades": { "dimensao_em_planta_estimada": true } },
    { "id": "V-310-001", "tipo": "viga", "geometria": { "forma": "caixa", ... }, "propriedades": { "nivel_cm": 310, "altura_cm": 40 } },
    { "id": "L1",  "tipo": "laje",   "geometria": { "forma": "prisma", "poligono": [[x, y], ...], "z0": 297, "z1": 310 },
      "propriedades": { "area_m2": 2.69, "espessura_cm": 13 } }
  ],
  "resumo": { "pilar": 31, "sapata": 31, "viga": 134, "laje": 13 },
  "calibracao_formas": [ { "titulo": "FORMA DO PAVIMENTO COBERTURA (NÍVEL 310)", "calibracao_erro_cm": 0.13, ... } ],
  "avisos": [ "Dimensão das sapatas em planta não consta nas folhas de forma: desenhadas com tamanho estimado." ]
}
```

Só duas primitivas: **caixa** (centro em planta, dimensões, z0→z1) e **prisma** (polígono extrudado z0→z1).
Vigas vêm como **trechos** reconstruídos do traçado da forma. Mostre os `avisos` ao usuário.

## Cliente TypeScript (exemplo)

```ts
const BASE = "http://localhost:8000", KEY = process.env.TRADUTOR_KEY!;

export async function traduzir(arquivo: File | Blob, nome: string) {
  const fd = new FormData();
  fd.append("arquivo", arquivo, nome);
  let r = await fetch(`${BASE}/v1/traducoes?aguardar=30`, { method: "POST", body: fd, headers: { "X-API-Key": KEY } });
  if (r.status === 200) return r.json();                       // ficou pronto na hora (PDF)
  if (r.status !== 202) throw new Error((await r.json()).detail);
  const { id } = await r.json();
  for (;;) {                                                   // ou use callback_url
    await new Promise(ok => setTimeout(ok, 3000));
    const s = await (await fetch(`${BASE}/v1/traducoes/${id}`, { headers: { "X-API-Key": KEY } })).json();
    if (s.status === "concluida") break;
    if (s.status === "falhou") throw new Error(s.erro);
  }
  return (await fetch(`${BASE}/v1/traducoes/${id}/resultado`, { headers: { "X-API-Key": KEY } })).json();
}
```

## Renderizando no three.js (z do contrato = altura)

```ts
for (const e of modelo.elementos) {
  const g = e.geometria;
  let geo: THREE.BufferGeometry;
  if (g.forma === "caixa") {
    geo = new THREE.BoxGeometry(g.dimensoes[0], g.z1 - g.z0, g.dimensoes[1]);
    geo.translate(g.centro[0], (g.z0 + g.z1) / 2, -g.centro[1]);      // planta (x, y) -> three (x, -z)
  } else {
    const s = new THREE.Shape(g.poligono.map(([x, y]) => new THREE.Vector2(x, y)));
    geo = new THREE.ExtrudeGeometry(s, { depth: g.z1 - g.z0, bevelEnabled: false });
    geo.rotateX(-Math.PI / 2); geo.translate(0, g.z0, 0);
  }
  scene.add(new THREE.Mesh(geo, materialPorTipo[e.tipo]));
}
```

## Limites atuais

- Padrão **Eberick/AutoCAD**; outros softwares exigem mapear as camadas/layout.
- Vigas e lajes no 3D só com **PDF com camadas**; com imagem o 3D traz pilares e sapatas.
- Sapatas em planta: tamanho **estimado** (a dimensão está na folha de detalhamento, ainda não cruzada).
- Cada prancha é traduzida isoladamente; juntar as folhas de um projeto num modelo único é o próximo passo.
