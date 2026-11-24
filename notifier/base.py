"""Interface comum dos canais de envio e formatação da mensagem."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class ErroNotificador(Exception):
    """Falha de configuração ou de envio em um canal."""


class Notificador(ABC):
    """Contrato único: enviar(mensagem) -> True/False."""

    nome = "base"

    @abstractmethod
    def enviar(self, mensagem: str) -> bool:
        """Envia a mensagem. Devolve True só quando o canal confirma o envio."""


def _campo(resultado: dict[str, Any], chave: str) -> str:
    valor = resultado.get(chave)
    if valor is None:
        return "não informado"
    if isinstance(valor, (list, tuple)):
        valor = "; ".join(str(item) for item in valor if str(item).strip())
    texto = " ".join(str(valor).split()).strip()
    return texto or "não informado"


def formatar_mensagem(
    *,
    orgao: str,
    titulo: str,
    link: str,
    resultado: dict[str, Any],
    atualizado: bool = False,
) -> str:
    """Monta a mensagem no formato definido no projeto."""
    status = str(resultado.get("ong_pode_participar", "incerto")).strip().lower()
    if status not in ("sim", "nao", "incerto"):
        status = "incerto"

    cabecalho = "🔄 EDITAL ATUALIZADO" if atualizado else "📢 NOVO EDITAL"
    linhas = [
        f"{cabecalho} - {orgao.strip().upper() or 'ÓRGÃO NÃO INFORMADO'}",
        f"📌 {titulo.strip() or _campo(resultado, 'titulo')}",
        f"🎯 Objeto: {_campo(resultado, 'objeto')}",
        f"✅ ONG pode participar: {status}",
    ]
    if status == "incerto":
        linhas.append("⚠️ Conferir elegibilidade no edital")

    linhas.extend(
        [
            f"📅 Prazo: {_campo(resultado, 'prazo_inscricao')}",
            f"💰 Valor: {_campo(resultado, 'valor')}",
            f"📝 Resumo: {_campo(resultado, 'resumo')}",
            f"🔗 {link.strip()}",
            "",
            "⚠️ Resumo gerado por IA. Confira sempre o edital oficial.",
        ]
    )
    return "\n".join(linhas)


def formatar_resumo(mensagens: list[str], *, data: str | None = None) -> str:
    """Junta várias mensagens em um único resumo diário.

    Usado no modo ``notificacao.formato: "resumo"``: uma só mensagem/e-mail por
    execução, com todos os editais elegíveis separados por uma linha.
    """
    itens = [mensagem.strip() for mensagem in mensagens if mensagem and mensagem.strip()]
    if not itens:
        return ""

    from datetime import date

    dia = data or date.today().strftime("%d/%m/%Y")
    quantidade = len(itens)
    rotulo = "edital" if quantidade == 1 else "editais"
    separador = "\n\n" + ("─" * 40) + "\n\n"

    return (
        f"📌 Resumo de {rotulo} — {dia} — {quantidade} {rotulo}\n"
        + separador
        + separador.join(itens)
    )


def dividir_mensagem(texto: str, limite: int = 4000) -> list[str]:
    """Divide mensagens longas (limite do Telegram/WhatsApp) sem cortar palavras."""
    if len(texto) <= limite:
        return [texto]

    partes: list[str] = []
    restante = texto
    while len(restante) > limite:
        corte = restante.rfind("\n", 0, limite)
        if corte < limite // 2:
            corte = restante.rfind(" ", 0, limite)
        if corte < limite // 2:
            corte = limite
        partes.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()
    if restante:
        partes.append(restante)
    return partes
