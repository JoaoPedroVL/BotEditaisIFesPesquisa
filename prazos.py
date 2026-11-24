"""Interpretação de prazos de inscrição em editais.

Serve para descartar editais já encerrados de forma determinística, sem
depender só da IA. Aceita os formatos mais comuns:

- ``15/12/2026``, ``15/12/26``, ``15-12-2026``
- ``15 de dezembro de 2026``
- intervalos: ``26/10/2026 a 08/12/2026`` (vale a data final)

Regra principal: se houver mais de uma data, o prazo é a **mais recente**
(normalmente o fim do período de inscrições).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

RE_DATA_NUMERICA = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")
RE_DATA_EXTENSO = re.compile(
    r"\b(\d{1,2})\s*(?:de\s+)?([a-z]+)(?:\s+de)?\s+(\d{4})\b", re.IGNORECASE
)

# Expressões que indicam que não há data final fixa.
SEM_PRAZO_FIXO = (
    "fluxo continuo",
    "em fluxo",
    "a qualquer momento",
    "ate o esgotamento",
    "sem data de encerramento",
    "chamada permanente",
)


def _sem_acento(texto: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    ).lower()

def _data_valida(dia: int, mes: int, ano: int) -> date | None:
    if ano < 100:
        ano += 2000
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def extrair_datas(texto: str) -> list[date]:
    """Extrai todas as datas válidas do texto, sem repetição e em ordem."""
    if not texto:
        return []

    datas: set[date] = set()

    for dia, mes, ano in RE_DATA_NUMERICA.findall(texto):
        data = _data_valida(int(dia), int(mes), int(ano))
        if data:
            datas.add(data)

    normalizado = _sem_acento(texto)
    for dia, nome_mes, ano in RE_DATA_EXTENSO.findall(normalizado):
        mes = MESES.get(nome_mes)
        if not mes:
            continue
        data = _data_valida(int(dia), mes, int(ano))
        if data:
            datas.add(data)

    return sorted(datas)


def prazo_encerrado(
    texto: str, referencia: date | None = None
) -> bool | None:
    """Diz se o prazo descrito em ``texto`` já passou.

    Devolve:
    - ``True``  → há data(s) e a mais recente já passou;
    - ``False`` → há data e a mais recente ainda está por vir (ou é hoje);
    - ``None``  → não há data interpretável (não é possível decidir).
    """
    if not texto:
        return None

    datas = extrair_datas(texto)
    if not datas:
        return None

    hoje = referencia or date.today()
    return max(datas) < hoje


def tem_prazo_fixo(texto: str) -> bool | None:
    """Indica se o texto fala em prazo contínuo/sem data final."""
    if not texto:
        return None
    normalizado = _sem_acento(texto)
    if any(expressao in normalizado for expressao in SEM_PRAZO_FIXO):
        return False
    return None
