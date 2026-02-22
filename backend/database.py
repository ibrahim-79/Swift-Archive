import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "archive.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Main documents table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            ocr_performed INTEGER DEFAULT 0,
            confidence_score REAL DEFAULT 0.0,
            extracted_text TEXT DEFAULT '',
            ocr_details TEXT DEFAULT '[]',
            uploaded_at TEXT NOT NULL,
            processing_time_ms INTEGER DEFAULT 0
        )
    """)

    # FTS5 virtual table for full-text search indexing
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            filename,
            extracted_text,
            content='documents',
            content_rowid='id',
            tokenize='porter unicode61'
        )
    """)

    # Triggers to keep FTS index in sync
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, filename, extracted_text)
            VALUES (new.id, new.filename, new.extracted_text);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, filename, extracted_text)
            VALUES ('delete', old.id, old.filename, old.extracted_text);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, filename, extracted_text)
            VALUES ('delete', old.id, old.filename, old.extracted_text);
            INSERT INTO documents_fts(rowid, filename, extracted_text)
            VALUES (new.id, new.filename, new.extracted_text);
        END
    """)

    conn.commit()
    conn.close()


def insert_document(
    filename: str,
    file_type: str,
    file_path: str,
    file_size: int,
    ocr_performed: bool,
    confidence_score: float,
    extracted_text: str,
    ocr_details: list,
    processing_time_ms: int,
) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO documents
            (filename, file_type, file_path, file_size, ocr_performed,
             confidence_score, extracted_text, ocr_details, uploaded_at, processing_time_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            filename,
            file_type,
            file_path,
            file_size,
            1 if ocr_performed else 0,
            confidence_score,
            extracted_text,
            json.dumps(ocr_details),
            datetime.utcnow().isoformat(),
            processing_time_ms,
        ),
    )
    doc_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return doc_id


def search_documents(query: str, limit: int = 50, offset: int = 0) -> list:
    conn = get_connection()
    cursor = conn.cursor()

    if not query or query.strip() == "":
        cursor.execute(
            """
            SELECT * FROM documents ORDER BY uploaded_at DESC LIMIT ? OFFSET ?
        """,
            (limit, offset),
        )
    else:
        # Use FTS5 for fast full-text search
        fts_query = " OR ".join(
            [f'"{term}"' for term in query.strip().split() if term]
        )
        cursor.execute(
            """
            SELECT d.*, highlight(documents_fts, 1, '<mark>', '</mark>') AS highlighted_text
            FROM documents_fts fts
            JOIN documents d ON d.id = fts.rowid
            WHERE documents_fts MATCH ?
            ORDER BY rank
            LIMIT ? OFFSET ?
        """,
            (fts_query, limit, offset),
        )

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_all_documents(limit: int = 100, offset: int = 0) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM documents ORDER BY uploaded_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_document_by_id(doc_id: int) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_document(doc_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_document_count(query: str = "") -> int:
    conn = get_connection()
    cursor = conn.cursor()
    if not query or query.strip() == "":
        cursor.execute("SELECT COUNT(*) FROM documents")
    else:
        fts_query = " OR ".join(
            [f'"{term}"' for term in query.strip().split() if term]
        )
        cursor.execute(
            "SELECT COUNT(*) FROM documents_fts WHERE documents_fts MATCH ?",
            (fts_query,),
        )
    count = cursor.fetchone()[0]
    conn.close()
    return count
