"""Banco SQLite: editais já vistos, análises e status de envio.

Regras:
- o link é único (deduplicação);
- ``hash_conteudo`` permite detectar edital alterado e reanalisar;
- ``analisado`` fica 0 quando a IA falha, para nova tentativa;
- ``enviado`` fica 0 quando o envio falha, para nova tentativa.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS editais (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    orgao           TEXT    NOT NULL DEFAULT '',
    titulo          TEXT    NOT NULL,
    link            TEXT    NOT NULL UNIQUE,
    hash_conteudo   TEXT,
    data_coleta     TEXT    NOT NULL,
    analisado       INTEGER NOT NULL DEFAULT 0,
    enviado         INTEGER NOT NULL DEFAULT 0,
    encerrado       INTEGER NOT NULL DEFAULT 0,
    resultado_json  TEXT,
    atualizado      INTEGER NOT NULL DEFAULT 0,
    modelo          TEXT,
    data_analise    TEXT,
    data_envio      TEXT
);
CREATE INDEX IF NOT EXISTS idx_editais_pendentes
    ON editais (analisado, enviado);
"""

# Migração leve para bancos criados por versões anteriores.
COLUNAS_EXTRAS = {
    "atualizado": "INTEGER NOT NULL DEFAULT 0",
    "modelo": "TEXT",
    "data_analise": "TEXT",
    "data_envio": "TEXT",
    "encerrado": "INTEGER NOT NULL DEFAULT 0",
    "tipo_edital": "TEXT DEFAULT 'outro'",
}


def gerar_hash(texto: str) -> str:
    """Hash estável do conteúdo (ignora diferenças de espaço/maiúsculas)."""
    normalizado = re.sub(r"\s+", " ", texto or "").strip().lower()
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()


@dataclass
class RegistroColeta:
    id: int
    novo: bool
    atualizado: bool
    precisa_analisar: bool


class BancoEditais:
    def __init__(self, caminho: str = "data/editais.db") -> None:
        caminho_path = Path(caminho).expanduser()
        if not caminho_path.is_absolute():
            caminho_path = BASE_DIR / caminho_path
        self.caminho = caminho_path
        self.caminho.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Infra
    # ------------------------------------------------------------------
    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        conexao = sqlite3.connect(self.caminho, timeout=30)
        conexao.row_factory = sqlite3.Row
        try:
            yield conexao
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def inicializar(self) -> None:
        with self._conexao() as conexao:
            conexao.executescript(SCHEMA)
            existentes = {
                linha["name"]
                for linha in conexao.execute("PRAGMA table_info(editais)").fetchall()
            }
            for coluna, definicao in COLUNAS_EXTRAS.items():
                if coluna not in existentes:
                    conexao.execute(
                        f"ALTER TABLE editais ADD COLUMN {coluna} {definicao}"
                    )
                    logger.info("Banco: coluna %s adicionada.", coluna)
        logger.info("Banco pronto em %s", self.caminho)

    # ------------------------------------------------------------------
    # Coleta / deduplicação
    # ------------------------------------------------------------------
    def obter_por_link(self, link: str) -> dict[str, Any] | None:
        with self._conexao() as conexao:
            linha = conexao.execute(
                "SELECT * FROM editais WHERE link = ?", (link,)
            ).fetchone()
            return dict(linha) if linha else None

    def registrar_coleta(
        self,
        *,
        orgao: str,
        titulo: str,
        link: str,
        hash_conteudo: str | None,
        encerrado: bool = False,
    ) -> RegistroColeta:
        """Insere ou atualiza a coleta e informa se precisa (re)analisar."""
        agora = datetime.now().isoformat(timespec="seconds")

        with self._conexao() as conexao:
            linha = conexao.execute(
                "SELECT id, hash_conteudo, analisado FROM editais WHERE link = ?",
                (link,),
            ).fetchone()

            if linha is None:
                cursor = conexao.execute(
                    """
                    INSERT INTO editais
                        (orgao, titulo, link, hash_conteudo, data_coleta,
                         analisado, enviado, atualizado, encerrado)
                    VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?)
                    """,
                    (orgao, titulo, link, hash_conteudo, agora, int(encerrado)),
                )
                return RegistroColeta(
                    id=int(cursor.lastrowid),
                    novo=True,
                    atualizado=False,
                    precisa_analisar=not encerrado,
                )

            id_existente = int(linha["id"])
            hash_antigo = linha["hash_conteudo"]
            alterado = bool(
                hash_conteudo and hash_antigo and hash_conteudo != hash_antigo
            )

            if alterado:
                logger.info("Conteúdo alterado, reanalisando: %s", titulo[:80])
                conexao.execute(
                    """
                    UPDATE editais
                       SET orgao = ?, titulo = ?, hash_conteudo = ?,
                           data_coleta = ?, analisado = 0, enviado = 0,
                           resultado_json = NULL, modelo = NULL,
                           data_analise = NULL, atualizado = 1, encerrado = ?
                     WHERE id = ?
                    """,
                    (orgao, titulo, hash_conteudo, agora, int(encerrado), id_existente),
                )
                return RegistroColeta(id_existente, False, True, not encerrado)

            # Hash novo preenchendo uma lacuna (extração falhou antes).
            precisa = False
            if hash_conteudo and not hash_antigo:
                conexao.execute(
                    """
                    UPDATE editais
                       SET orgao = ?, titulo = ?, hash_conteudo = ?,
                           data_coleta = ?, analisado = 0, enviado = 0,
                           encerrado = ?
                     WHERE id = ?
                    """,
                    (orgao, titulo, hash_conteudo, agora, int(encerrado), id_existente),
                )
                precisa = True
            else:
                conexao.execute(
                    """
                    UPDATE editais
                       SET orgao = ?, titulo = ?, data_coleta = ?, encerrado = ?
                     WHERE id = ?
                    """,
                    (orgao, titulo, agora, int(encerrado), id_existente),
                )

            return RegistroColeta(
                id=id_existente,
                novo=False,
                atualizado=False,
                precisa_analisar=precisa or not bool(linha["analisado"]),
            )

    # ------------------------------------------------------------------
    # Análise
    # ------------------------------------------------------------------
    def salvar_analise(
        self, edital_id: int, resultado: dict[str, Any], modelo: str
    ) -> None:
        agora = datetime.now().isoformat(timespec="seconds")
        # Marca como encerrado se a IA disse que as inscrições não estão abertas.
        encerrado = str(resultado.get("inscricoes_abertas", "incerto")).strip().lower() == "nao"
        tipo_edital = str(resultado.get("tipo_edital", "outro")).strip().lower()
        with self._conexao() as conexao:
            conexao.execute(
                """
                UPDATE editais
                   SET analisado = 1, resultado_json = ?, modelo = ?,
                       data_analise = ?, encerrado = ?, tipo_edital = ?
                 WHERE id = ?
                """,
                (
                    json.dumps(resultado, ensure_ascii=False),
                    modelo,
                    agora,
                    int(encerrado),
                    tipo_edital,
                    edital_id,
                ),
            )

    def pendentes_analise(self) -> list[dict[str, Any]]:
        with self._conexao() as conexao:
            linhas = conexao.execute(
                """
                SELECT * FROM editais
                 WHERE analisado = 0 AND hash_conteudo IS NOT NULL
                 ORDER BY data_coleta ASC
                """
            ).fetchall()
            return [dict(linha) for linha in linhas]

    # ------------------------------------------------------------------
    # Envio
    # ------------------------------------------------------------------
    def pendentes_envio(self) -> list[dict[str, Any]]:
        """Análises prontas e ainda não enviadas, apenas sim/incerto."""
        with self._conexao() as conexao:
            linhas = conexao.execute(
                """
                SELECT * FROM editais
                 WHERE analisado = 1 AND enviado = 0 AND encerrado = 0
                 ORDER BY data_coleta ASC
                """
            ).fetchall()

        pendentes: list[dict[str, Any]] = []
        for linha in linhas:
            try:
                resultado = json.loads(linha["resultado_json"] or "{}")
            except (TypeError, ValueError):
                logger.warning(
                    "Resultado JSON inválido no banco para o edital id=%s", linha["id"]
                )
                continue
            if resultado.get("ong_pode_participar") not in ("sim", "incerto"):
                continue
            item = dict(linha)
            item["resultado"] = resultado
            pendentes.append(item)
        return pendentes

    def marcar_enviado(self, edital_id: int) -> None:
        agora = datetime.now().isoformat(timespec="seconds")
        with self._conexao() as conexao:
            conexao.execute(
                """
                UPDATE editais
                   SET enviado = 1, atualizado = 0, data_envio = ?
                 WHERE id = ?
                """,
                (agora, edital_id),
            )

    # ------------------------------------------------------------------
    # Estatísticas
    # ------------------------------------------------------------------
    def estatisticas(self) -> dict[str, int]:
        with self._conexao() as conexao:
            linha = conexao.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN analisado = 0 THEN 1 ELSE 0 END) AS pendentes_analise,
                    SUM(CASE WHEN enviado = 1 THEN 1 ELSE 0 END) AS enviados
                  FROM editais
                """
            ).fetchone()
            resultado = {chave: int(linha[chave] or 0) for chave in linha.keys()}
        # Conta apenas sim/incerto, coerente com o filtro de envio.
        resultado["pendentes_envio"] = len(self.pendentes_envio())
        return resultado
