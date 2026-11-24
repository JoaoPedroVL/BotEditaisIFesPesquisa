#!/usr/bin/env python3
"""Orquestra o fluxo do robô de editais.

Coleta -> deduplicação -> extração -> análise por IA -> formatação -> envio.

Exemplos:
    python main.py --dry-run --teste-fonte cnpq --limite-itens 2
    python main.py --dry-run
    python main.py                    # executa e envia pelo canal configurado
    python main.py --agendar          # fica rodando e executa todo dia
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from database import BancoEditais, RegistroColeta, gerar_hash  # noqa: E402
from extractor import extrair_texto  # noqa: E402
from llm_client import ErroConfiguracaoLLM, ErroLLM, LLMClient  # noqa: E402
from logging_setup import configurar_logging  # noqa: E402
from notifier import criar_notificador  # noqa: E402
from notifier.base import Notificador, formatar_mensagem, formatar_resumo  # noqa: E402
from prazos import prazo_encerrado  # noqa: E402
from scrapers.base import ScraperBase  # noqa: E402

logger = logging.getLogger("main")


# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------
def carregar_config(caminho: str | Path) -> dict[str, Any]:
    caminho = Path(caminho)
    if not caminho.exists():
        raise SystemExit(f"Arquivo de configuração não encontrado: {caminho}")
    with caminho.open(encoding="utf-8") as arquivo:
        config = yaml.safe_load(arquivo) or {}
    if not isinstance(config, dict):
        raise SystemExit("config.yaml inválido: o topo deve ser um mapa.")
    return config


def criar_scrapers(
    config: dict[str, Any], selecionadas: list[str] | None
) -> tuple[list[ScraperBase], list[str]]:
    """Instancia as fontes ativas. Uma fonte quebrada não impede as demais."""
    coleta_cfg = config.get("coleta") or {}
    scrapers: list[ScraperBase] = []
    nomes_criados: set[str] = set()

    for fonte in coleta_cfg.get("fontes") or []:
        if not isinstance(fonte, dict) or not fonte.get("ativo", True):
            continue
        nome = str(fonte.get("nome") or "").strip()
        if selecionadas and nome not in selecionadas:
            continue

        caminho_classe = str(fonte.get("classe") or "").strip()
        try:
            modulo_nome, classe_nome = caminho_classe.rsplit(".", 1)
            modulo = importlib.import_module(modulo_nome)
            classe = getattr(modulo, classe_nome)
            scraper = classe(fonte, coleta_cfg)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Fonte %s: não foi possível iniciar (%s).", nome, exc)
            continue

        scrapers.append(scraper)
        nomes_criados.add(nome)

    faltantes = sorted(set(selecionadas or []) - nomes_criados)
    return scrapers, faltantes


def preparar_config_extracao(config: dict[str, Any]) -> dict[str, Any]:
    """Herda timeout e pausas da coleta para o extractor."""
    cfg = dict(config.get("extracao") or {})
    coleta = config.get("coleta") or {}
    cfg.setdefault("timeout_segundos", coleta.get("timeout_segundos", 30))
    cfg.setdefault(
        "pausa_minima_segundos", coleta.get("pausa_minima_segundos", 2)
    )
    cfg.setdefault(
        "pausa_maxima_segundos", coleta.get("pausa_maxima_segundos", 3)
    )
    cfg.setdefault("user_agent", coleta.get("user_agent"))
    return cfg


# ----------------------------------------------------------------------
# Processamento
# ----------------------------------------------------------------------
def _entregar(
    *,
    edital_id: int,
    mensagem: str,
    banco: BancoEditais,
    notificador: Notificador | None,
    dry_run: bool,
    pausa: float,
    resumo_acumulado: list[tuple[int, str]] | None = None,
    prefixo: str = "Editais ONG",
) -> bool:
    """Envia (ou imprime, no dry-run). Devolve True quando confirmado.

    Se ``resumo_acumulado`` for informado, a mensagem apenas entra na lista do
    resumo diário (o envio único acontece no fim da execução).
    """
    if resumo_acumulado is not None:
        resumo_acumulado.append((edital_id, mensagem))
        logger.info(
            "Edital id=%s incluído no resumo diário (%d até agora).",
            edital_id,
            len(resumo_acumulado),
        )
        if dry_run:
            print("\n" + mensagem + "\n")
        return False

    if dry_run:
        print("\n" + mensagem + "\n")
        logger.info("DRY-RUN: mensagem impressa, envio não realizado.")
        return False

    if notificador is None:
        logger.warning("Sem notificador configurado; envio ficará pendente.")
        return False

    try:
        # NotificadorEmail aceita prefixo; outros ignoram
        if hasattr(notificador, "enviar") and "prefixo" in notificador.enviar.__code__.co_varnames:
            enviado = notificador.enviar(mensagem, prefixo=prefixo)
        else:
            enviado = notificador.enviar(mensagem)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha inesperada no envio: %s", exc)
        enviado = False

    if enviado:
        banco.marcar_enviado(edital_id)
        if pausa > 0:
            time.sleep(pausa)
    else:
        logger.warning(
            "Envio não confirmado; o edital id=%s continua pendente.", edital_id
        )
    return enviado


def processar_edital(
    item: dict[str, Any],
    *,
    banco: BancoEditais,
    llm: LLMClient,
    notificador_ongs: Notificador | None,
    notificador_ifes: Notificador | None,
    dry_run: bool,
    cfg_extracao: dict[str, Any],
    processados: set[str],
    estado: dict[str, bool],
    pausa_envio: float,
    resumo_ongs: list[tuple[int, str]] | None = None,
    resumo_ifes: list[tuple[int, str]] | None = None,
) -> None:
    """Processa um edital coletado (novo, alterado ou pendente)."""
    link = str(item.get("link") or "").strip()
    titulo = str(item.get("titulo") or "").strip()
    orgao = str(item.get("orgao") or "").strip()
    prazo = str(item.get("prazo") or "").strip()

    if not link or not titulo:
        logger.warning("Item sem título/link ignorado: %s", item)
        return
    if link in processados:
        return
    processados.add(link)

    # Filtro determinístico: se o prazo já passou, marca como encerrado e ignora.
    if prazo and prazo_encerrado(prazo):
        logger.info("Edital com prazo encerrado, ignorando: [%s] %s", orgao, titulo[:80])
        banco.registrar_coleta(
            orgao=orgao, titulo=titulo, link=link, hash_conteudo=None, encerrado=True
        )
        return

    logger.info("Processando: [%s] %s", orgao, titulo[:100])

    # 1) Extração de texto (também serve para calcular o hash do conteúdo).
    texto = ""
    try:
        texto = extrair_texto(link, cfg_extracao)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao extrair texto de %s: %s", link, exc)

    hash_conteudo = gerar_hash(texto) if texto else None

    # 2) Deduplicação / detecção de alteração.
    try:
        registro = banco.registrar_coleta(
            orgao=orgao,
            titulo=titulo,
            link=link,
            hash_conteudo=hash_conteudo,
            encerrado=False,  # se chegou aqui, o prazo não está encerrado
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao gravar coleta de %s: %s", link, exc)
        return

    if registro.novo:
        logger.info("Novo edital registrado (id=%s).", registro.id)
    elif registro.atualizado:
        logger.info("Edital alterado detectado (id=%s).", registro.id)
    elif registro.precisa_analisar:
        logger.info("Edital pendente de análise (id=%s).", registro.id)
    else:
        logger.info("Já visto e sem alteração; ignorando (id=%s).", registro.id)
        return

    if not registro.precisa_analisar:
        return
    if not texto:
        logger.warning(
            "Sem texto extraído; edital id=%s fica na fila para a próxima execução.",
            registro.id,
        )
        return

    # 3) Análise por IA.
    if estado["abortar_ia"]:
        return
    if not llm.tem_chave:
        if not estado["aviso_sem_chave"]:
            logger.error(
                "NVIDIA_API_KEY ausente: análises ficarão na fila. "
                "Preencha o .env para habilitar a IA."
            )
            estado["aviso_sem_chave"] = True
        return

    try:
        analise = llm.analisar_edital(
            texto, orgao=orgao, titulo=titulo, link=link
        )
    except ErroConfiguracaoLLM as exc:
        logger.error("Análise interrompida: %s", exc)
        estado["abortar_ia"] = True
        return
    except ErroLLM as exc:
        logger.error(
            "Análise falhou para id=%s; fica na fila para a próxima execução: %s",
            registro.id,
            exc,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro inesperado na análise id=%s: %s", registro.id, exc)
        return

    banco.salvar_analise(registro.id, analise.dados, analise.modelo)
    status = analise.dados.get("ong_pode_participar", "incerto")
    tipo_edital = analise.dados.get("tipo_edital", "outro")
    logger.info(
        "Análise concluída id=%s | ONG pode participar: %s | Tipo: %s | modelo: %s",
        registro.id,
        status,
        tipo_edital,
        analise.modelo,
    )

    # 4) Filtro final: so envia se ong_pode_participar for sim ou incerto.
    if status == "nao":
        logger.info("ONG não pode participar; edital salvo, sem envio (id=%s).", registro.id)
        return

    mensagem = formatar_mensagem(
        orgao=orgao,
        titulo=titulo,
        link=link,
        resultado=analise.dados,
        atualizado=registro.atualizado,
    )

    # Roteia para o resumo correto baseado no tipo_edital
    if tipo_edital == "instituicoes_federais":
        resumo_alvo = resumo_ifes
        notificador_alvo = notificador_ifes
        prefixo = "Editais IFES"
    else:
        # "ongs" ou "outro" vao para o resumo de ONGs
        resumo_alvo = resumo_ongs
        notificador_alvo = notificador_ongs
        prefixo = "Editais ONG"

    _entregar(
        edital_id=registro.id,
        mensagem=mensagem,
        banco=banco,
        notificador=notificador_alvo,
        dry_run=dry_run,
        pausa=pausa_envio,
        resumo_acumulado=resumo_alvo,
    )


def processar_pendentes_envio(
    *,
    banco: BancoEditais,
    notificador_ongs: Notificador | None,
    notificador_ifes: Notificador | None,
    dry_run: bool,
    pausa: float,
    ignorar_links: set[str] | None = None,
    resumo_ongs: list[tuple[int, str]] | None = None,
    resumo_ifes: list[tuple[int, str]] | None = None,
) -> int:
    """Tenta enviar análises prontas de execuções anteriores."""
    ignorar = ignorar_links or set()
    pendentes = [
        linha for linha in banco.pendentes_envio() if linha["link"] not in ignorar
    ]
    if not pendentes:
        return 0

    enviados = 0
    for linha in pendentes:
        resultado = linha["resultado"]
        tipo_edital = resultado.get("tipo_edital", "outro")

        if tipo_edital == "instituicoes_federais":
            notificador_alvo = notificador_ifes
            resumo_alvo = resumo_ifes
            prefixo = "Editais IFES"
        else:
            notificador_alvo = notificador_ongs
            resumo_alvo = resumo_ongs
            prefixo = "Editais ONG"

        if notificador_alvo is None and not dry_run:
            logger.warning("Há envio pendente para %s, mas notificador não configurado.", tipo_edital)
            continue

        mensagem = formatar_mensagem(
            orgao=linha["orgao"],
            titulo=linha["titulo"],
            link=linha["link"],
            resultado=resultado,
            atualizado=bool(linha.get("atualizado")),
        )
        confirmado = _entregar(
            edital_id=int(linha["id"]),
            mensagem=mensagem,
            banco=banco,
            notificador=notificador_alvo,
            dry_run=dry_run,
            pausa=pausa,
            resumo_acumulado=resumo_alvo,
            prefixo=prefixo,
        )
        enviados += int(confirmado)

    logger.info("Pendentes de envio processados: %d confirmado(s).", enviados)
    return enviados


def enviar_resumo_diario(
    *,
    resumo_ongs: list[tuple[int, str]] | None,
    resumo_ifes: list[tuple[int, str]] | None,
    banco: BancoEditais,
    notificador_ongs: Notificador | None,
    notificador_ifes: Notificador | None,
    dry_run: bool,
) -> int:
    """Envia até dois resumos: um para ONGs e outro para IFES."""
    total_enviados = 0

    # Resumo ONGs
    if resumo_ongs:
        enviados = _enviar_resumo_categoria(
            categoria="ONGs",
            resumo=resumo_ongs,
            banco=banco,
            notificador=notificador_ongs,
            dry_run=dry_run,
            prefixo="Editais ONG",
        )
        total_enviados += enviados

    # Resumo IFES
    if resumo_ifes:
        enviados = _enviar_resumo_categoria(
            categoria="IFES",
            resumo=resumo_ifes,
            banco=banco,
            notificador=notificador_ifes,
            dry_run=dry_run,
            prefixo="Editais IFES",
        )
        total_enviados += enviados

    if not resumo_ongs and not resumo_ifes:
        logger.info("Nenhum edital elegível em nenhuma categoria; nenhum e-mail enviado.")

    return total_enviados


def _enviar_resumo_categoria(
    *,
    categoria: str,
    resumo: list[tuple[int, str]],
    banco: BancoEditais,
    notificador: Notificador | None,
    dry_run: bool,
    prefixo: str,
) -> int:
    """Envia um resumo para uma categoria específica."""
    if not resumo:
        return 0
    if dry_run:
        logger.info(
            "DRY-RUN [%s]: %d edital(is) no resumo; envio não realizado.",
            categoria,
            len(resumo),
        )
        return 0
    if notificador is None:
        logger.warning(
            "Resumo [%s] com %d edital(is), mas nenhum notificador; envio pendente.",
            categoria,
            len(resumo),
        )
        return 0

    mensagem = formatar_resumo([texto for _, texto in resumo])
    try:
        if hasattr(notificador, "enviar") and "prefixo" in notificador.enviar.__code__.co_varnames:
            enviado = notificador.enviar(mensagem, prefixo=prefixo)
        else:
            enviado = notificador.enviar(mensagem)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha inesperada no envio do resumo [%s]: %s", categoria, exc)
        enviado = False

    if not enviado:
        logger.warning(
            "Envio do resumo [%s] não confirmado; %d edital(is) continuam pendentes.",
            categoria,
            len(resumo),
        )
        return 0

    for edital_id, _ in resumo:
        banco.marcar_enviado(edital_id)

    logger.info("Resumo diário [%s] enviado com %d edital(is).", categoria, len(resumo))
    return len(resumo)


# ----------------------------------------------------------------------
# Execução
# ----------------------------------------------------------------------
def executar(
    config: dict[str, Any],
    *,
    fontes: list[str] | None = None,
    dry_run: bool = False,
    limite_itens: int | None = None,
) -> int:
    coleta_cfg = config.get("coleta") or {}
    banco = BancoEditais((config.get("banco") or {}).get("caminho", "data/editais.db"))
    banco.inicializar()

    llm = LLMClient(config.get("ia") or {})
    if not llm.tem_chave:
        logger.warning("NVIDIA_API_KEY não configurada; coleta funcionará sem análise.")

    # Cria dois notificadores de e-mail: um para ONGs, outro para IFES
    notificador_ongs: Notificador | None = None
    notificador_ifes: Notificador | None = None
    if not dry_run:
        try:
            cfg_notif = config.get("notificacao") or {}
            from notifier.email import NotificadorEmail
            notificador_ongs = NotificadorEmail(cfg_notif)
            # Segundo notificador usa EMAIL_DESTINO_IFES
            notificador_ifes = NotificadorEmail(cfg_notif, destino_override=os.getenv("EMAIL_DESTINO_IFES"))
            logger.info("Canais de envio: email (ONGs) + email (IFES)")
        except Exception as exc:  # noqa: BLE001
            logger.error("Notificações desativadas nesta execução: %s", exc)

    scrapers, faltantes = criar_scrapers(config, fontes)
    if faltantes:
        logger.error("Fonte(s) não encontrada(s) no config.yaml: %s", ", ".join(faltantes))
        return 2
    if not scrapers:
        logger.error("Nenhuma fonte ativa para processar.")
        return 1

    cfg_extracao = preparar_config_extracao(config)
    cfg_notificacao = config.get("notificacao") or {}
    pausa_envio = float(cfg_notificacao.get("pausa_entre_mensagens", 2))
    formato = str(cfg_notificacao.get("formato") or "resumo").strip().lower()
    modo_resumo = formato in ("resumo", "digest", "diario", "diário")
    # Dois acumuladores separados
    resumo_ongs: list[tuple[int, str]] | None = [] if modo_resumo else None
    resumo_ifes: list[tuple[int, str]] | None = [] if modo_resumo else None
    if modo_resumo:
        logger.info("Formato de entrega: resumo diário (dois e-mails: ONGs e IFES).")
    limite = limite_itens
    if limite is None:
        limite = int(coleta_cfg.get("max_itens_por_fonte", 25))
    limite = max(1, limite)

    estado = {"abortar_ia": False, "aviso_sem_chave": False}
    processados: set[str] = set()

    logger.info(
        "Execução iniciada | fontes: %s | dry-run: %s | limite/fonte: %d",
        ", ".join(scraper.nome for scraper in scrapers),
        dry_run,
        limite,
    )

    for scraper in scrapers:
        try:
            itens = scraper.coletar()
        except Exception as exc:  # a base já protege, mas garantimos aqui
            logger.exception("Fonte %s falhou: %s", scraper.nome, exc)
            continue

        if not itens:
            logger.warning("Fonte %s não retornou editais.", scraper.nome)
            continue

        logger.info("Fonte %s: processando até %d item(ns).", scraper.nome, limite)
        for item in itens[:limite]:
            processar_edital(
                item,
                banco=banco,
                llm=llm,
                notificador_ongs=notificador_ongs,
                notificador_ifes=notificador_ifes,
                dry_run=dry_run,
                cfg_extracao=cfg_extracao,
                processados=processados,
                estado=estado,
                pausa_envio=pausa_envio,
                resumo_ongs=resumo_ongs,
                resumo_ifes=resumo_ifes,
            )

    # Análises que ficaram pendentes em execuções anteriores.
    if llm.tem_chave and not estado["abortar_ia"]:
        max_pendentes = int(coleta_cfg.get("max_pendentes_analise", 10))
        pendentes = [
            linha
            for linha in banco.pendentes_analise()
            if linha["link"] not in processados
        ][:max_pendentes]
        if pendentes:
            logger.info("Reprocessando %d análise(s) pendente(s).", len(pendentes))
        for linha in pendentes:
            processar_edital(
                {
                    "titulo": linha["titulo"],
                    "orgao": linha["orgao"],
                    "link": linha["link"],
                },
                banco=banco,
                llm=llm,
                notificador_ongs=notificador_ongs,
                notificador_ifes=notificador_ifes,
                dry_run=dry_run,
                cfg_extracao=cfg_extracao,
                processados=processados,
                estado=estado,
                pausa_envio=pausa_envio,
                resumo_ongs=resumo_ongs,
                resumo_ifes=resumo_ifes,
            )

    # Envios pendentes (inclusive de execuções anteriores).
    # Para pendentes, roteia baseado no tipo_edital de cada um
    processar_pendentes_envio(
        banco=banco,
        notificador_ongs=notificador_ongs,
        notificador_ifes=notificador_ifes,
        dry_run=dry_run,
        pausa=pausa_envio,
        ignorar_links=processados,
        resumo_ongs=resumo_ongs,
        resumo_ifes=resumo_ifes,
    )

    # No modo resumo, envia dois e-mails separados.
    if modo_resumo:
        enviar_resumo_diario(
            resumo_ongs=resumo_ongs,
            resumo_ifes=resumo_ifes,
            banco=banco,
            notificador_ongs=notificador_ongs,
            notificador_ifes=notificador_ifes,
            dry_run=dry_run,
        )

    stats = banco.estatisticas()
    logger.info(
        "Resumo do banco | total=%d | pendentes_analise=%d | "
        "pendentes_envio=%d | enviados=%d",
        stats["total"],
        stats["pendentes_analise"],
        stats["pendentes_envio"],
        stats["enviados"],
    )
    logger.info("Execução concluída.")
    return 0


# ----------------------------------------------------------------------
# Agendamento
# ----------------------------------------------------------------------
def agendar(
    config: dict[str, Any],
    *,
    fontes: list[str] | None,
    dry_run: bool,
    limite_itens: int | None,
) -> int:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        logger.error(
            "APScheduler não instalado. Rode: pip install -r requirements.txt"
        )
        return 1

    cfg_ag = config.get("agendamento") or {}
    cron_expr = cfg_ag.get("cron")

    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")

    if cron_expr:
        # Usa expressão cron completa (ex: "0 6 * * 1,4" = seg/qui 06:00)
        scheduler.add_job(
            executar,
            "cron",
            cron=cron_expr,
            kwargs={
                "config": config,
                "fontes": fontes,
                "dry_run": dry_run,
                "limite_itens": limite_itens,
            },
            id="monitor-editais",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Agendado com cron: %s (America/Sao_Paulo). Pressione Ctrl+C para sair.",
            cron_expr,
        )
    else:
        # Fallback: horario legado "HH:MM" (diário)
        horario = str(cfg_ag.get("horario", "07:00"))
        try:
            hora, minuto = (int(parte) for parte in horario.split(":"))
        except (ValueError, TypeError):
            logger.error("Horário inválido no config.yaml: %r (use HH:MM).", horario)
            return 2

        scheduler.add_job(
            executar,
            "cron",
            hour=hora,
            minute=minuto,
            kwargs={
                "config": config,
                "fontes": fontes,
                "dry_run": dry_run,
                "limite_itens": limite_itens,
            },
            id="monitor-editais",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        logger.info(
            "Agendado para todos os dias às %02d:%02d (America/Sao_Paulo). "
            "Pressione Ctrl+C para sair.",
            hora,
            minuto,
        )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Agendador encerrado.")
    return 0


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Robô de monitoramento de editais para ONGs."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Faz tudo, mas imprime as mensagens em vez de enviar.",
    )
    parser.add_argument(
        "--teste-fonte",
        action="append",
        dest="fontes",
        metavar="NOME",
        help="Processa apenas a fonte indicada (pode repetir).",
    )
    parser.add_argument(
        "--limite-itens",
        type=int,
        default=None,
        help="Máximo de itens por fonte nesta execução (para testes).",
    )
    parser.add_argument(
        "--config",
        default=str(BASE_DIR / "config.yaml"),
        help="Caminho do config.yaml.",
    )
    parser.add_argument(
        "--agendar",
        action="store_true",
        help="Mantém o processo rodando e executa diariamente no horário configurado.",
    )
    parser.add_argument("--debug", action="store_true", help="Loga em nível DEBUG.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = criar_parser().parse_args(argv)
    configurar_logging(logging.DEBUG if args.debug else logging.INFO)

    if args.limite_itens is not None and args.limite_itens < 1:
        logger.error("--limite-itens deve ser maior que zero.")
        return 2

    config = carregar_config(args.config)

    if args.agendar:
        return agendar(
            config,
            fontes=args.fontes,
            dry_run=args.dry_run,
            limite_itens=args.limite_itens,
        )

    return executar(
        config,
        fontes=args.fontes,
        dry_run=args.dry_run,
        limite_itens=args.limite_itens,
    )


if __name__ == "__main__":
    sys.exit(main())
