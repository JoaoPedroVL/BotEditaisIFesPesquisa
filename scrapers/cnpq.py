"""Scraper do CNPq - chamadas abertas para submissão."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .base import EditalColetado, ScraperBase


class ScraperCNPq(ScraperBase):
    nome = "cnpq"
    orgao = "CNPq"

    def extrair(self, html: str) -> list[EditalColetado]:
        soup = BeautifulSoup(html, "lxml")
        itens: list[EditalColetado] = []

        # Cada chamada fica em <div class="item"> dentro de #content-core.
        for bloco in soup.select("#content-core .item"):
            link_tag = bloco.select_one("h2 a[href]")
            if not link_tag:
                continue

            titulo = " ".join(link_tag.get_text(" ", strip=True).split())
            link = link_tag.get("href", "")
            texto = " ".join(bloco.get_text(" ", strip=True).split())

            publicado = re.search(r"Publicado em\s+(\d{2}/\d{2}/\d{4})", texto)
            prazo = re.search(
                r"Inscrições:\s*"
                r"(\d{2}/\d{2}/\d{4}(?:\s*(?:a|até)\s*\d{2}/\d{2}/\d{4})?)",
                texto,
            )

            itens.append(
                EditalColetado(
                    titulo=titulo,
                    orgao=self.orgao,
                    link=link,
                    data_publicacao=publicado.group(1) if publicado else "",
                    prazo=prazo.group(1) if prazo else "",
                )
            )

        return itens
