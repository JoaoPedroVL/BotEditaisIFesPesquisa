"""Testes do notificador de e-mail com SMTP simulado (sem rede)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from notifier.base import ErroNotificador
from notifier.email import NotificadorEmail

AMBIENTE = {
    "EMAIL_HOST": "smtp.exemplo.org",
    "EMAIL_PORT": "587",
    "EMAIL_USER": "remetente@exemplo.org",
    "EMAIL_PASSWORD": "senha-falsa",
    "EMAIL_DESTINO": "diretor@exemplo.org",
    "EMAIL_SSL": "0",
    "EMAIL_TLS": "1",
}

MENSAGEM = (
    "📢 NOVO EDITAL - FAPES\n"
    "📌 Chamada Pública 01/2026\n"
    "🎯 Objeto: apoiar projetos.\n"
    "✅ ONG pode participar: sim\n"
    "🔗 https://exemplo.org/edital"
)


def _ambiente(**extras: str) -> dict[str, str]:
    base = dict(AMBIENTE)
    base.update(extras)
    return base


class TestNotificadorEmail(unittest.TestCase):
    def test_envia_com_tls_e_assunto_do_titulo(self) -> None:
        with patch.dict(os.environ, _ambiente(), clear=True):
            with patch("notifier.email.load_dotenv"):  # impede leitura do .env real
                with patch("notifier.email.smtplib.SMTP") as smtp_cls:
                    servidor = smtp_cls.return_value
                    notificador = NotificadorEmail()

                    self.assertTrue(notificador.enviar(MENSAGEM))

        smtp_cls.assert_called_once()
        argumentos = smtp_cls.call_args
        self.assertEqual(argumentos.args[0], "smtp.exemplo.org")
        self.assertEqual(argumentos.args[1], 587)

        servidor.starttls.assert_called_once()
        servidor.login.assert_called_once_with(
            "remetente@exemplo.org", "senha-falsa"
        )
        servidor.send_message.assert_called_once()
        servidor.quit.assert_called_once()

        email = servidor.send_message.call_args.args[0]
        self.assertIn("Chamada Pública 01/2026", email["Subject"])
        self.assertEqual(email["To"], "diretor@exemplo.org")
        self.assertEqual(email["From"], "Monitor de Editais <remetente@exemplo.org>")
        self.assertIn("apoiar projetos", email.get_content())

    def test_ssl_usa_porta_465_sem_starttls(self) -> None:
        ambiente = _ambiente(EMAIL_SSL="1", EMAIL_PORT="465")
        with patch.dict(os.environ, ambiente, clear=True):
            with patch("notifier.email.load_dotenv"):
                with patch("notifier.email.smtplib.SMTP_SSL") as smtp_ssl_cls:
                    servidor = smtp_ssl_cls.return_value
                    notificador = NotificadorEmail()

                    self.assertTrue(notificador.enviar(MENSAGEM))

        smtp_ssl_cls.assert_called_once()
        self.assertEqual(smtp_ssl_cls.call_args.args[1], 465)
        servidor.starttls.assert_not_called()
        servidor.send_message.assert_called_once()

    def test_falha_de_smtp_devolve_false(self) -> None:
        with patch.dict(os.environ, _ambiente(), clear=True):
            with patch("notifier.email.load_dotenv"):
                with patch("notifier.email.smtplib.SMTP") as smtp_cls:
                    smtp_cls.return_value.login.side_effect = OSError("conexão caiu")
                    notificador = NotificadorEmail()

                    self.assertFalse(notificador.enviar(MENSAGEM))

    def test_assunto_padrao_sem_titulo(self) -> None:
        self.assertEqual(
            NotificadorEmail._assunto("Mensagem sem o marcador de título."),
            "[Editais ONG] Novo edital",
        )

    def test_assunto_com_prefixo_personalizado(self) -> None:
        # Testa o novo parâmetro prefixo
        self.assertEqual(
            NotificadorEmail._assunto("📌 Título teste", prefixo="Editais IFES"),
            "[Editais IFES] Título teste",
        )

    def test_sem_credenciais_levanta_erro_de_configuracao(self) -> None:
        with patch.dict(
            os.environ,
            {"EMAIL_USER": "", "EMAIL_PASSWORD": "", "EMAIL_DESTINO": ""},
            clear=True,
        ):
            with patch("notifier.email.load_dotenv"):
                with self.assertRaises(ErroNotificador):
                    NotificadorEmail()


if __name__ == "__main__":
    unittest.main()
