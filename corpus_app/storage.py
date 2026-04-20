from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .config import DB_PATH, EXPORT_DIR, PARSED_DIR, STORAGE_DIR, UPLOAD_DIR
from .importer import TeiImporter
from .utils import now_iso, sha256_bytes


class RepositoryStorage:
    def __init__(self) -> None:
        self.importer = TeiImporter()
        self._ensure_dirs()
        self._init_db()

    def _ensure_dirs(self) -> None:
        for path in (STORAGE_DIR, UPLOAD_DIR, PARSED_DIR, EXPORT_DIR):
            path.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    source_label TEXT,
                    title TEXT,
                    sha256 TEXT NOT NULL UNIQUE,
                    declared_encoding TEXT,
                    actual_encoding TEXT,
                    word_count INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    sheet_labels_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    parsed_path TEXT NOT NULL,
                    upload_path TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alignments (
                    alignment_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    master_doc_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    export_path TEXT,
                    FOREIGN KEY(master_doc_id) REFERENCES documents(doc_id)
                );
                """
            )

    def import_document_bytes(
        self,
        *,
        file_name: str,
        source_bytes: bytes,
        display_name: str | None = None,
        source_label: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = sha256_bytes(source_bytes)
        existing = self.get_document_by_sha(fingerprint)
        if existing:
            return existing

        parsed = self.importer.import_document(
            file_name=file_name,
            source_bytes=source_bytes,
            display_name=display_name,
            source_label=source_label,
        )
        doc_id = parsed["doc_id"]
        upload_path = UPLOAD_DIR / f"{doc_id}_{file_name}"
        parsed_path = PARSED_DIR / f"{doc_id}.json"
        upload_path.write_bytes(source_bytes)
        parsed_path.write_text(self.importer.to_json(parsed), encoding="utf-8")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    doc_id, file_name, display_name, source_label, title, sha256,
                    declared_encoding, actual_encoding, word_count, token_count,
                    sheet_labels_json, warnings_json, imported_at, parsed_path, upload_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    parsed["file_name"],
                    parsed["display_name"],
                    parsed["source_label"],
                    parsed["title"],
                    fingerprint,
                    parsed["declared_encoding"],
                    parsed["actual_encoding"],
                    parsed["word_count"],
                    parsed["token_count"],
                    json.dumps(parsed["sheet_labels"], ensure_ascii=False),
                    json.dumps(parsed["warnings"], ensure_ascii=False),
                    now_iso(),
                    str(parsed_path),
                    str(upload_path),
                ),
            )
        return self.get_document(doc_id)

    def import_document_file(self, file_path: Path) -> dict[str, Any]:
        return self.import_document_bytes(
            file_name=file_path.name,
            source_bytes=file_path.read_bytes(),
            display_name=file_path.stem,
            source_label=file_path.stem,
        )

    def get_document(self, doc_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if row is None:
            raise KeyError(f"Document not found: {doc_id}")
        data = dict(row)
        data["sheet_labels"] = json.loads(data.pop("sheet_labels_json"))
        data["warnings"] = json.loads(data.pop("warnings_json"))
        return data

    def get_document_by_sha(self, fingerprint: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT doc_id FROM documents WHERE sha256 = ?", (fingerprint,)).fetchone()
        return self.get_document(row["doc_id"]) if row else None

    def load_parsed_document(self, doc_id: str) -> dict[str, Any]:
        metadata = self.get_document(doc_id)
        parsed_path = Path(metadata["parsed_path"])
        return json.loads(parsed_path.read_text(encoding="utf-8"))

    def list_documents(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT doc_id FROM documents ORDER BY imported_at DESC").fetchall()
        return [self.get_document(row["doc_id"]) for row in rows]

    def list_alignments(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT alignment_id, name, master_doc_id, created_at, updated_at, export_path FROM alignments ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def save_alignment(self, state: dict[str, Any]) -> None:
        now = now_iso()
        state["updated_at"] = now
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM alignments WHERE alignment_id = ?",
                (state["alignment_id"],),
            ).fetchone()
            if exists:
                conn.execute(
                    """
                    UPDATE alignments
                    SET name = ?, master_doc_id = ?, state_json = ?, updated_at = ?, export_path = ?
                    WHERE alignment_id = ?
                    """,
                    (
                        state["name"],
                        state["master_doc_id"],
                        json.dumps(state, ensure_ascii=False),
                        now,
                        state.get("export_path"),
                        state["alignment_id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO alignments (alignment_id, name, master_doc_id, state_json, created_at, updated_at, export_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state["alignment_id"],
                        state["name"],
                        state["master_doc_id"],
                        json.dumps(state, ensure_ascii=False),
                        state.get("created_at", now),
                        now,
                        state.get("export_path"),
                    ),
                )

    def load_alignment(self, alignment_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT state_json FROM alignments WHERE alignment_id = ?", (alignment_id,)).fetchone()
        if row is None:
            raise KeyError(f"Alignment not found: {alignment_id}")
        return json.loads(row["state_json"])

    def save_export(self, alignment_id: str, tei_text: str) -> str:
        export_path = EXPORT_DIR / f"{alignment_id}.xml"
        export_path.write_text(tei_text, encoding="utf-8")
        with self._connect() as conn:
            conn.execute(
                "UPDATE alignments SET export_path = ?, updated_at = updated_at WHERE alignment_id = ?",
                (str(export_path), alignment_id),
            )
        return str(export_path)

    def scan_project_xml_files(self, root: Path) -> list[Path]:
        return sorted(path for path in root.glob("*.xml") if path.is_file())

    def reset_storage(self) -> None:
        if STORAGE_DIR.exists():
            shutil.rmtree(STORAGE_DIR)
        self._ensure_dirs()
        self._init_db()

