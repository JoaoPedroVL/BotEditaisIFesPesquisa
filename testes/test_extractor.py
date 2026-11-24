"""Testes das funções puras do extractor (sem rede)."""

from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from extractor import _encontrar_pdfs, limpar_texto, limitar_texto


class TestLimpeza(unittest.TestCase):
    def test_remove_espacos_e_linhas_repetidas(self) -> None:
        texto = "Título  \n\n\n\nTexto   com   espaços\nTexto   com   espaços"
        self.assertEqual(limpar_texto(texto), "Título\n\nTexto com espaços")

    def test_texto_pequeno_nao_e_alterado(self) -> None:
        texto = "Objeto: apoiar projetos."
        self.assertEqual(limitar_texto(texto, limite=1000), texto)


class TestPriorizacao(unittest.TestCase):
    def test_prioriza_trecho_com_palavra_chave(self) -> None:
        cabecalho = ["EDITAL DE TESTE", "Objeto: apoio a projetos."]
        lixo = ["preenchimento irrelevante " * 20 for _ in range(80)]
        relevante = [
            "Público-alvo: organizações da sociedade civil sem fins lucrativos.",
            "Prazo de inscrição: 15/12/2026.",
        ]
        texto = "\n".join(cabecalho + lixo + relevante)

        resultado = limitar_texto(
            texto, limite=1500, palavras_priorizadas=["público-alvo", "prazo"]
        )

        self.assertLessEqual(len(resultado), 1500)
        self.assertIn("organizações da sociedade civil", resultado)
        self.assertIn("15/12/2026", resultado)
        self.assertIn("EDITAL DE TESTE", resultado)


class TestLinksPdf(unittest.TestCase):
    def test_encontra_pdf_e_prioriza_edital(self) -> None:
        html = """
        <html><body>
          <a href="/anexo.pdf">Anexo I</a>
          <a href="/arquivos/edital-01.pdf">Edital 01/2026</a>
          <a href="/pagina.html">Página</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        links = _encontrar_pdfs(soup, "https://exemplo.org/listagem")
        self.assertTrue(links[0].endswith("edital-01.pdf"))
        self.assertTrue(links[0].startswith("https://exemplo.org/"))
        self.assertFalse(any(link.endswith(".html") for link in links))


if __name__ == "__main__":
    unittest.main()
