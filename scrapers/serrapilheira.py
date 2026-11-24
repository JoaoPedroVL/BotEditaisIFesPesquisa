"""Scraper do Instituto Serrapilheira - Todas as Chamadas.

Fonte: https://serrapilheira.org/todas-as-chamadas/
Página WordPress com grid Visual Composer contendo links para editais.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import EditalColetado, ScraperBase

logger = logging.getLogger(__name__)


class ScraperSerrapilheira(ScraperBase):
    """Scraper da página 'Todas as chamadas' do Instituto Serrapilheira."""

    nome = "serrapilheira"
    orgao = "Instituto Serrapilheira"

    def __init__(
        self, config_fonte: dict[str, Any], config_coleta: dict[str, Any] | None = None
    ) -> None:
        super().__init__(config_fonte, config_coleta)

        self.url = str(
            self.config_fonte.get(
                "url", "https://serrapilheira.org/todas-as-chamadas/"
            )
        ).strip()

        if not self.url:
            raise ValueError(f"Fonte {self.nome}: 'url' não configurado no config.yaml")

    def extrair(self, html: str) -> list[EditalColetado]:
        """Extrai editais do grid Visual Composer da página."""
        soup = BeautifulSoup(html, "lxml")
        itens: list[EditalColetado] = []

        # O grid usa classes vc_gitem-link vc-zone-link
        for link_tag in soup.select("a.vc_gitem-link.vc-zone-link"):
            href = link_tag.get("href", "").strip()
            if not href:
                continue

            # Título está no title attribute ou no texto do link
            titulo = link_tag.get("title", "").strip()
            if not titulo:
                titulo = link_tag.get_text(strip=True)

            # Tenta pegar a categoria/ano do elemento pai
            categoria = ""
            pai_grid = link_tag.find_parent("div", class_=re.compile(r"vc_grid-item"))
            if pai_grid:
                # Procura por texto de categoria (ex: "2026", "Ciência", etc.)
                cat_elem = pai_grid.select_one(".vc_gitem-post-data-source-post_title")
                if cat_elem:
                    categoria = cat_elem.get_text(strip=True)

            # Detecta se é edital de ciência/jornalismo/formação
            texto_busca = f"{titulo} {categoria}".lower()
            eh_ciencia = any(
                p in texto_busca
                for p in ("ciência", "ciencia", "pesquisa", "pós-doc", "pos-doc")
            )
            eh_jornalismo = any(
                p in texto_busca
                for p in ("jornalismo", "reportagem", "divulgação", "divulgacao")
            )
            eh_formacao = any(
                p in texto_busca
                for p in ("formação", "formacao", "ecologia quantitativa", "camp serrapilheira")
            )

            if eh_ciencia:
                cat_final = "ciência"
            elif eh_jornalismo:
                cat_final = "jornalismo"
            elif eh_formacao:
                cat_final = "formação"
            else:
                cat_final = "outro"

            # Ano do edital (tenta extrair do título ou URL)
            ano_match = re.search(r"\b(20\d{2})\b", titulo)
            ano = ano_match.group(1) if ano_match else ""

            itens.append(
                EditalColetado(
                    titulo=titulo,
                    orgao=self.orgao,
                    link=urljoin(self.url, href),
                    data_publicacao=ano,
                    prazo="",  # Será preenchido na extração do detalhe
                    resumo_fonte=f"Categoria: {cat_final}",
                    metadados={
                        "categoria_serrapilheira": cat_final,
                        "ano": ano,
                    },
                )
            )

        logger.info("Serrapilheira: %d editais extraídos.", len(itens))
        return itens