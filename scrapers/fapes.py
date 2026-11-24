"""Scraper da FAPES - editais abertos na área de Inovação.

A página usa um acordeão: o título de cada edital fica no botão e os arquivos
(PDF/DOCX) ficam na tabela interna. Usamos o primeiro PDF como link principal.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import EditalColetado, ScraperBase

logger = logging.getLogger(__name__)


class ScraperFapes(ScraperBase):
    nome = "fapes"
    orgao = "FAPES"

    def extrair(self, html: str) -> list[EditalColetado]:
        soup = BeautifulSoup(html, "lxml")
        itens: list[EditalColetado] = []

        for bloco in soup.select(".accordion-item"):
            botao = bloco.select_one(".accordion-button")
            if not botao:
                continue
            titulo = " ".join(botao.get_text(" ", strip=True).split())
            if not titulo:
                continue

            pdfs = [
                a.get("href", "")
                for a in bloco.select("a[href]")
                if ".pdf" in a.get("href", "").lower()
            ]
            if not pdfs:
                logger.warning("FAPES: edital sem PDF, ignorado: %s", titulo[:80])
                continue

            texto = " ".join(bloco.get_text(" ", strip=True).split())
            # A tabela traz a data de atualização no formato dd/mm/aaaa.
            data = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto)

            itens.append(
                EditalColetado(
                    titulo=titulo,
                    orgao=self.orgao,
                    link=urljoin(self.url, pdfs[0]),
                    data_publicacao=data.group(1) if data else "",
                    resumo_fonte=texto[:500],
                )
            )

        return itens
