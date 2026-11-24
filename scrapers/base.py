"""Classe base dos scrapers.

Todas as fontes seguem o mesmo contrato:

    scraper.coletar() -> list[dict]

Cada item tem: titulo, orgao, link, data_publicacao, prazo e resumo_fonte.

A base cuida de:
- User-Agent identificado;
- respeito ao robots.txt (com cache por domínio);
- pausa aleatória de 2 a 3 s entre requisições;
- timeout e tratamento de erro (uma fonte com defeito não derruba o robô);
- normalização de links e pré-filtro por palavras-chave.
"""

from __future__ import annotations

import logging
import random
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PALAVRAS_PADRAO = [
    "edital",
    "chamada pública",
    "chamada publica",
    "chamada",
    "seleção",
    "selecao",
    "fomento",
    "apoio",
    "projetos",
]


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados (para comparação)."""
    if not texto:
        return ""
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


@dataclass
class EditalColetado:
    titulo: str
    orgao: str
    link: str
    data_publicacao: str = ""
    prazo: str = ""
    # Texto curto da listagem; ajuda a IA quando a página do edital é pobre.
    resumo_fonte: str = ""
    metadados: dict[str, Any] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScraperBase(ABC):
    """Base para scrapers de listagens de editais."""

    nome = "base"
    orgao = ""

    def __init__(
        self, config_fonte: dict[str, Any], config_coleta: dict[str, Any] | None = None
    ) -> None:
        self.config_fonte = config_fonte or {}
        self.config_coleta = config_coleta or {}

        self.nome = str(self.config_fonte.get("nome") or self.nome)
        self.orgao = str(self.config_fonte.get("orgao") or self.orgao or self.nome.upper())
        self.url = str(self.config_fonte.get("url") or "").strip()
        if not self.url:
            raise ValueError(f"Fonte {self.nome}: campo 'url' não configurado")

        self.usa_playwright = bool(self.config_fonte.get("usa_playwright", False))
        self.user_agent = str(
            self.config_coleta.get(
                "user_agent",
                "MonitorEditaisONG/1.0 (+contato: diretor@exemplo.org.br)",
            )
        )
        self.timeout = float(self.config_coleta.get("timeout_segundos", 30))
        self.pausa_min = max(0.0, float(self.config_coleta.get("pausa_minima_segundos", 2)))
        self.pausa_max = max(self.pausa_min, float(self.config_coleta.get("pausa_maxima_segundos", 3)))

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
            }
        )

        # Cache de robots.txt por origem (scheme + host).
        self._robots: dict[str, RobotFileParser | None] = {}

    # ------------------------------------------------------------------
    # Contrato público
    # ------------------------------------------------------------------
    def coletar(self) -> list[dict[str, Any]]:
        """Coleta e devolve os editais já filtrados. Nunca levanta exceção."""
        logger.info("Fonte %s: iniciando coleta em %s", self.nome, self.url)
        try:
            html = self._baixar(self.url)
            brutos = self.extrair(html) or []
            itens = self._normalizar_itens(brutos)
            logger.info(
                "Fonte %s: %d itens brutos, %d após filtro/deduplicação.",
                self.nome,
                len(brutos),
                len(itens),
            )
            return [item.como_dict() for item in itens]
        except Exception as exc:  # noqa: BLE001 - queremos logar e seguir
            logger.exception("Fonte %s: falha na coleta: %s", self.nome, exc)
            return []

    @abstractmethod
    def extrair(self, html: str) -> list[EditalColetado]:
        """Extrai os editais do HTML da listagem."""

    # ------------------------------------------------------------------
    # HTTP / robots / pausa
    # ------------------------------------------------------------------
    def _pausar(self) -> None:
        if self.pausa_max <= 0:
            return
        time.sleep(random.uniform(self.pausa_min, self.pausa_max))

    def _robots_permite(self, url: str) -> bool:
        """Consulta e respeita o robots.txt do domínio (cache)."""
        partes = urlparse(url)
        origem = f"{partes.scheme}://{partes.netloc}"

        if origem in self._robots:
            robots = self._robots[origem]
        else:
            robots = None
            try:
                self._pausar()
                resposta = self.session.get(
                    f"{origem}/robots.txt", timeout=self.timeout
                )
                if resposta.status_code == 200:
                    robots = RobotFileParser()
                    robots.parse(resposta.text.splitlines())
                    logger.debug("robots.txt carregado de %s", origem)
                else:
                    logger.warning(
                        "robots.txt de %s retornou HTTP %s; assumindo permitido.",
                        origem,
                        resposta.status_code,
                    )
            except requests.RequestException as exc:
                logger.warning(
                    "Não foi possível ler robots.txt de %s (%s); assumindo permitido.",
                    origem,
                    exc,
                )
            self._robots[origem] = robots

        if robots is None:
            return True
        permitido = robots.can_fetch(self.user_agent, url)
        if not permitido:
            logger.warning("robots.txt proíbe acesso a %s", url)
        return permitido

    def _baixar(self, url: str) -> str:
        """Baixa uma URL de listagem como texto, respeitando robots e pausa."""
        if not self._robots_permite(url):
            raise PermissionError(f"acesso proibido pelo robots.txt: {url}")

        self._pausar()
        resposta = self.session.get(url, timeout=self.timeout)
        resposta.raise_for_status()

        tipo = (resposta.headers.get("Content-Type") or "").lower()
        if "application/pdf" in tipo:
            raise ValueError(f"a listagem retornou PDF em vez de HTML: {url}")

        # Alguns sites não declaram charset; requests usa ISO-8859-1 por padrão.
        if resposta.encoding in (None, "ISO-8859-1"):
            resposta.encoding = resposta.apparent_encoding
        return resposta.text

    def _baixar_playwright(self, url: str) -> str:
        """Fallback para páginas que só renderizam conteúdo via JavaScript."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright não instalado. Rode: pip install -r requirements.txt "
                "&& playwright install chromium"
            ) from exc

        if not self._robots_permite(url):
            raise PermissionError(f"acesso proibido pelo robots.txt: {url}")

        self._pausar()
        with sync_playwright() as playwright:
            navegador = playwright.chromium.launch(headless=True)
            pagina = navegador.new_page(user_agent=self.user_agent)
            pagina.goto(url, timeout=self.timeout * 1000, wait_until="networkidle")
            html = pagina.content()
            navegador.close()
        return html

    # ------------------------------------------------------------------
    # Normalização / filtro
    # ------------------------------------------------------------------
    def _normalizar_itens(
        self, brutos: list[EditalColetado | dict[str, Any]]
    ) -> list[EditalColetado]:
        # Prioriza palavras-chave da fonte, cai para global, depois padrão
        palavras_fonte = self.config_fonte.get("palavras_chave")
        palavras = palavras_fonte or self.config_coleta.get("palavras_chave") or PALAVRAS_PADRAO
        palavras_norm = [normalizar_texto(p) for p in palavras if normalizar_texto(p)]
        usar_prefiltro = bool(self.config_fonte.get("prefiltro_palavras_chave", True))

        vistos: set[str] = set()
        resultado: list[EditalColetado] = []

        for bruto in brutos:
            item = bruto if isinstance(bruto, EditalColetado) else EditalColetado(**bruto)
            item.titulo = re.sub(r"\s+", " ", item.titulo or "").strip()
            item.link = urljoin(self.url, (item.link or "").strip())
            item.orgao = (item.orgao or self.orgao).strip()
            item.data_publicacao = (item.data_publicacao or "").strip()
            item.prazo = (item.prazo or "").strip()

            if not item.titulo or not item.link:
                continue
            if item.link.startswith(("javascript:", "mailto:", "#")):
                continue
            if item.link in vistos:
                continue

            if usar_prefiltro:
                titulo_norm = normalizar_texto(item.titulo)
                if not any(palavra in titulo_norm for palavra in palavras_norm):
                    logger.debug("Item descartado pelo filtro: %s", item.titulo[:80])
                    continue

            vistos.add(item.link)
            resultado.append(item)

        return resultado
