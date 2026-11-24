"""SQLite memory for the master CV and one saved CV per job."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cvtailor.parse import parse_cv, text_from_upload
from cvtailor.render import to_html, to_markdown, to_pdf
from cvtailor.tailor import coverage, infer_title, tailor


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS master (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    filename TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    parsed_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    filename TEXT,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS versions (
                    id INTEGER PRIMARY KEY,
                    job_id INTEGER NOT NULL,
                    cv_json TEXT NOT NULL,
                    cv_md TEXT NOT NULL,
                    cv_html TEXT NOT NULL,
                    cv_pdf BLOB NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def save_master(self, filename: str, data: bytes) -> dict:
        raw = text_from_upload(filename, data).strip()
        if not raw:
            raise ValueError("That file had no readable text.")
        parsed = parse_cv(raw)
        stamp = now()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO master (id, filename, raw_text, parsed_json, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    filename = excluded.filename,
                    raw_text = excluded.raw_text,
                    parsed_json = excluded.parsed_json,
                    updated_at = excluded.updated_at
                """,
                (filename, raw, json.dumps(parsed), stamp),
            )
        return self.get_master()

    def get_master(self) -> dict | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM master WHERE id = 1").fetchone()
        if row is None:
            return None
        parsed = json.loads(row["parsed_json"])
        return {
            "filename": row["filename"],
            "raw_text": row["raw_text"],
            "parsed": parsed,
            "updated_at": row["updated_at"],
        }

    def add_job(self, filename: str, description: str, title: str = "") -> int:
        master = self.get_master()
        if master is None:
            raise ValueError("Upload a CV first. The app keeps that CV and reuses it for every job.")
        description = description.strip()
        if not description:
            raise ValueError("The job description was empty.")
        chosen = infer_title(filename, description, title)
        tailored, notes = tailor(master["parsed"], chosen, description)
        stamp = now()
        pdf = to_pdf(tailored)
        with self._connect() as con:
            cursor = con.execute(
                "INSERT INTO jobs (title, filename, description, created_at) VALUES (?, ?, ?, ?)",
                (chosen, filename, description, stamp),
            )
            job_id = int(cursor.lastrowid)
            con.execute(
                """
                INSERT INTO versions (job_id, cv_json, cv_md, cv_html, cv_pdf, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, json.dumps(tailored), to_markdown(tailored), to_html(tailored), pdf, json.dumps(notes), stamp),
            )
        return job_id

    def regenerate(self, job_id: int) -> None:
        master = self.get_master()
        if master is None:
            raise ValueError("Upload a CV first.")
        job = self.get_job(job_id)
        if job is None:
            raise ValueError("That job is not saved.")
        tailored, notes = tailor(master["parsed"], job["title"], job["description"])
        stamp = now()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO versions (job_id, cv_json, cv_md, cv_html, cv_pdf, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, json.dumps(tailored), to_markdown(tailored), to_html(tailored), to_pdf(tailored), json.dumps(notes), stamp),
            )

    def list_jobs(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT j.id, j.title, j.description, j.created_at, v.id AS version_id, v.created_at AS version_at
                FROM jobs j
                JOIN versions v ON v.id = (
                    SELECT id FROM versions WHERE job_id = j.id ORDER BY id DESC LIMIT 1
                )
                ORDER BY j.id DESC
                """
            ).fetchall()
        master = self.get_master()
        jobs = []
        for row in rows:
            job = dict(row)
            description = job.pop("description")
            job["match"] = coverage(master["parsed"], description)["percent"] if master else None
            jobs.append(job)
        return jobs

    def get_job(self, job_id: int) -> dict | None:
        with self._connect() as con:
            job = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                return None
            version = con.execute(
                "SELECT * FROM versions WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        master = self.get_master()
        stale = bool(master and version and master["updated_at"] > version["created_at"])
        return {
            "id": job["id"],
            "title": job["title"],
            "filename": job["filename"],
            "description": job["description"],
            "created_at": job["created_at"],
            "version_id": version["id"],
            "cv": json.loads(version["cv_json"]),
            "html": version["cv_html"],
            "notes": json.loads(version["notes"]),
            "version_at": version["created_at"],
            "stale": stale,
            "match": coverage(master["parsed"], job["description"]) if master else None,
        }

    def get_version_file(self, version_id: int, kind: str) -> tuple[str, bytes]:
        with self._connect() as con:
            row = con.execute(
                "SELECT v.cv_md, v.cv_html, v.cv_pdf, j.title FROM versions v JOIN jobs j ON j.id = v.job_id WHERE v.id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise ValueError("That CV version is not saved.")
        stem = _safe_name(row["title"])
        if kind == "md":
            return f"{stem}.md", row["cv_md"].encode("utf-8")
        if kind == "html":
            return f"{stem}.html", row["cv_html"].encode("utf-8")
        if kind == "pdf":
            return f"{stem}.pdf", row["cv_pdf"]
        raise ValueError("Unknown download type.")

    def delete_job(self, job_id: int) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM versions WHERE job_id = ?", (job_id,))
            con.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


def _safe_name(title: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_ " else "" for char in title).strip()
    return (cleaned or "cv").replace(" ", "-")[:80]
