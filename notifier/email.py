"""Notificador por e-mail (SMTP).

Ideal para receber os editais na própria caixa de entrada, sem depender de
API de WhatsApp. Funciona com Gmail (senha de app), Outlook, Zoho e qualquer
servidor SMTP.

Variáveis no .env:
    EMAIL_HOST=smtp.gmail.com
    EMAIL_PORT=587
    EMAIL_USER=seuemail@gmail.com
    EMAIL_PASSWORD=senha-de-app
    EMAIL_DESTINO=seuemail@gmail.com
    EMAIL_DESTINO_IFES=outro@email.com   (opcional; segundo canal)
    # Vários destinatários: separe por vírgula ou ponto e vírgula.
    EMAIL_DESTINO=a@x.com,b@y.com
    EMAIL_REMETENTE=seuemail@gmail.com   (opcional; padrão = EMAIL_USER)
    EMAIL_SSL=0                          (opcional; use 1 para porta 465)
    EMAIL_TLS=1                          (opcional; STARTTLS na porta 587)
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from dotenv import load_dotenv

from .base import ErroNotificador, Notificador

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent


class NotificadorEmail(Notificador):
    nome = "email"

    def __init__(self, config: dict | None = None, destino_override: str | None = None) -> None:
        load_dotenv(BASE_DIR / ".env")
        cfg = config or {}

        self.host = (os.getenv("EMAIL_HOST") or "smtp.gmail.com").strip()
        self.porta = int(os.getenv("EMAIL_PORT") or 587)
        self.usuario = (os.getenv("EMAIL_USER") or "").strip()
        self.senha = (os.getenv("EMAIL_PASSWORD") or "").strip()
        # Permite sobrescrever o destino (para segundo canal IFES).
        # Aceita vários endereços separados por vírgula ou ponto e vírgula.
        destino_bruto = (destino_override or os.getenv("EMAIL_DESTINO") or self.usuario).strip()
        self.destinos = [
            endereco.strip()
            for endereco in destino_bruto.replace(";", ",").split(",")
            if endereco.strip()
        ]
        # Mantém o atributo antigo por compatibilidade (string com todos).
        self.destino = ", ".join(self.destinos)
        self.remetente = (os.getenv("EMAIL_REMETENTE") or self.usuario).strip()

        if not self.usuario or not self.senha or not self.destinos:
            raise ErroNotificador(
                "E-mail: preencha EMAIL_USER, EMAIL_PASSWORD e EMAIL_DESTINO no .env."
            )

        self.usar_ssl = (os.getenv("EMAIL_SSL") or "0").strip() == "1"
        self.usar_tls = (os.getenv("EMAIL_TLS") or "1").strip() != "0"
        self.timeout = float(cfg.get("timeout_segundos", 30))

    @staticmethod
    def _assunto(mensagem: str, prefixo: str = "Editais ONG") -> str:
        """Usa o título do edital como assunto, quando presente."""
        for linha in mensagem.splitlines():
            if linha.startswith("📌"):
                titulo = linha.lstrip("📌 ").strip()
                if titulo:
                    return f"[{prefixo}] {titulo[:120]}"
        return f"[{prefixo}] Novo edital"

    def enviar(self, mensagem: str, prefixo: str = "Editais ONG") -> bool:
        email = EmailMessage()
        email["Subject"] = self._assunto(mensagem, prefixo)
        email["From"] = formataddr(("Monitor de Editais", self.remetente))
        email["To"] = ", ".join(self.destinos)
        email.set_content(mensagem)

        servidor = None
        try:
            contexto = ssl.create_default_context()
            if self.usar_ssl:
                servidor = smtplib.SMTP_SSL(
                    self.host, self.porta, timeout=self.timeout, context=contexto
                )
            else:
                servidor = smtplib.SMTP(
                    self.host, self.porta, timeout=self.timeout
                )
                if self.usar_tls:
                    servidor.starttls(context=contexto)

            servidor.login(self.usuario, self.senha)
            servidor.send_message(email)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("E-mail: falha ao enviar: %s", exc)
            return False
        finally:
            if servidor is not None:
                try:
                    servidor.quit()
                except Exception:  # noqa: BLE001 - encerramento best-effort
                    pass

        logger.info("E-mail: mensagem enviada para %s.", ", ".join(self.destinos))
        return True
