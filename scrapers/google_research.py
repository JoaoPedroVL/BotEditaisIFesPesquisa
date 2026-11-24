"""Scraper do Google Research Blog (RSS).

Fonte: https://research.google/blog/rss/
Feed RSS padrão com posts de pesquisa de IA, ML, ciência, saúde, clima, etc.
Não são editais de fomento, mas posts de pesquisa relevantes para IFs/ONGs.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

import feedparser

from .base import EditalColetado, ScraperBase

logger = logging.getLogger(__name__)


class ScraperGoogleResearch(ScraperBase):
    """Scraper do Google Research Blog via RSS."""

    nome = "google_research"
    orgao = "Google Research"

    def __init__(
        self, config_fonte: dict[str, Any], config_coleta: dict[str, Any] | None = None
    ) -> None:
        super().__init__(config_fonte, config_coleta)

        self.feed_url = str(
            self.config_fonte.get("feed_url", "https://research.google/blog/rss/")
        ).strip()

        if not self.feed_url:
            raise ValueError(f"Fonte {self.nome}: 'feed_url' não configurado no config.yaml")

        # Categorias de interesse (filtro)
        self.categorias_interesse = self.config_fonte.get("categorias_interesse", [
            "education innovation",
            "climate & sustainability",
            "health & bioscience",
            "education",
            "open source",
            "general science",
            "earth ai",
            "algorithms & theory",
        ])

    def extrair(self, html: str) -> list[EditalColetado]:
        """Parseia o feed RSS e extrai os posts."""
        itens: list[EditalColetado] = []

        try:
            feed = feedparser.parse(self.feed_url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao parsear feed RSS do Google Research: %s", exc)
            return itens

        if feed.bozo and feed.bozo_exception:
            logger.warning("Feed RSS com problemas: %s", feed.bozo_exception)

        for entrada in feed.entries:
            try:
                edital = self._entrada_para_edital(entrada)
                if edital:
                    itens.append(edital)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Erro ao processar entrada do feed: %s", exc)

        logger.info("Google Research: %d posts extraídos do RSS.", len(itens))
        return itens

    def _entrada_para_edital(self, entrada: Any) -> EditalColetado | None:
        """Converte uma entrada do feedparser para EditalColetado."""

        titulo = getattr(entrada, "title", "").strip()
        if not titulo:
            return None

        link = getattr(entrada, "link", "").strip()
        if not link:
            return None

        # Descrição/sumário
        descricao = ""
        if hasattr(entrada, "summary"):
            descricao = entrada.summary.strip()
        elif hasattr(entrada, "description"):
            descricao = entrada.description.strip()

        # Remove tags HTML da descrição
        descricao = re.sub(r"<[^>]+>", "", descricao)
        descricao = re.sub(r"\s+", " ", descricao).strip()

        # Categorias/tags
        categorias = []
        if hasattr(entrada, "tags"):
            categorias = [tag.term for tag in entrada.tags if hasattr(tag, "term")]

        # Data de publicação
        data_pub = ""
        if hasattr(entrada, "published"):
            data_pub = entrada.published.strip()
        elif hasattr(entrada, "updated"):
            data_pub = entrada.updated.strip()

        # Verifica se categoria é de interesse (case-insensitive)
        cat_lower = [c.lower() for c in categorias]
        interesses_lower = [i.lower() for i in self.categorias_interesse]
        eh_interesse = any(
            any(interesse in cat for cat in cat_lower)
            for interesse in interesses_lower
        )

        return EditalColetado(
            titulo=titulo,
            orgao=self.orgao,
            link=link,
            data_publicacao=data_pub,
            prazo="",  # Não se aplica a posts de blog
            resumo_fonte=descricao[:500],
            metadados={
                "categorias": categorias,
                "eh_interesse": eh_interesse,
                "tipo": "blog_post",
            },
        )