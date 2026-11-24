"""Canais de envio de mensagens (Telegram, WhatsApp etc.)."""

from __future__ import annotations

from typing import Any

from .base import ErroNotificador, Notificador, formatar_mensagem  # noqa: F401


def criar_notificador(config: dict[str, Any] | None = None) -> Notificador:
    """Cria o canal configurado em ``notificacao.canal``."""
    cfg = config or {}
    canal = str(cfg.get("canal") or "telegram").strip().lower()

    if canal == "telegram":
        from .telegram import NotificadorTelegram

        return NotificadorTelegram(cfg)
    if canal in ("whatsapp", "whatsapp_cloud"):
        from .whatsapp import NotificadorWhatsApp

        return NotificadorWhatsApp(cfg)
    if canal in ("email", "e-mail"):
        from .email import NotificadorEmail

        return NotificadorEmail(cfg)

    raise ErroNotificador(
        f"Canal de notificação desconhecido: {canal!r}. "
        "Use 'telegram', 'email' ou 'whatsapp'."
    )
