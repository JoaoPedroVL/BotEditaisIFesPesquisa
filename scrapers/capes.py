"""Scraper da CAPES - seção "Editais Abertos".

A CAPES não publica, nessa página, uma lista de PDFs: publica links para os
programas que estão com edital aberto. O texto do programa (e o edital vigente)
é lido depois pelo extractor/IA.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from .base import EditalColetado, ScraperBase


class ScraperCapes(ScraperBase):
    nome = "capes"
    orgao = "CAPES"

    def extrair(self, html: str) -> list[EditalColetado]:
        soup = BeautifulSoup(html, "lxml")
        itens: list[EditalColetado] = []

        # Localiza o título "Editais Abertos" e a lista que vem logo depois.
        titulo_secao = None
        for h2 in soup.find_all("h2"):
            if "editais abertos" in h2.get_text(" ", strip=True).lower():
                titulo_secao = h2
                break
        if titulo_secao is None:
            return itens

        lista = None
        irmao = titulo_secao.find_next_sibling()
        while irmao is not None:
            if irmao.name == "ul":
                lista = irmao
                break
            if irmao.name == "h2":
                break
            irmao = irmao.find_next_sibling()
        if lista is None:
            return itens

        for link_tag in lista.select("li a[href]"):
            titulo = " ".join(link_tag.get_text(" ", strip=True).split())
            if not titulo:
                continue
            # O prefixo garante que o pré-filtro reconheça o item como edital.
            itens.append(
                EditalColetado(
                    titulo=f"Edital aberto: {titulo}",
                    orgao=self.orgao,
                    link=link_tag.get("href", ""),
                    resumo_fonte="Programa com edital aberto na página da CAPES.",
                )
            )

        return itens
