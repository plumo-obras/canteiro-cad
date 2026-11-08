"""Tradutor de pranchas estruturais do Plumo: lê o projeto estrutural (PDF do CAD ou imagem) e devolve os dados, o
pacote do projeto e o modelo 3D.

Camadas (de dentro para fora; cada uma só conhece as de dentro):
    dominio/          regras puras: a tradução, o pacote do projeto, o contrato do modelo 3D, o espelho no CAD
    aplicacao/        casos de uso e as portas que eles pedem (repositório, leitor, notificador, espelho)
    infraestrutura/   adaptadores: o motor de leitura (PDF/OCR), o disco, o DXF, o callback HTTP, a planilha
    interfaces/       quem chama: a API HTTP (FastAPI) e a linha de comando
"""

from canteiro_cad.dominio.versao import VERSAO_CONTRATO, VERSAO_SERVICO

__all__ = ["VERSAO_CONTRATO", "VERSAO_SERVICO"]
