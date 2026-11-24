"""Notificador do WhatsApp Cloud API oficial (Meta).

Estrutura pronta, mas desativada por padrão. Variáveis no .env:
    WHATSAPP_TOKEN=
    WHATSAPP_PHONE_ID=
    WHATSAPP_DESTINO=   (número com DDI/DDD, ex.: 5527999999999)

Observação: envios para números fora da lista de teste exigem conta
business verificada e template aprovado pela Meta. Para textos livres dentro
da janela de 24h, este endpoint funciona normalmente.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

from .base import ErroNotificador, Notificador, dividir_mensagem

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent


class NotificadorWhatsApp(Notificador):
    nome = "whatsapp"

    def __init__(self, config: dict | None = None) -> None:
        load_dotenv(BASE_DIR / ".env")
        cfg = config or {}

        self.token = (os.getenv("WHATSAPP_TOKEN") or "").strip()
        self.phone_id = (os.getenv("WHATSAPP_PHONE_ID") or "").strip()
        destino = (os.getenv("WHATSAPP_DESTINO") or "").strip()
        self.destino = re.sub(r"\D", "", destino)

        if not self.token or not self.phone_id or not self.destino:
            raise ErroNotificador(
                "WhatsApp: preencha WHATSAPP_TOKEN, WHATSAPP_PHONE_ID e "
                "WHATSAPP_DESTINO no .env."
            )

        # A Meta desativa versões antigas da Graph API periodicamente.
        # Ajuste em config.yaml (notificacao.whatsapp_versao) se necessário.
        self.versao = str(cfg.get("whatsapp_versao") or "v23.0")
        self.timeout = float(cfg.get("timeout_segundos", 30))

    def enviar(self, mensagem: str) -> bool:
        url = f"https://graph.facebook.com/{self.versao}/{self.phone_id}/messages"
        cabecalhos = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        for indice, parte in enumerate(dividir_mensagem(mensagem, 4000), start=1):
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self.destino,
                "type": "text",
                "text": {"preview_url": True, "body": parte},
            }
            try:
                resposta = requests.post(
                    url, headers=cabecalhos, json=payload, timeout=self.timeout
                )
            except requests.RequestException as exc:
                logger.error("WhatsApp: falha de conexão: %s", exc)
                return False

            if resposta.status_code not in (200, 201):
                logger.error(
                    "WhatsApp: HTTP %s ao enviar (%d): %s",
                    resposta.status_code,
                    indice,
                    resposta.text[:300],
                )
                return False

        logger.info("WhatsApp: mensagem enviada.")
        return True
