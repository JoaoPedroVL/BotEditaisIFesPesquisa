"""Teste isolado do cliente de IA (NVIDIA).

Uso:
    python testar_llm.py                    # analisa um edital de exemplo
    python testar_llm.py --listar-modelos   # confere nomes no catálogo
    python testar_llm.py --arquivo texto.txt --orgao "FAPES"

Requer NVIDIA_API_KEY no .env. Não envia mensagens: serve só para validar a
análise antes de rodar o robô completo.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from llm_client import ErroConfiguracaoLLM, ErroLLM, LLMClient
from logging_setup import configurar_logging

BASE_DIR = Path(__file__).resolve().parent

TEXTO_EXEMPLO = """\
CHAMADA PÚBLICA Nº 01/2026 - FOMENTO A PROJETOS SOCIAIS

Objeto: apoiar projetos de organizações da sociedade civil sem fins lucrativos
voltados à inclusão digital de jovens em situação de vulnerabilidade.

Público-alvo: organizações da sociedade civil (OSCs), associações e fundações
sem fins lucrativos, com CNPJ ativo há pelo menos dois anos.

Prazo para inscrições: 15/12/2026, às 18h.
Valor total: R$ 1.000.000,00. Valor por projeto: até R$ 100.000,00.
Contrapartida: não exigida.

Requisitos: possuir cadastro atualizado, apresentar plano de trabalho e
declaração de regularidade fiscal.
"""


def carregar_config() -> dict:
    caminho = BASE_DIR / "config.yaml"
    if not caminho.exists():
        raise SystemExit(f"Arquivo de configuração não encontrado: {caminho}")
    with caminho.open(encoding="utf-8") as arquivo:
        return yaml.safe_load(arquivo) or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Testa a análise de editais por IA.")
    parser.add_argument(
        "--listar-modelos",
        action="store_true",
        help="Consulta o catálogo da NVIDIA e compara com o config.yaml.",
    )
    parser.add_argument(
        "--arquivo", help="Arquivo .txt com o texto de um edital real."
    )
    parser.add_argument(
        "--orgao", default="FAPES", help="Órgão do edital de exemplo."
    )
    parser.add_argument(
        "--titulo",
        default="Chamada Pública 01/2026 - Fomento a Projetos Sociais",
        help="Título do edital de exemplo.",
    )
    parser.add_argument(
        "--modelo",
        action="append",
        help="Usa somente este modelo (pode repetir). Padrão: lista do config.yaml.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Mostra logs de depuração."
    )
    args = parser.parse_args()

    configurar_logging(logging.DEBUG if args.debug else logging.INFO)

    config = carregar_config()
    config_ia = dict(config.get("ia") or {})
    if args.modelo:
        config_ia["modelos"] = args.modelo

    cliente = LLMClient(config_ia)

    if not cliente.tem_chave:
        print(
            "\nERRO: NVIDIA_API_KEY não encontrada.\n"
            "1. Copie .env.example para .env\n"
            "2. Preencha NVIDIA_API_KEY=...\n"
            "3. Rode novamente.\n"
        )
        return 2

    try:
        if args.listar_modelos:
            print("Consultando catálogo da NVIDIA...\n")
            ids = cliente.listar_modelos()
            print(f"{len(ids)} modelos disponíveis:\n")
            for modelo_id in ids:
                marca = " <-- configurado" if modelo_id in cliente.modelos else ""
                print(f"  {modelo_id}{marca}")
            print("\nConferência do config.yaml:")
            for modelo in cliente.modelos:
                status = "OK" if modelo in ids else "NÃO ENCONTRADO no catálogo"
                print(f"  [{status}] {modelo}")
            return 0

        texto = TEXTO_EXEMPLO
        if args.arquivo:
            caminho = Path(args.arquivo).expanduser()
            if not caminho.exists():
                print(f"ERRO: arquivo não encontrado: {caminho}")
                return 2
            texto = caminho.read_text(encoding="utf-8", errors="replace")

        print("Analisando edital de teste...\n")
        resultado = cliente.analisar_edital(
            texto,
            orgao=args.orgao,
            titulo=args.titulo,
            link="https://exemplo.org/edital",
        )

        print(json.dumps(resultado.dados, ensure_ascii=False, indent=2))
        print(f"\nModelo que respondeu: {resultado.modelo}")
        print(f"Tentativas: {resultado.tentativas}")
        return 0

    except ErroConfiguracaoLLM as erro:
        print(f"\nERRO DE CONFIGURAÇÃO: {erro}")
        return 2
    except ErroLLM as erro:
        print(f"\nERRO NA ANÁLISE: {erro}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
