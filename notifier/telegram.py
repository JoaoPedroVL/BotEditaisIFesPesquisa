"""Notificador do Telegram (Bot API).

Variáveis necessárias no .env:
    TELEGRAM_BOT_TOKEN=
    TELEGRAM_CHAT_ID=
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .base import ErroNotificador, Notificador, dividir_mensagem

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent


class NotificadorTelegram(Notificador):
    nome = "telegram"

    def __init__(self, config: dict | None = None) -> None:
        load_dotenv(BASE_DIR / ".env")
        cfg = config or {}

        self.token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        self.chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        if not self.token or not self.chat_id:
            raise ErroNotificador(
                "Telegram: preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env."
            )

        self.timeout = float(cfg.get("timeout_segundos", 30))

    def enviar(self, mensagem: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        partes = dividir_mensagem(mensagem, 4000)

        for indice, parte in enumerate(partes, start=1):
            payload = {
                "chat_id": self.chat_id,
                "text": parte,
                "disable_web_page_preview": False,
            }
            try:
                resposta = requests.post(url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                logger.error("Telegram: falha de conexão: %s", exc)
                return False

            if resposta.status_code == 429:
                espera = 3.0
                try:
                    espera = float(
                        (resposta.json().get("parameters") or {}).get("retry_after", 3)
                    )
                except (ValueError, AttributeError, TypeError):
                    pass
                logger.warning("Telegram: limite atingido; aguardando %.0fs.", espera)
                time.sleep(espera)
                try:
                    resposta = requests.post(url, json=payload, timeout=self.timeout)
                except requests.RequestException as exc:
                    logger.error("Telegram: falha na nova tentativa: %s", exc)
                    return False

            if resposta.status_code != 200:
                logger.error(
                    "Telegram: HTTP %s ao enviar (%d/%d): %s",
                    resposta.status_code,
                    indice,
                    len(partes),
                    resposta.text[:300],
                )
                return False

            try:
                corpo = resposta.json()
            except ValueError:
                corpo = {}
            if corpo and corpo.get("ok") is False:
                logger.error("Telegram: API recusou o envio: %s", corpo)
                return False

        logger.info("Telegram: mensagem enviada (%d parte(s)).", len(partes))
        return True
