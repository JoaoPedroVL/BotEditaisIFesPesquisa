#!/usr/bin/env python3
"""Teste isolado de envio de notificação.

Monta uma mensagem de exemplo (a mesma que o robô envia) e tenta entregá-la
pelo canal configurado em ``notificacao.canal``.

Exemplos:
    python testar_notificacao.py                 # usa o canal do config.yaml
    python testar_notificacao.py --canal email   # força o canal de e-mail

Não toca no banco nem faz coleta: apenas valida credenciais e entrega.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from logging_setup import configurar_logging  # noqa: E402
from notifier import criar_notificador  # noqa: E402
from notifier.base import ErroNotificador, formatar_mensagem  # noqa: E402

logger = logging.getLogger("testar_notificacao")

MENSAGEM_EXEMPLO: dict[str, Any] = {
    "objeto": "Apoiar projetos de inclusão digital de jovens em situação de vulnerabilidade.",
    "ong_pode_participar": "sim",
    "justificativa_ong": "O edital cita organizações da sociedade civil sem fins lucrativos.",
    "prazo_inscricao": "15/12/2026, às 18h",
    "valor": "até R$ 100.000,00 por projeto",
    "principais_requisitos": [
        "CNPJ ativo há pelo menos dois anos",
        "plano de trabalho",
        "regularidade fiscal",
    ],
    "resumo": (
        "Mensagem de TESTE do monitor de editais. Se você recebeu isto, o canal "
        "de envio está configurado corretamente."
    ),
}


def carregar_config(caminho: Path) -> dict[str, Any]:
    if not caminho.exists():
        raise SystemExit(f"Arquivo de configuração não encontrado: {caminho}")
    with caminho.open(encoding="utf-8") as arquivo:
        config = yaml.safe_load(arquivo) or {}
    if not isinstance(config, dict):
        raise SystemExit("config.yaml inválido: o topo deve ser um mapa.")
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Envia uma mensagem de teste pelo canal configurado."
    )
    parser.add_argument(
        "--canal",
        choices=["telegram", "email", "whatsapp"],
        default=None,
        help="Força um canal, ignorando notificacao.canal do config.yaml.",
    )
    parser.add_argument(
        "--config",
        default=str(BASE_DIR / "config.yaml"),
        help="Caminho do config.yaml.",
    )
    parser.add_argument("--debug", action="store_true", help="Loga em nível DEBUG.")
    args = parser.parse_args(argv)

    configurar_logging(logging.DEBUG if args.debug else logging.INFO)
    config = carregar_config(Path(args.config))

    cfg_notificacao = dict(config.get("notificacao") or {})
    if args.canal:
        cfg_notificacao["canal"] = args.canal

    canal = str(cfg_notificacao.get("canal") or "telegram").strip().lower()
    print(f"Canal selecionado: {canal}")

    try:
        notificador = criar_notificador(cfg_notificacao)
    except ErroNotificador as exc:
        logger.error("Configuração incompleta: %s", exc)
        print("\nPreencha as variáveis do canal no .env (veja .env.example).")
        return 2

    mensagem = formatar_mensagem(
        orgao="TESTE",
        titulo="Mensagem de teste do monitor de editais",
        link="https://exemplo.org/teste",
        resultado=MENSAGEM_EXEMPLO,
        atualizado=False,
    )

    print("\n--- Mensagem que será enviada ---\n")
    print(mensagem)
    print("\n---------------------------------\n")

    try:
        enviado = notificador.enviar(mensagem)
    except Exception as exc:  # noqa: BLE001 - queremos o diagnóstico completo
        logger.exception("Falha inesperada no envio: %s", exc)
        return 1

    if enviado:
        logger.info("Teste concluído: envio confirmado pelo canal %s.", canal)
        return 0

    logger.error("Teste falhou: o canal %s não confirmou o envio.", canal)
    return 1


if __name__ == "__main__":
    sys.exit(main())
