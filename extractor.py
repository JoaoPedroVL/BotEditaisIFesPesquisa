"""Extração de texto de páginas HTML e de PDFs de editais.

Fluxo:
1. baixa a página do edital;
2. remove menus, scripts, rodapés e navegação;
3. encontra links de PDF (edital/anexos) e extrai o texto com pdfplumber;
4. limpa espaços/repetições;
5. se o texto passar do limite, prioriza trechos com palavras importantes
   (objeto, público-alvo, elegibilidade, requisitos, prazo, valor etc.).
"""

from __future__ import annotations

import io
import logging
import random
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT_PADRAO = "MonitorEditaisONG/1.0 (+contato: diretor@exemplo.org.br)"

PALAVRAS_PRIORIZADAS_PADRAO = [
    "objeto",
    "quem pode participar",
    "público-alvo",
    "publico-alvo",
    "elegibilidade",
    "requisitos",
    "prazo",
    "inscrições",
    "inscricoes",
    "valor",
    "recursos",
    "contrapartida",
]

# Evita baixar arquivos gigantes por acidente (25 MB).
TAMANHO_MAXIMO_PDF = 25 * 1024 * 1024
MAX_PAGINAS_PDF = 40


# ----------------------------------------------------------------------
# Limpeza / priorização (funções puras, testáveis)
# ----------------------------------------------------------------------
def limpar_texto(texto: str) -> str:
    """Remove espaços repetidos, linhas vazias em excesso e duplicatas seguidas."""
    if not texto:
        return ""

    texto = texto.replace("\xa0", " ").replace("\r", "")
    linhas: list[str] = []

    for linha in texto.splitlines():
        linha = re.sub(r"[ \t]+", " ", linha).strip()
        if not linha:
            if linhas and linhas[-1] != "":
                linhas.append("")
            continue
        # Linhas de um único símbolo costumam ser lixo de layout.
        if len(linha) < 2 and not linha.isalnum():
            continue
        if linhas and linha == linhas[-1]:
            continue
        linhas.append(linha)

    limpo = "\n".join(linhas)
    limpo = re.sub(r"\n{3,}", "\n\n", limpo)
    return limpo.strip()


def _normalizar_para_busca(texto: str) -> str:
    import unicodedata

    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sem_acento).lower()


def limitar_texto(
    texto: str,
    limite: int = 12000,
    palavras_priorizadas: list[str] | None = None,
) -> str:
    """Corta o texto no limite, priorizando trechos com palavras-chave.

    O começo do documento é sempre mantido (título, data, objeto). Depois,
    entram primeiro os parágrafos que citam elegibilidade, prazo, valor etc.
    """
    if len(texto) <= limite:
        return texto

    palavras = palavras_priorizadas or PALAVRAS_PRIORIZADAS_PADRAO
    palavras_norm = [_normalizar_para_busca(p) for p in palavras if p.strip()]

    blocos = [b.strip() for b in texto.split("\n") if b.strip()]
    if not blocos:
        return texto[:limite]

    # Cabeçalho: primeiros parágrafos, até 35% do limite.
    orcamento_cabeca = max(1000, int(limite * 0.35))
    cabeca: list[str] = []
    usados = 0
    indice_inicio = 0
    for i, bloco in enumerate(blocos):
        if usados + len(bloco) + 1 > orcamento_cabeca and cabeca:
            indice_inicio = i
            break
        cabeca.append(bloco)
        usados += len(bloco) + 1
        indice_inicio = i + 1

    # Corpo: pontua os parágrafos restantes pelas palavras-chave.
    candidatos: list[tuple[int, int, str]] = []
    for i, bloco in enumerate(blocos[indice_inicio:], start=indice_inicio):
        bloco_norm = _normalizar_para_busca(bloco)
        pontos = sum(1 for palavra in palavras_norm if palavra and palavra in bloco_norm)
        if pontos:
            candidatos.append((pontos, i, bloco))

    restante = limite - usados - 100  # margem para os marcadores
    selecionados: list[tuple[int, str]] = []
    for _, i, bloco in sorted(candidatos, key=lambda x: (-x[0], x[1])):
        if restante <= 0:
            break
        if len(bloco) > restante:
            bloco = bloco[:restante]
        selecionados.append((i, bloco))
        restante -= len(bloco) + 1

    if not selecionados:
        # Nenhum trecho relevante: completa com o texto na ordem original.
        resto = "\n".join(blocos[indice_inicio:])
        return (("\n".join(cabeca) + "\n\n" + resto)[:limite]).rstrip()

    selecionados.sort(key=lambda x: x[0])
    corpo = "\n".join(bloco for _, bloco in selecionados)
    resultado = (
        "\n".join(cabeca)
        + "\n\n[...trechos priorizados do edital...]\n\n"
        + corpo
        + "\n\n[...texto truncado...]"
    )
    return resultado[:limite]


# ----------------------------------------------------------------------
# Extração
# ----------------------------------------------------------------------
def extrair_texto(
    url: str,
    config: dict[str, Any] | None = None,
    sessao: requests.Session | None = None,
) -> str:
    """Baixa a página/PDF do edital e devolve o texto limpo e limitado."""
    cfg = config or {}
    limite = int(cfg.get("limite_caracteres", 12000))
    palavras = cfg.get("palavras_priorizadas") or PALAVRAS_PRIORIZADAS_PADRAO
    timeout = float(cfg.get("timeout_segundos", 30))
    pausa_min = max(0.0, float(cfg.get("pausa_minima_segundos", 2)))
    pausa_max = max(pausa_min, float(cfg.get("pausa_maxima_segundos", 3)))
    max_pdfs = max(0, int(cfg.get("max_pdfs", 2)))

    sess = sessao or requests.Session()
    sess.headers.setdefault("User-Agent", cfg.get("user_agent", USER_AGENT_PADRAO))

    def pausar() -> None:
        if pausa_max > 0:
            time.sleep(random.uniform(pausa_min, pausa_max))

    caminho = urlparse(url).path.lower()
    partes: list[str] = []

    if caminho.endswith(".pdf"):
        pausar()
        texto_pdf = _extrair_pdf_de_url(url, sess, timeout)
        if texto_pdf:
            partes.append(texto_pdf)
    else:
        pausar()
        resposta = sess.get(url, timeout=timeout)
        resposta.raise_for_status()

        tipo = (resposta.headers.get("Content-Type") or "").lower()
        if "application/pdf" in tipo:
            texto_pdf = _extrair_pdf_de_bytes(resposta.content)
            if texto_pdf:
                partes.append(texto_pdf)
        else:
            if resposta.encoding in (None, "ISO-8859-1"):
                resposta.encoding = resposta.apparent_encoding
            soup = BeautifulSoup(resposta.text, "lxml")
            partes.append(_texto_do_html(soup))

            # PDFs anexados: baixa no máximo `max_pdfs`, começando pelos mais
            # prováveis (texto com "edital", "chamada" ou "regulamento").
            if max_pdfs:
                for pdf_url in _encontrar_pdfs(soup, url)[:max_pdfs]:
                    pausar()
                    texto_pdf = _extrair_pdf_de_url(pdf_url, sess, timeout)
                    if texto_pdf:
                        partes.append(
                            f"\n\n[Conteúdo do PDF: {pdf_url}]\n\n{texto_pdf}"
                        )

    texto = limpar_texto("\n".join(parte for parte in partes if parte))
    if not texto:
        raise ValueError(f"não foi possível extrair texto de {url}")

    return limitar_texto(texto, limite=limite, palavras_priorizadas=palavras)


def _texto_do_html(soup: BeautifulSoup) -> str:
    for tag in soup(
        ["script", "style", "noscript", "svg", "form", "nav", "header", "footer", "aside", "button"]
    ):
        tag.decompose()

    principal = (
        soup.select_one("main")
        or soup.select_one("article")
        or soup.select_one("#content")
        or soup.select_one(".content")
        or soup.body
        or soup
    )
    return principal.get_text("\n")


def _encontrar_pdfs(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Lista links de PDF, priorizando os que parecem ser o edital principal."""
    diretos: list[tuple[int, int, str]] = []
    provaveis: list[tuple[int, int, str]] = []

    for ordem, a in enumerate(soup.find_all("a", href=True)):
        href = urljoin(base_url, a["href"].strip())
        if not href.startswith(("http://", "https://")):
            continue
        texto = _normalizar_para_busca(a.get_text(" ", strip=True))
        caminho = urlparse(href).path.lower()

        if caminho.endswith(".pdf"):
            prioridade = 0 if any(p in texto for p in ("edital", "chamada", "regulamento")) else 1
            diretos.append((prioridade, ordem, href))
        elif any(p in texto for p in ("edital", "chamada", "regulamento")):
            # Links sem extensão que costumam servir PDF (ex.: gov.br/arquivo).
            if not caminho.endswith((".html", ".htm", ".php", ".aspx")):
                provaveis.append((2, ordem, href))

    ordenados = sorted(diretos + provaveis)
    vistos: set[str] = set()
    resultado: list[str] = []
    for _, _, href in ordenados:
        if href in vistos:
            continue
        vistos.add(href)
        resultado.append(href)
    return resultado


def _extrair_pdf_de_url(
    url: str, sessao: requests.Session, timeout: float
) -> str | None:
    try:
        resposta = sessao.get(url, timeout=timeout, stream=True)
        resposta.raise_for_status()

        tipo = (resposta.headers.get("Content-Type") or "").lower()
        tamanho = resposta.headers.get("Content-Length")
        if tamanho and int(tamanho) > TAMANHO_MAXIMO_PDF:
            logger.warning("PDF ignorado por tamanho (%s bytes): %s", tamanho, url)
            return None
        if "pdf" not in tipo and not urlparse(url).path.lower().endswith(".pdf"):
            logger.debug("Link não retornou PDF (%s): %s", tipo, url)
            return None

        conteudo = resposta.content
        if len(conteudo) > TAMANHO_MAXIMO_PDF:
            logger.warning("PDF ignorado por tamanho: %s", url)
            return None
    except requests.RequestException as exc:
        logger.warning("Falha ao baixar PDF %s: %s", url, exc)
        return None

    return _extrair_pdf_de_bytes(conteudo, url)


def _extrair_pdf_de_bytes(conteudo: bytes, origem: str = "") -> str | None:
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber não instalado; PDF não será lido.")
        return None

    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            paginas = []
            for pagina in pdf.pages[:MAX_PAGINAS_PDF]:
                texto = pagina.extract_text() or ""
                if texto.strip():
                    paginas.append(texto)
    except Exception as exc:  # noqa: BLE001 - PDFs corrompidos são comuns
        logger.warning("Falha ao ler PDF %s: %s", origem or "(memória)", exc)
        return None

    return "\n".join(paginas)
