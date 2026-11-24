"""Testes do fallback e da validação do cliente de IA.

Não usam a rede nem a chave real: as chamadas HTTP são simuladas.
Execute na raiz do projeto:
    python -m unittest testes.test_llm_client -v
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from llm_client import ErroConfiguracaoLLM, ErroLLM, LLMClient
from prompts import extrair_json, validar_resultado

RESULTADO_VALIDO = {
    "orgao": "FAPES",
    "titulo": "Chamada Pública 01/2026",
    "objeto": "Apoiar projetos sociais.",
    "publico_alvo": "OSCs sem fins lucrativos.",
    "ong_pode_participar": "sim",
    "justificativa_ong": "O edital cita organizações da sociedade civil.",
    "inscricoes_abertas": "sim",
    "tipo_edital": "ongs",
    "justificativa_tipo": "Edital voltado para OSCs.",
    "prazo_inscricao": "15/12/2026",
    "valor": "Até R$ 100.000,00",
    "principais_requisitos": ["CNPJ ativo", "Plano de trabalho"],
    "resumo": "Edital de fomento a projetos sociais para OSCs.",
}


class RespostaFalsa:
    """Imita uma resposta mínima do requests."""

    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}
        if status_code == 200 and payload is not None:
            self.text = json.dumps(payload)
        else:
            self.text = '{"error": "falha simulada"}'

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("sem JSON")
        return self._payload


def resposta_ok(conteudo: str) -> RespostaFalsa:
    return RespostaFalsa(
        200,
        {
            "choices": [{"message": {"content": conteudo}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
    )


class TestLLMFallback(unittest.TestCase):
    def criar_cliente(self) -> LLMClient:
        return LLMClient(
            {
                "modelos": ["modelo-1", "modelo-2"],
                "temperatura": 0.1,
                "pausa_entre_chamadas": 0,
                "espera_entre_tentativas": 0,
                "max_tentativas_por_modelo": 2,
            },
            api_key="chave-de-teste",
        )

    @patch("llm_client.requests.post")
    def test_faz_fallback_apos_429(self, post) -> None:
        post.side_effect = [
            RespostaFalsa(429),
            RespostaFalsa(429),
            resposta_ok(json.dumps(RESULTADO_VALIDO)),
        ]

        resultado = self.criar_cliente().analisar_edital("texto", titulo="Teste")

        self.assertEqual(resultado.modelo, "modelo-2")
        self.assertEqual(resultado.dados["ong_pode_participar"], "sim")
        self.assertEqual(post.call_count, 3)

    @patch("llm_client.requests.post")
    def test_pede_correcao_de_json_invalido(self, post) -> None:
        post.side_effect = [
            resposta_ok("desculpe, não consegui responder em JSON"),
            resposta_ok(json.dumps(RESULTADO_VALIDO)),
        ]

        resultado = self.criar_cliente().analisar_edital("texto", titulo="Teste")

        self.assertEqual(resultado.modelo, "modelo-1")
        self.assertEqual(resultado.tentativas, 2)
        mensagens = post.call_args_list[1].kwargs["json"]["messages"]
        self.assertEqual(mensagens[-2]["role"], "assistant")
        self.assertEqual(mensagens[-1]["role"], "user")
        self.assertIn("JSON", mensagens[-1]["content"])

    @patch("llm_client.requests.post")
    def test_todos_os_modelos_falham(self, post) -> None:
        post.return_value = RespostaFalsa(503)

        with self.assertRaises(ErroLLM):
            self.criar_cliente().analisar_edital("texto")

        # 2 modelos x 2 tentativas
        self.assertEqual(post.call_count, 4)

    @patch("llm_client.requests.post")
    def test_chave_invalida_nao_insiste(self, post) -> None:
        post.return_value = RespostaFalsa(401)

        with self.assertRaises(ErroConfiguracaoLLM):
            self.criar_cliente().analisar_edital("texto")

        self.assertEqual(post.call_count, 1)

    def test_chave_ausente(self) -> None:
        cliente = LLMClient({"modelos": ["modelo-1"]}, api_key="")
        with self.assertRaises(ErroConfiguracaoLLM):
            cliente.analisar_edital("texto")


class TestValidacao(unittest.TestCase):
    def test_extrai_json_com_cerca_markdown(self) -> None:
        bruto = "```json\n" + json.dumps(RESULTADO_VALIDO) + "\n```"
        self.assertEqual(extrair_json(bruto)["orgao"], "FAPES")

    def test_extrai_json_com_texto_ao_redor(self) -> None:
        bruto = "Segue: " + json.dumps(RESULTADO_VALIDO) + " fim."
        self.assertEqual(extrair_json(bruto)["titulo"], "Chamada Pública 01/2026")

    def test_json_invalido_levanta_erro(self) -> None:
        with self.assertRaises(ValueError):
            extrair_json("não é json")

    def test_campo_ausente_levanta_erro(self) -> None:
        incompleto = dict(RESULTADO_VALIDO)
        del incompleto["prazo_inscricao"]
        with self.assertRaises(ValueError):
            validar_resultado(incompleto)

    def test_normaliza_status_e_requisitos(self) -> None:
        dados = dict(RESULTADO_VALIDO)
        dados["ong_pode_participar"] = "NÃO"
        dados["principais_requisitos"] = "CNPJ ativo"
        dados["valor"] = ""

        normalizado = validar_resultado(dados)

        self.assertEqual(normalizado["ong_pode_participar"], "nao")
        self.assertEqual(normalizado["principais_requisitos"], ["CNPJ ativo"])
        self.assertEqual(normalizado["valor"], "não informado")


if __name__ == "__main__":
    unittest.main()
