"""Scraper do Portal de Editais IFES (GitHub Pages ZIP).

Fonte: https://ifesserra-lab.github.io/portal_edital/dados/
Baixa um ZIP com 58+ editais JSON estruturados do IFES.
Ideal para a categoria 'instituicoes_federais': PIBIC, eventos, feiras, TCC, etc.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any
from urllib.parse import urljoin

from .base import EditalColetado, ScraperBase

logger = logging.getLogger(__name__)


class ScraperPortalEditaisIFES(ScraperBase):
    """Scraper que baixa o ZIP do Portal de Editais IFES e extrai os JSONs."""

    nome = "portal_editais_ifes"
    orgao = "Portal Editais IFES"

    def __init__(
        self, config_fonte: dict[str, Any], config_coleta: dict[str, Any] | None = None
    ) -> None:
        super().__init__(config_fonte, config_coleta)

        # URL do ZIP (vem do config.yaml ou padrão)
        self.zip_url = str(
            self.config_fonte.get(
                "zip_url",
                "https://ifesserra-lab.github.io/portal_edital/dados-editais.zip",
            )
        ).strip()

        # Se a fonte já tem 'url', usa ela como fallback
        if not self.zip_url and self.url:
            # Tenta inferir o ZIP a partir da URL da página
            if self.url.endswith("/dados/"):
                self.zip_url = urljoin(self.url, "dados-editais.zip")

        if not self.zip_url:
            raise ValueError(
                f"Fonte {self.nome}: 'zip_url' não configurado no config.yaml"
            )

    def extrair(self, html: str) -> list[EditalColetado]:
        """Baixa o ZIP, extrai JSONs e converte para EditalColetado.

        O parâmetro 'html' não é usado aqui (o ZIP é binário), mas mantemos
        a assinatura da classe base.
        """
        itens: list[EditalColetado] = []

        try:
            zip_bytes = self._baixar_zip()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao baixar ZIP do Portal Editais IFES: %s", exc)
            return itens

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                itens_brutos: list[EditalColetado] = []
                for nome_arquivo in zf.namelist():
                    if not nome_arquivo.lower().endswith(".json"):
                        continue
                    try:
                        with zf.open(nome_arquivo) as f:
                            dados = json.load(f)
                        edital = self._json_para_edital(dados, nome_arquivo)
                        if edital:
                            itens_brutos.append(edital)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Erro ao processar %s do ZIP: %s", nome_arquivo, exc
                        )

                # Prioriza editais IFES (eh_ifes=True) no topo
                itens_brutos.sort(key=lambda e: e.metadados.get("eh_ifes", False), reverse=True)

                logger.info(
                    "Portal Editais IFES: %d editais extraídos do ZIP (%d IFES).",
                    len(itens_brutos),
                    sum(1 for e in itens_brutos if e.metadados.get("eh_ifes")),
                )
                return itens_brutos
        except zipfile.BadZipFile as exc:
            logger.error("Arquivo ZIP inválido: %s", exc)
            return itens
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro inesperado ao processar ZIP: %s", exc)
            return itens

    def _baixar_zip(self) -> bytes:
        """Baixa o arquivo ZIP completo."""
        if not self._robots_permite(self.zip_url):
            raise PermissionError(f"Acesso ao ZIP proibido por robots.txt: {self.zip_url}")

        self._pausar()
        resposta = self.session.get(self.zip_url, timeout=self.timeout)
        resposta.raise_for_status()

        tipo = (resposta.headers.get("Content-Type") or "").lower()
        if "zip" not in tipo and not self.zip_url.lower().endswith(".zip"):
            logger.warning(
                "URL não retornou ZIP (Content-Type: %s): %s", tipo, self.zip_url
            )

        return resposta.content

    def _json_para_edital(self, dados: dict[str, Any], nome_arquivo: str) -> EditalColetado | None:
        """Converte o JSON do Portal Editais para EditalColetado."""

        titulo = str(dados.get("nome") or dados.get("titulo") or "").strip()
        if not titulo:
            logger.warning("Edital sem título no arquivo %s", nome_arquivo)
            return None

        link = str(dados.get("link") or "").strip()
        if not link:
            logger.warning("Edital sem link no arquivo %s: %s", nome_arquivo, titulo[:80])
            return None

        # Descrição/objeto
        objeto = str(dados.get("descrição") or dados.get("descricao") or "").strip()

        # Órgão de fomento
        orgao_fomento = str(dados.get("orgão_fomento") or dados.get("orgao_fomento") or self.orgao).strip()

        # Status e datas
        status = str(dados.get("status") or "").strip().lower()
        data_abertura = str(dados.get("data_abertura") or "").strip()
        data_encerramento = str(dados.get("data_encerramento") or "").strip()

        # Se status for fechado/encerrado, não processa (filtro determinístico)
        if status in ("fechado", "encerrado", "finalizado"):
            logger.info("Edital com status '%s', ignorando: %s", status, titulo[:80])
            return None

        # Prazo: usa data_encerramento se disponível
        prazo = data_encerramento or data_abertura or ""

        # Constrói resumo_fonte com tags e categoria
        categoria = str(dados.get("categoria") or "").strip()
        tags = dados.get("tags") or []
        tags_str = ", ".join(str(t) for t in tags if str(t).strip())

        resumo_partes = []
        if objeto:
            resumo_partes.append(f"Objeto: {objeto[:300]}")
        if categoria:
            resumo_partes.append(f"Categoria: {categoria}")
        if tags_str:
            resumo_partes.append(f"Tags: {tags_str[:200]}")

        resumo_fonte = " | ".join(resumo_partes) if resumo_partes else ""

        # Cronograma como informação extra
        cronograma = dados.get("cronograma")
        if cronograma and isinstance(cronograma, list):
            eventos = [f"{c.get('evento')}: {c.get('data')}" for c in cronograma if isinstance(c, dict)]
            if eventos:
                resumo_fonte += " | Cronograma: " + "; ".join(eventos[:5])

        # Detecta se é edital IFES (para priorização)
        # Verifica órgão de fomento e tags específicas do IFES
        orgao_lower = orgao_fomento.lower()
        tags_lower = [str(t).lower() for t in tags]
        texto_busca = " ".join([titulo, orgao_lower, categoria, tags_str, objeto]).lower()

        eh_ifes = False
        # 1. Órgão de fomento explícito do IFES
        if any(p in orgao_lower for p in ("ifes", "prppg", "conif", "dirinter", "instituto federal do espírito santo")):
            eh_ifes = True
        # 2. Tags específicas do IFES
        elif any(p in tags_lower for p in ("ifes", "prppg", "conif", "dirinter")):
            eh_ifes = True
        # 3. Título menciona IFES explicitamente
        elif "ifes" in titulo.lower():
            eh_ifes = True
        # 4. PIBIC/PIBITI apenas se contexto IFES (orgão ou tag)
        elif any(p in texto_busca for p in ("pibic", "pibiti", "pivic", "pivit")) and (
            "ifes" in orgao_lower or "ifes" in tags_lower or "prppg" in orgao_lower
        ):
            eh_ifes = True

        return EditalColetado(
            titulo=titulo,
            orgao=orgao_fomento,
            link=link,
            data_publicacao=data_abertura,
            prazo=prazo,
            resumo_fonte=resumo_fonte[:500],
            metadados={
                "categoria": categoria,
                "status": status,
                "tags": tags,
                "cronograma": cronograma,
                "anexos": dados.get("anexos"),
                "arquivo_origem": nome_arquivo,
                "eh_ifes": eh_ifes,  # flag para priorização
            },
        )