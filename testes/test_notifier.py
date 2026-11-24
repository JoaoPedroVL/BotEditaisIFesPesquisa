"""Testes da formatação e divisão das mensagens."""

from __future__ import annotations

import unittest

from notifier.base import dividir_mensagem, formatar_mensagem, formatar_resumo

RESULTADO = {
    "orgao": "FAPES",
    "titulo": "Chamada 01/2026",
    "objeto": "Apoiar projetos sociais.",
    "publico_alvo": "OSCs.",
    "ong_pode_participar": "incerto",
    "justificativa_ong": "O texto não cita ONGs.",
    "prazo_inscricao": "15/12/2026",
    "valor": "R$ 100.000,00",
    "principais_requisitos": ["CNPJ ativo"],
    "resumo": "Resumo curto do edital.",
}


class TestMensagem(unittest.TestCase):
    def test_formato_completo_e_aviso_de_incerto(self) -> None:
        mensagem = formatar_mensagem(
            orgao="FAPES",
            titulo="Chamada 01/2026",
            link="https://exemplo.org/edital",
            resultado=RESULTADO,
        )
        self.assertIn("📢 NOVO EDITAL - FAPES", mensagem)
        self.assertIn("📌 Chamada 01/2026", mensagem)
        self.assertIn("🎯 Objeto:", mensagem)
        self.assertIn("ONG pode participar: incerto", mensagem)
        self.assertIn("Conferir elegibilidade no edital", mensagem)
        self.assertIn("📅 Prazo: 15/12/2026", mensagem)
        self.assertIn("🔗 https://exemplo.org/edital", mensagem)
        self.assertIn("Resumo gerado por IA", mensagem)

    def test_sem_aviso_quando_sim(self) -> None:
        resultado = dict(RESULTADO, ong_pode_participar="sim")
        mensagem = formatar_mensagem(
            orgao="FAPES",
            titulo="Chamada 01/2026",
            link="https://exemplo.org/edital",
            resultado=resultado,
        )
        self.assertNotIn("Conferir elegibilidade", mensagem)
        self.assertIn("ONG pode participar: sim", mensagem)

    def test_cabecalho_de_edital_atualizado(self) -> None:
        mensagem = formatar_mensagem(
            orgao="CNPq",
            titulo="Chamada",
            link="https://exemplo.org",
            resultado=RESULTADO,
            atualizado=True,
        )
        self.assertTrue(mensagem.startswith("🔄 EDITAL ATUALIZADO"))

    def test_campos_ausentes_viram_nao_informado(self) -> None:
        mensagem = formatar_mensagem(
            orgao="CNPq",
            titulo="Chamada",
            link="https://exemplo.org",
            resultado={"ong_pode_participar": "sim"},
        )
        self.assertIn("Prazo: não informado", mensagem)
        self.assertIn("Valor: não informado", mensagem)


class TestDividirMensagem(unittest.TestCase):
    def test_respeita_limite(self) -> None:
        texto = "\n".join(["linha de teste"] * 500)
        partes = dividir_mensagem(texto, limite=200)
        self.assertEqual("".join(partes).replace("\n", ""), texto.replace("\n", ""))
        self.assertTrue(all(len(parte) <= 200 for parte in partes))


class TestResumoDiario(unittest.TestCase):
    def test_junta_mensagens_com_cabecalho_e_contagem(self) -> None:
        resumo = formatar_resumo(
            ["Mensagem A", "Mensagem B", "Mensagem C"], data="24/11/2026"
        )
        self.assertTrue(resumo.startswith("📌 Resumo de editais — 24/11/2026 — 3 editais"))
        self.assertIn("Mensagem A", resumo)
        self.assertIn("Mensagem B", resumo)
        self.assertIn("Mensagem C", resumo)
        self.assertEqual(resumo.count("─" * 40), 3)

    def test_singular(self) -> None:
        resumo = formatar_resumo(["Única"], data="24/11/2026")
        self.assertIn("— 1 edital", resumo)
        self.assertNotIn("1 editais", resumo)

    def test_lista_vazia_devolve_texto_vazio(self) -> None:
        self.assertEqual(formatar_resumo([]), "")
        self.assertEqual(formatar_resumo(["   ", ""]), "")

    def test_assunto_do_email_usa_o_cabecalho_do_resumo(self) -> None:
        from notifier.email import NotificadorEmail

        resumo = formatar_resumo(["Mensagem"], data="24/11/2026")
        assunto = NotificadorEmail._assunto(resumo)
        self.assertIn("Resumo de edital", assunto)


if __name__ == "__main__":
    unittest.main()
