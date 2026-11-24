"""Configuração central de logs.

Grava em ``logs/app.log`` (com rotação) e também no console. O formato
inclui data/hora, nível e módulo de origem, o que ajuda a identificar
qual fonte ou modelo falhou.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"

_FORMATO = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATA = "%Y-%m-%d %H:%M:%S"


def configurar_logging(nivel: int = logging.INFO) -> None:
    """Configura o logging uma única vez (chamadas repetidas são ignoradas)."""
    root = logging.getLogger()
    if getattr(root, "_monitor_editais_configurado", False):
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_FORMATO, datefmt=_DATA)

    # Arquivo: 2 MB por arquivo, mantendo 5 backups.
    arquivo = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    arquivo.setFormatter(formatter)

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    root.setLevel(nivel)
    root.addHandler(arquivo)
    root.addHandler(console)

    # Bibliotecas externas falam demais em nível DEBUG.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pdfplumber").setLevel(logging.WARNING)

    root._monitor_editais_configurado = True  # type: ignore[attr-defined]
