# syntax=docker/dockerfile:1
# Tradutor de pranchas estruturais do Plumo. Contexto de build = raiz deste repositório.
# Imagens travadas pelo digest do índice multi-arquitetura (a mesma tag pode apontar para outra imagem amanhã); o
# Dependabot sobe tag e digest juntos. O uv é um estágio com nome porque o Dependabot só lê as linhas FROM.
# Python 3.11: o onnxruntime e o rapidocr travados no pyproject ainda não têm roda para 3.13+.
FROM ghcr.io/astral-sh/uv:0.13@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
# libGL/glib: o opencv que o rapidocr puxa pede as bibliotecas de interface gráfica mesmo sem tela
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_NO_CACHE=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    PATH=/srv/.venv/bin:$PATH \
    TRADUTOR_DADOS=/dados TRADUTOR_WORKERS=2
WORKDIR /srv
# Versões do uv.lock com --locked: lock desatualizado em relação ao pyproject quebra o build, em vez de instalar
# calado a versão velha. A imagem instala exatamente o que o CI testou. Dependências antes do código, para mudança
# no src não reinstalar o motor inteiro.
COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    uv sync --locked --no-dev --no-install-project
COPY src src
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    uv sync --locked --no-dev --no-editable \
 && useradd --create-home --uid 1000 tradutor && mkdir -p /dados && chown tradutor /dados
# uid 1000 desde a 1.0: o volume /dados de quem já rodava o serviço continua gravável
USER tradutor
VOLUME ["/dados"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/saude', timeout=4)"
CMD ["uvicorn", "canteiro_cad.interfaces.http.app:criar_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
