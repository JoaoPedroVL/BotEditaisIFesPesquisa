"""Testes do módulo prazos (extração e verificação de datas)."""

from __future__ import annotations

import unittest
from datetime import date

from prazos import extrair_datas, prazo_encerrado, tem_prazo_fixo


class TestExtrairDatas(unittest.TestCase):
    def test_intervalo_usando_a_data_final(self) -> None:
        datas = extrair_datas("26/10/2026 a 08/12/2026")
        self.assertEqual(max(datas), date(2026, 12, 8))

    def test_formato_extenso(self) -> None:
        datas = extrair_datas("15 de dezembro de 2026")
        self.assertEqual(datas, [date(2026, 12, 15)])

    def test_ano_com_dois_digitos(self) -> None:
        datas = extrair_datas("31/12/26")
        self.assertEqual(max(datas), date(2026, 12, 31))

    def test_sem_data(self) -> None:
        self.assertEqual(extrair_datas("fluxo contínuo"), [])
        self.assertEqual(extrair_datas("não informado"), [])


class TestPrazoEncerrado(unittest.TestCase):
    def setUp(self) -> None:
        self.hoje = date(2026, 11, 24)

    def test_encerrado_true(self) -> None:
        self.assertTrue(prazo_encerrado("10/10/2025", self.hoje))
        self.assertTrue(prazo_encerrado("encerrado em 01/01/2026", self.hoje))

    def test_encerrado_false(self) -> None:
        self.assertFalse(prazo_encerrado("26/10/2026 a 08/12/2026", self.hoje))
        self.assertFalse(prazo_encerrado("15 de dezembro de 2026", self.hoje))

    def test_none_quando_sem_data(self) -> None:
        self.assertIsNone(prazo_encerrado("fluxo contínuo", self.hoje))
        self.assertIsNone(prazo_encerrado("", self.hoje))

    def test_data_hoje_nao_encerrado(self) -> None:
        self.assertFalse(prazo_encerrado("até 24/11/2026", self.hoje))


class TestTemPrazoFixo(unittest.TestCase):
    def test_detecta_fluxo_continuo(self) -> None:
        self.assertFalse(tem_prazo_fixo("Inscrições em fluxo contínuo"))
        self.assertFalse(tem_prazo_fixo("CHAMADA PERMANENTE"))

    def test_none_quando_nao_informado(self) -> None:
        self.assertIsNone(tem_prazo_fixo("até 15/12/2026"))
        self.assertIsNone(tem_prazo_fixo(""))


if __name__ == "__main__":
    unittest.main()