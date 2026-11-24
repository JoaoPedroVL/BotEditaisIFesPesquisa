"""Testes do banco: deduplicação, alteração de conteúdo e filtro de envio."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import BancoEditais, gerar_hash

RESULTADO = {
    "orgao": "FAPES",
    "titulo": "Edital 01/2026",
    "objeto": "Apoiar projetos.",
    "publico_alvo": "OSCs.",
    "ong_pode_participar": "sim",
    "justificativa_ong": "Cita OSCs.",
    "prazo_inscricao": "15/12/2026",
    "valor": "R$ 100.000,00",
    "principais_requisitos": ["CNPJ ativo"],
    "resumo": "Resumo.",
}


class TestBancoEditais(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.banco = BancoEditais(Path(self._tmp.name) / "editais.db")
        self.banco.inicializar()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def registrar(self, hash_conteudo: str) -> object:
        return self.banco.registrar_coleta(
            orgao="FAPES",
            titulo="Edital 01/2026",
            link="https://exemplo.org/edital-1",
            hash_conteudo=hash_conteudo,
        )

    def test_novo_deduplicacao_e_analise(self) -> None:
        primeiro = self.registrar("hash-1")
        self.assertTrue(primeiro.novo)
        self.assertTrue(primeiro.precisa_analisar)

        repetido = self.registrar("hash-1")
        self.assertFalse(repetido.novo)
        self.assertFalse(repetido.atualizado)
        # Ainda não foi analisado, então continua pendente.
        self.assertTrue(repetido.precisa_analisar)

        self.banco.salvar_analise(primeiro.id, RESULTADO, "modelo-x")
        depois = self.registrar("hash-1")
        self.assertFalse(depois.precisa_analisar)

    def test_edital_alterado_reanalisa_e_reenvia(self) -> None:
        registro = self.registrar("hash-1")
        self.banco.salvar_analise(registro.id, RESULTADO, "modelo-x")
        self.banco.marcar_enviado(registro.id)
        self.assertEqual(len(self.banco.pendentes_envio()), 0)

        alterado = self.registrar("hash-2")
        self.assertTrue(alterado.atualizado)
        self.assertTrue(alterado.precisa_analisar)
        self.assertEqual(len(self.banco.pendentes_envio()), 0)

        linha = self.banco.obter_por_link("https://exemplo.org/edital-1")
        self.assertIsNotNone(linha)
        self.assertEqual(linha["enviado"], 0)
        self.assertEqual(linha["atualizado"], 1)

    def test_filtro_nao_envia_ong_nao(self) -> None:
        registro = self.registrar("hash-1")
        resultado = dict(RESULTADO, ong_pode_participar="nao")
        self.banco.salvar_analise(registro.id, resultado, "modelo-x")

        self.assertEqual(self.banco.pendentes_envio(), [])
        self.assertEqual(self.banco.estatisticas()["pendentes_envio"], 0)

    def test_hash_ignora_espacos_e_maiusculas(self) -> None:
        self.assertEqual(
            gerar_hash("Edital   com espaços\n\ne MAIÚSCULAS"),
            gerar_hash("edital com espaços e maiúsculas"),
        )


if __name__ == "__main__":
    unittest.main()
