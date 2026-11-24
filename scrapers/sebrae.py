"""Scraper do Sebrae - chamadas públicas.

Observação: o Sebrae publica editais por unidade estadual. A URL padrão aponta
para a unidade RS, cuja página é server-rendered e estável. Troque a URL no
config.yaml pela unidade desejada (ES, CE etc.) quando ela expuser uma listagem
equivalente.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import EditalColetado, ScraperBase


class ScraperSebrae(ScraperBase):
    nome = "sebrae"
    orgao = "Sebrae"

    def extrair(self, html: str) -> list[EditalColetado]:
        soup = BeautifulSoup(html, "lxml")
        itens: list[EditalColetado] = []

        for bloco in soup.select(".editais-e-licitacoes"):
            titulo_tag = bloco.find("h2")
            if not titulo_tag:
                continue
            titulo = " ".join(titulo_tag.get_text(" ", strip=True).split())
            if not titulo:
                continue

            pdfs = [
                a.get("href", "")
                for a in bloco.select("a[href]")
                if ".pdf" in a.get("href", "").lower()
            ]
            if not pdfs:
                continue

            texto = " ".join(bloco.get_text(" ", strip=True).split())
            # A tabela do Sebrae costuma trazer só o ano; usamos dd/mm/aaaa se vier.
            data = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto)
            if not data:
                data = re.search(r"\b(20\d{2})\b", texto)

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
