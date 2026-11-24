"""Testes dos parsers dos scrapers usando HTML reduzido (sem rede)."""

from __future__ import annotations

import unittest

from scrapers.capes import ScraperCapes
from scrapers.cnpq import ScraperCNPq
from scrapers.fapes import ScraperFapes
from scrapers.sebrae import ScraperSebrae

CONFIG_COLETA = {"pausa_minima_segundos": 0, "pausa_maxima_segundos": 0}


def criar(classe, url: str):
    return classe({"nome": "teste", "url": url}, CONFIG_COLETA)


class TestScrapers(unittest.TestCase):
    def test_cnpq_extrai_titulo_data_e_prazo(self) -> None:
        html = """
        <div id="content-core">
          <div class="item">
            <h2><a href="/chamada-1">Chamada Pública Nº 01/2026</a></h2>
            <p>Publicado em 10/11/2026 09h00</p>
            <p>Objeto: apoiar projetos.</p>
            <p>Inscrições: 10/11/2026 a 15/12/2026</p>
          </div>
        </div>
        """
        itens = criar(ScraperCNPq, "https://www.gov.br/cnpq/").extrair(html)
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0].data_publicacao, "10/11/2026")
        self.assertEqual(itens[0].prazo, "10/11/2026 a 15/12/2026")
        self.assertEqual(itens[0].link, "/chamada-1")

    def test_fapes_usa_primeiro_pdf(self) -> None:
        html = """
        <div class="accordion-item">
          <button class="accordion-button">EDITAL FAPES Nº 28/2026</button>
          <table><tr><td>10/11/2026</td></tr></table>
          <a href="/media/edital.pdf">Edital</a>
        </div>
        """
        itens = criar(ScraperFapes, "https://fapes.es.gov.br/inovacao").extrair(html)
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0].link, "https://fapes.es.gov.br/media/edital.pdf")
        self.assertEqual(itens[0].data_publicacao, "10/11/2026")

    def test_capes_le_lista_de_editais_abertos(self) -> None:
        html = """
        <div>
          <h2>Editais Abertos</h2>
          <ul>
            <li><a href="/capes/programa">Programa Exemplo</a></li>
          </ul>
          <h2>Resultados</h2>
        </div>
        """
        itens = criar(
            ScraperCapes, "https://www.gov.br/capes/"
        ).extrair(html)
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0].titulo, "Edital aberto: Programa Exemplo")
        self.assertEqual(itens[0].link, "/capes/programa")

    def test_sebrae_extrai_chamada(self) -> None:
        html = """
        <div class="editais-e-licitacoes">
          <h2>CHAMADA PÚBLICA Nº 05/2026</h2>
          <table><tr><td>2026</td><td>Edital</td></tr></table>
          <a href="/edital.pdf">Edital de Chamada Pública</a>
        </div>
        """
        itens = criar(
            ScraperSebrae, "https://sebraers.com.br/editais/"
        ).extrair(html)
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0].link, "https://sebraers.com.br/edital.pdf")


if __name__ == "__main__":
    unittest.main()
