"""Scraper da FACTO - Editais por ano.

Fonte: https://facto.org.br/editais/ (2026), /editais-2025/, etc.
Página WordPress/Elementor com lista de editais por ano.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import EditalColetado, ScraperBase

logger = logging.getLogger(__name__)


class ScraperFACTO(ScraperBase):
    """Scraper de editais da FACTO (Fundação de Apoio à Ciência e Tecnologia do IFES)."""

    nome = "facto"
    orgao = "FACTO"

    def __init__(
        self, config_fonte: dict[str, Any], config_coleta: dict[str, Any] | None = None
    ) -> None:
        super().__init__(config_fonte, config_coleta)

        # URL base - usa a página do ano atual por padrão
        self.url = str(
            self.config_fonte.get("url", "https://facto.org.br/editais/")
        ).strip()

        if not self.url:
            raise ValueError(f"Fonte {self.nome}: 'url' não configurado no config.yaml")

        # Anos para buscar (padrão: ano atual e anterior)
        self.anos = self.config_fonte.get("anos", [])
        if not self.anos:
            from datetime import date
            ano_atual = date.today().year
            self.anos = [str(ano_atual), str(ano_atual - 1)]

    def extrair(self, html: str) -> list[EditalColetado]:
        """Extrai editais da página de um ano específico."""
        # Este método é chamado para cada URL; a lógica principal está em extrair_todos
        return []

    def extrair_todos(self) -> list[EditalColetado]:
        """Percorre as páginas de cada ano e extrai todos os editais."""
        itens: list[EditalColetado] = []

        for ano in self.anos:
            if ano == str(self._ano_atual()):
                url_ano = "https://facto.org.br/editais/"
            else:
                url_ano = f"https://facto.org.br/editais-{ano}/"

            logger.info("FACTO: coletando ano %s em %s", ano, url_ano)

            try:
                if not self._robots_permite(url_ano):
                    logger.warning("Acesso proibido por robots.txt: %s", url_ano)
                    continue

                self._pausar()
                resp = self.session.get(url_ano, timeout=self.timeout)
                resp.raise_for_status()

                if resp.encoding in (None, "ISO-8859-1"):
                    resp.encoding = resp.apparent_encoding

                itens_ano = self._extrair_ano(resp.text, ano)
                itens.extend(itens_ano)
                logger.info("FACTO %s: %d editais.", ano, len(itens_ano))

            except Exception as exc:  # noqa: BLE001
                logger.warning("FACTO %s: erro ao coletar: %s", ano, exc)

        return itens

    def _ano_atual(self) -> int:
        from datetime import date
        return date.today().year

    def _extrair_ano(self, html: str, ano: str) -> list[EditalColetado]:
        """Extrai editais do HTML de uma página de ano."""
        soup = BeautifulSoup(html, "lxml")
        itens: list[EditalColetado] = []

        # A página usa Elementor com botões para cada edital
        # Links estão em <a class="elementor-button elementor-button-link ...>
        for link_tag in soup.select("a.elementor-button.elementor-button-link"):
            href = link_tag.get("href", "").strip()
            if not href:
                continue

            # Título do edital
            titulo_elem = link_tag.select_one(".elementor-button-text")
            titulo = titulo_elem.get_text(strip=True) if titulo_elem else ""
            if not titulo:
                titulo = link_tag.get_text(strip=True)

            if not titulo:
                continue

            # Tenta identificar tipo: edital ou pregão
            texto_pagina = soup.get_text().lower()
            eh_pregao = "pregao" in href.lower() or "pregoes" in href.lower()

            # Filtro: só editais (não pregões)
            if eh_pregao:
                continue

            itens.append(
                EditalColetado(
                    titulo=titulo,
                    orgao=self.orgao,
                    link=urljoin(ano == str(self._ano_atual()) and "https://facto.org.br/editais/" or f"https://facto.org.br/editais-{ano}/", href),
                    data_publicacao=ano,
                    prazo="",
                    resumo_fonte=f"FACTO - Editais {ano}",
                    metadados={
                        "ano": ano,
                        "tipo": "edital",
                    },
                )
            )

        return itens

    # Sobrescreve coletar para usar extrair_todos
    def coletar(self) -> list[dict[str, Any]]:
        """Coleta editais de todos os anos configurados."""
        logger.info("Fonte %s: iniciando coleta em %s", self.nome, self.url)
        try:
            brutos = self.extrair_todos() or []
            itens = self._normalizar_itens(brutos)
            logger.info(
                "Fonte %s: %d itens brutos, %d após filtro/deduplicação.",
                self.nome,
                len(brutos),
                len(itens),
            )
            return [item.como_dict() for item in itens]
        except Exception as exc:  # noqa: BLE001
            logger.exception("Fonte %s: falha na coleta: %s", self.nome, exc)
            return []