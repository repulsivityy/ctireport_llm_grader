import os
import json
import sqlite3
import datetime
from typing import List, Optional
import pandas as pd

from schemas import SubmissionRecord, GradingResult, Level1Assessment, IntegrityReview

# Configuration
COLLECTION_NAME = os.getenv("FIRESTORE_COLLECTION", "cti_submissions")
GCP_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("PROJECT_ID", None))
SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), "submissions.db")

_firestore_client = None
_use_firestore = None


def get_firestore_client():
    """Lazily initializes the Firestore client if available."""
    global _firestore_client, _use_firestore
    if _use_firestore is not None:
        return _firestore_client

    try:
        from google.cloud import firestore
        _firestore_client = firestore.Client(project=GCP_PROJECT)
        _use_firestore = True
    except Exception:
        _firestore_client = None
        _use_firestore = False
    
    return _firestore_client


# ==========================================
# SQLITE FALLBACK IMPLEMENTATION
# ==========================================
def _init_sqlite_db(db_path: str = SQLITE_DB_PATH):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                submission_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                student_name TEXT NOT NULL,
                student_email TEXT NOT NULL,
                student_email_lower TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                report_title TEXT NOT NULL,
                report_type TEXT NOT NULL,
                filename TEXT,
                file_type TEXT NOT NULL,
                report_content TEXT NOT NULL,
                total_score INTEGER NOT NULL,
                percentage_score REAL NOT NULL,
                letter_grade TEXT,
                actionability_score INTEGER NOT NULL,
                clarity_of_scope_score INTEGER NOT NULL,
                evidence_and_attribution_score INTEGER NOT NULL,
                methodology_score INTEGER NOT NULL,
                primary_model_used TEXT NOT NULL,
                final_model_used TEXT NOT NULL,
                level_1_json TEXT,
                result_json TEXT NOT NULL,
                integrity_json TEXT
            )
        """)
        # Lightweight migration for databases created before integrity_json existed.
        cols = {row[1] for row in cursor.execute("PRAGMA table_info(submissions)")}
        if "integrity_json" not in cols:
            cursor.execute("ALTER TABLE submissions ADD COLUMN integrity_json TEXT")
        conn.commit()


# ==========================================
# UNIFIED STORAGE INTERFACE
# ==========================================
def get_next_attempt_number(student_email: str) -> int:
    """Returns the next attempt number for a given student email."""
    client = get_firestore_client()
    clean_email_lower = student_email.strip().lower()
    
    if client:
        try:
            docs = client.collection(COLLECTION_NAME).where("student_email_lower", "==", clean_email_lower).stream()
            count = sum(1 for _ in docs)
            return count + 1
        except Exception:
            pass
            
    _init_sqlite_db()
    with sqlite3.connect(SQLITE_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM submissions WHERE student_email_lower = ?",
            (clean_email_lower,)
        )
        count = cursor.fetchone()[0]
        return count + 1


def save_submission(record: SubmissionRecord) -> None:
    """Saves a student submission record (report text + model evals) to Firestore (with SQLite fallback)."""
    doc_data = {
        "submission_id": record.submission_id,
        "timestamp": record.timestamp,
        "student_name": record.student_name,
        "student_email": record.student_email,
        "student_email_lower": record.student_email.strip().lower(),
        "attempt_number": record.attempt_number,
        "report_title": record.report_title,
        "report_type": record.report_type,
        "filename": record.filename,
        "file_type": record.file_type,
        "report_content": record.report_content,
        "total_score": record.total_score,
        "percentage_score": record.percentage_score,
        "actionability_score": record.actionability_score,
        "clarity_of_scope_score": record.clarity_of_scope_score,
        "evidence_and_attribution_score": record.evidence_and_attribution_score,
        "methodology_score": record.methodology_score,
        "primary_model_used": record.primary_model_used,
        "final_model_used": record.final_model_used,
        "level_1_json": json.dumps(record.level_1_result.model_dump()) if record.level_1_result else None,
        "result_json": json.dumps(record.result.model_dump()),
        "integrity_json": json.dumps(record.integrity.model_dump()) if record.integrity else None,
    }

    client = get_firestore_client()
    if client:
        try:
            client.collection(COLLECTION_NAME).document(record.submission_id).set(doc_data)
            return
        except Exception:
            pass

    # SQLite fallback
    _init_sqlite_db()
    with sqlite3.connect(SQLITE_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO submissions (
                submission_id, timestamp, student_name, student_email, student_email_lower,
                attempt_number, report_title, report_type, filename, file_type, report_content,
                total_score, percentage_score, letter_grade,
                actionability_score, clarity_of_scope_score,
                evidence_and_attribution_score, methodology_score,
                primary_model_used, final_model_used, level_1_json, result_json, integrity_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.submission_id,
            record.timestamp,
            record.student_name,
            record.student_email,
            doc_data["student_email_lower"],
            record.attempt_number,
            record.report_title,
            record.report_type,
            record.filename,
            record.file_type,
            record.report_content,
            record.total_score,
            record.percentage_score,
            record.actionability_score,
            record.clarity_of_scope_score,
            record.evidence_and_attribution_score,
            record.methodology_score,
            record.primary_model_used,
            record.final_model_used,
            doc_data["level_1_json"],
            doc_data["result_json"],
            doc_data["integrity_json"],
        ))
        conn.commit()


def _row_to_record(d: dict) -> SubmissionRecord:
    result_dict = json.loads(d["result_json"])
    level_1_res = None
    if d.get("level_1_json"):
        try:
            level_1_res = Level1Assessment(**json.loads(d["level_1_json"]))
        except Exception:
            pass

    integrity = None
    if d.get("integrity_json"):
        try:
            integrity = IntegrityReview(**json.loads(d["integrity_json"]))
        except Exception:
            pass

    return SubmissionRecord(
        submission_id=d["submission_id"],
        timestamp=d["timestamp"],
        student_name=d["student_name"],
        student_email=d.get("student_email", ""),
        attempt_number=d.get("attempt_number", 1),
        report_title=d["report_title"],
        report_type=d.get("report_type", "General CTI Briefing"),
        filename=d.get("filename"),
        file_type=d["file_type"],
        report_content=d.get("report_content", ""),
        total_score=d["total_score"],
        percentage_score=d["percentage_score"],
        actionability_score=d["actionability_score"],
        clarity_of_scope_score=d["clarity_of_scope_score"],
        evidence_and_attribution_score=d["evidence_and_attribution_score"],
        methodology_score=d["methodology_score"],
        primary_model_used=d.get("primary_model_used", "gemini-3.5-flash-lite"),
        final_model_used=d.get("final_model_used", "gemini-3.7-flash"),
        level_1_result=level_1_res,
        result=GradingResult(**result_dict),
        integrity=integrity,
    )


def get_all_submissions() -> List[SubmissionRecord]:
    """Retrieves all submissions ordered by timestamp descending."""
    client = get_firestore_client()
    records = []
    
    if client:
        try:
            from google.cloud import firestore
            docs = client.collection(COLLECTION_NAME).order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
            for doc in docs:
                records.append(_row_to_record(doc.to_dict()))
            return records
        except Exception:
            pass

    # SQLite fallback
    _init_sqlite_db()
    with sqlite3.connect(SQLITE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM submissions ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        for row in rows:
            records.append(_row_to_record(dict(row)))
    return records


def get_student_submissions(student_email: str) -> List[SubmissionRecord]:
    """Retrieves all past submissions for a specific student email."""
    client = get_firestore_client()
    clean_email_lower = student_email.strip().lower()
    records = []
    
    if client:
        try:
            docs = client.collection(COLLECTION_NAME).where("student_email_lower", "==", clean_email_lower).stream()
            for doc in docs:
                records.append(_row_to_record(doc.to_dict()))
            records.sort(key=lambda r: r.attempt_number)
            return records
        except Exception:
            pass

    # SQLite fallback
    _init_sqlite_db()
    with sqlite3.connect(SQLITE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM submissions WHERE student_email_lower = ? ORDER BY attempt_number ASC",
            (clean_email_lower,)
        )
        rows = cursor.fetchall()
        for row in rows:
            records.append(_row_to_record(dict(row)))
    return records


def get_submissions_dataframe() -> pd.DataFrame:
    """Returns a pandas DataFrame summarizing all student submissions and attempts."""
    records = get_all_submissions()
    if not records:
        return pd.DataFrame()
    
    rows = []
    for r in records:
        l1_total = r.level_1_result.total_score if r.level_1_result else None
        rows.append({
            "Student Name": r.student_name,
            "Email": r.student_email,
            "Attempt #": r.attempt_number,
            "Total Score (100)": r.total_score,
            "Tier 1 Total": l1_total,
            "Δ (T2-T1)": (r.total_score - l1_total) if l1_total is not None else None,
            "Integrity": (r.integrity.severity if r.integrity and r.integrity.manipulation_detected else "ok"),
            "Report Subject": r.report_type,
            "Framing (25)": r.clarity_of_scope_score,
            "Sourcing (25)": r.evidence_and_attribution_score,
            "Reasoning (25)": r.methodology_score,
            "Exec/Action (25)": r.actionability_score,
            "Report Title": r.report_title,
            "Filename": r.filename or "Direct Paste",
            "Submitted At": r.timestamp,
            "Submission ID": r.submission_id
        })
    return pd.DataFrame(rows)
