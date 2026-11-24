"""Cliente de IA para a API NVIDIA NIM (compatível com o formato OpenAI).

Recursos:
- fallback entre modelos configurados, em ordem de prioridade;
- retentativa (1x, após 2 s) em 429, 5xx, timeout e falha de conexão;
- pedido de correção (1x) quando o JSON retornado é inválido;
- controle de taxa para o plano gratuito (~40 req/min);
- log do modelo que respondeu e dos erros, sem expor a chave.

A chave é lida de ``NVIDIA_API_KEY`` (arquivo .env). Nunca fica no código.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from prompts import (
    extrair_json,
    montar_mensagem_correcao,
    montar_mensagens,
    validar_resultado,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
BASE_URL_PADRAO = "https://integrate.api.nvidia.com/v1"
MODELOS_PADRAO = [
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
]


class ErroLLM(Exception):
    """Falha ao falar com o provedor de IA.

    ``transitorio`` indica se vale a pena tentar de novo (429/5xx/timeout).
    ``espera`` é o tempo sugerido pelo servidor (Retry-After), se houver.
    """

    def __init__(
        self,
        mensagem: str,
        *,
        status: int | None = None,
        transitorio: bool = False,
        espera: float = 0.0,
    ) -> None:
        super().__init__(mensagem)
        self.status = status
        self.transitorio = transitorio
        self.espera = espera


class ErroConfiguracaoLLM(ErroLLM):
    """Chave ausente/inválida: não adianta tentar outros modelos."""


@dataclass
class ResultadoAnalise:
    """Resultado validado de uma análise."""

    dados: dict[str, Any]
    modelo: str
    tentativas: int


def _parse_retry_after(resposta: requests.Response) -> float:
    """Lê o header Retry-After (segundos) com tolerância a valores inválidos."""
    valor = resposta.headers.get("Retry-After")
    if not valor:
        return 0.0
    try:
        return max(0.0, float(valor))
    except (TypeError, ValueError):
        return 0.0


class LLMClient:
    """Cliente com fallback para a API da NVIDIA.

    Uso típico:
        cliente = LLMClient(config["ia"])
        resultado = cliente.analisar_edital(texto, orgao=..., titulo=..., link=...)
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        load_dotenv(BASE_DIR / ".env")  # não sobrescreve variáveis já definidas

        cfg = config or {}
        self.base_url = str(
            cfg.get("base_url") or os.getenv("NVIDIA_BASE_URL") or BASE_URL_PADRAO
        ).rstrip("/")

        modelos = cfg.get("modelos") or MODELOS_PADRAO
        if isinstance(modelos, str):
            modelos = [modelos]
        # Remove duplicados e entradas vazias, preservando a ordem.
        self.modelos: list[str] = list(
            dict.fromkeys(str(m).strip() for m in modelos if str(m).strip())
        )
        if not self.modelos:
            self.modelos = list(MODELOS_PADRAO)

        self.temperatura = float(cfg.get("temperatura", 0.15))
        self.max_tokens = int(cfg.get("max_tokens", 1500))
        self.timeout = float(cfg.get("timeout_segundos", 90))
        self.pausa_minima = max(0.0, float(cfg.get("pausa_entre_chamadas", 1.6)))
        self.max_tentativas = max(1, int(cfg.get("max_tentativas_por_modelo", 2)))
        self.espera_entre_tentativas = max(
            0.0, float(cfg.get("espera_entre_tentativas", 2.0))
        )
        self.limite_caracteres = max(
            1000, int(cfg.get("limite_caracteres_texto", 12000))
        )

        # api_key="" é tratado como "explicitamente sem chave" (útil em testes);
        # apenas None faz o fallback para a variável de ambiente.
        if api_key is not None:
            self.api_key = api_key.strip()
        else:
            self.api_key = os.getenv("NVIDIA_API_KEY", "").strip()

        # Controle de taxa: garante pausa mínima entre QUALQUER chamada.
        self._ultima_chamada = 0.0

        if self.temperatura > 0.3:
            logger.warning(
                "Temperatura %.2f é alta para extração de dados; "
                "o recomendado é entre 0.1 e 0.2.",
                self.temperatura,
            )

    # ------------------------------------------------------------------
    # Propriedades/utilitários
    # ------------------------------------------------------------------
    @property
    def tem_chave(self) -> bool:
        return bool(self.api_key)

    def _limitar_texto(self, texto: str) -> str:
        """Aplica a trava final de tamanho do texto enviado ao modelo."""
        if len(texto) <= self.limite_caracteres:
            return texto
        logger.warning(
            "Texto do edital truncado de %d para %d caracteres antes da IA.",
            len(texto),
            self.limite_caracteres,
        )
        return texto[: self.limite_caracteres] + "\n\n[...texto truncado...]"

    def _respeitar_taxa(self) -> None:
        """Espera o intervalo mínimo entre chamadas (plano gratuito)."""
        if self.pausa_minima <= 0:
            return
        espera = self.pausa_minima - (time.monotonic() - self._ultima_chamada)
        if espera > 0:
            time.sleep(espera)
        self._ultima_chamada = time.monotonic()

    def _cabeçalhos(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _requisicao(self, modelo: str, mensagens: list[dict[str, str]]) -> str:
        """Faz uma chamada de chat e devolve o conteúdo textual."""
        if not self.api_key:
            raise ErroConfiguracaoLLM(
                "NVIDIA_API_KEY não configurada. Preencha o arquivo .env."
            )

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": modelo,
            "messages": mensagens,
            "temperature": self.temperatura,
            "max_tokens": self.max_tokens,
            "stream": False,
        }

        self._respeitar_taxa()
        try:
            resposta = requests.post(
                url,
                headers=self._cabeçalhos(),
                json=payload,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise ErroLLM(
                f"timeout após {self.timeout:.0f}s", transitorio=True
            ) from exc
        except requests.RequestException as exc:
            raise ErroLLM(
                f"falha de conexão: {exc}", transitorio=True
            ) from exc

        codigo = resposta.status_code

        if codigo == 401:
            raise ErroConfiguracaoLLM(
                "NVIDIA_API_KEY inválida ou expirada (HTTP 401)."
            )
        if codigo == 429:
            raise ErroLLM(
                "limite de requisições atingido (HTTP 429)",
                status=codigo,
                transitorio=True,
                espera=_parse_retry_after(resposta),
            )
        if 500 <= codigo < 600:
            raise ErroLLM(
                f"erro no servidor da NVIDIA (HTTP {codigo})",
                status=codigo,
                transitorio=True,
            )
        if codigo != 200:
            # 403/404/400/422 normalmente são problema do modelo/requisição:
            # não adianta repetir no mesmo modelo, mas vale tentar o próximo.
            trecho = (resposta.text or "")[:300].replace("\n", " ")
            raise ErroLLM(
                f"HTTP {codigo}: {trecho}", status=codigo, transitorio=False
            )

        try:
            corpo = resposta.json()
        except ValueError as exc:
            raise ErroLLM(
                "a resposta HTTP não contém JSON", transitorio=True
            ) from exc

        try:
            escolha = corpo["choices"][0]
            conteudo = escolha["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ErroLLM(
                "resposta sem choices/message/content", transitorio=False
            ) from exc

        if not isinstance(conteudo, str) or not conteudo.strip():
            # Modelos de raciocínio podem gastar todos os tokens antes de
            # começar a resposta. Nesse caso, aumentar ia.max_tokens resolve.
            if escolha.get("finish_reason") == "length":
                raise ErroLLM(
                    "o modelo esgotou os tokens de saída antes de gerar o JSON "
                    "(aumente ia.max_tokens)",
                    transitorio=False,
                )
            raise ErroLLM("o modelo devolveu conteúdo vazio", transitorio=False)

        uso = corpo.get("usage") or {}
        logger.debug(
            "%s: tokens de entrada=%s, saída=%s",
            modelo,
            uso.get("prompt_tokens", "?"),
            uso.get("completion_tokens", "?"),
        )
        return conteudo

    # ------------------------------------------------------------------
    # Análise com fallback
    # ------------------------------------------------------------------
    def analisar_edital(
        self,
        texto: str,
        *,
        orgao: str = "",
        titulo: str = "",
        link: str | None = None,
    ) -> ResultadoAnalise:
        """Analisa um edital, tentando os modelos em ordem de prioridade.

        Levanta ``ErroConfiguracaoLLM`` se a chave estiver ausente/inválida e
        ``ErroLLM`` se todos os modelos falharem (o chamador deve manter o
        edital na fila para a próxima execução).
        """
        if not texto or not texto.strip():
            raise ErroLLM("texto do edital vazio; nada para analisar")
        if not self.api_key:
            raise ErroConfiguracaoLLM(
                "NVIDIA_API_KEY não configurada. Preencha o arquivo .env."
            )

        texto = self._limitar_texto(texto)
        mensagens_base = montar_mensagens(
            texto, orgao=orgao, titulo=titulo, link=link
        )
        falhas: list[str] = []

        for modelo in self.modelos:
            mensagens = list(mensagens_base)
            tentativas = 0

            while tentativas < self.max_tentativas:
                tentativas += 1
                try:
                    bruto = self._requisicao(modelo, mensagens)
                except ErroConfiguracaoLLM:
                    # Chave errada não melhora trocando de modelo.
                    raise
                except ErroLLM as erro:
                    falhas.append(f"{modelo}: {erro}")
                    logger.warning(
                        "Modelo %s falhou (tentativa %d/%d): %s",
                        modelo,
                        tentativas,
                        self.max_tentativas,
                        erro,
                    )
                    if erro.transitorio and tentativas < self.max_tentativas:
                        espera = max(self.espera_entre_tentativas, erro.espera)
                        logger.info("Nova tentativa em %.1fs...", espera)
                        if espera > 0:
                            time.sleep(espera)
                        continue
                    break  # passa para o próximo modelo

                try:
                    dados = validar_resultado(extrair_json(bruto))
                except ValueError as erro_json:
                    falhas.append(f"{modelo}: JSON inválido ({erro_json})")
                    logger.warning(
                        "JSON inválido do modelo %s (tentativa %d/%d): %s",
                        modelo,
                        tentativas,
                        self.max_tentativas,
                        erro_json,
                    )
                    if tentativas < self.max_tentativas:
                        # Conversa de correção: mostra a resposta e o erro.
                        mensagens = mensagens + [
                            {"role": "assistant", "content": bruto},
                            {
                                "role": "user",
                                "content": montar_mensagem_correcao(str(erro_json)),
                            },
                        ]
                        continue
                    break

                logger.info(
                    "Edital %r analisado com o modelo %s (tentativa %d).",
                    (titulo or "sem título")[:80],
                    modelo,
                    tentativas,
                )
                return ResultadoAnalise(
                    dados=dados, modelo=modelo, tentativas=tentativas
                )

        resumo_falhas = " | ".join(falhas[-5:]) if falhas else "erro desconhecido"
        raise ErroLLM(
            "Nenhum modelo conseguiu analisar o edital. " + resumo_falhas
        )

    # ------------------------------------------------------------------
    # Catálogo de modelos
    # ------------------------------------------------------------------
    def listar_modelos(self) -> list[str]:
        """Consulta /v1/models e devolve os IDs disponíveis.

        Útil para confirmar os nomes exatos antes de usar no config.yaml.
        """
        if not self.api_key:
            raise ErroConfiguracaoLLM(
                "NVIDIA_API_KEY não configurada. Preencha o arquivo .env."
            )

        self._respeitar_taxa()
        try:
            resposta = requests.get(
                f"{self.base_url}/models",
                headers=self._cabeçalhos(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ErroLLM(f"falha ao listar modelos: {exc}") from exc

        if resposta.status_code == 401:
            raise ErroConfiguracaoLLM(
                "NVIDIA_API_KEY inválida ou expirada (HTTP 401)."
            )
        if resposta.status_code != 200:
            raise ErroLLM(
                f"falha ao listar modelos (HTTP {resposta.status_code})"
            )

        try:
            corpo = resposta.json()
        except ValueError as exc:
            raise ErroLLM("resposta do catálogo não é JSON") from exc

        itens = corpo.get("data") if isinstance(corpo, dict) else corpo
        if not isinstance(itens, list):
            raise ErroLLM("formato inesperado do catálogo de modelos")

        ids = sorted(
            str(item["id"])
            for item in itens
            if isinstance(item, dict) and item.get("id")
        )
        return ids
