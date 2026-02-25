"""
ATS (Applicant Tracking System) Database Module
Uses SQLite for persistent storage of employers, jobs, pipeline, and history.
"""

import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "ats.db")

PIPELINE_STAGES = [
    "Identified",
    "Contacted",
    "Responded",
    "Phone Screen",
    "Submitted to Client",
    "Interview 1",
    "Interview 2",
    "Final Interview",
    "Reference Check",
    "Offer Extended",
    "Offer Accepted",
    "Placed",
    "Rejected",
    "Withdrawn",
    "On Hold",
]

STAGE_COLORS = {
    "Identified": "blue",
    "Contacted": "blue",
    "Responded": "blue",
    "Phone Screen": "green",
    "Submitted to Client": "green",
    "Interview 1": "green",
    "Interview 2": "green",
    "Final Interview": "green",
    "Reference Check": "gold",
    "Offer Extended": "gold",
    "Offer Accepted": "gold",
    "Placed": "gold",
    "Rejected": "red",
    "Withdrawn": "red",
    "On Hold": "yellow",
}


def get_db():
    """Get a database connection with row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate_db(conn):
    """Run any needed migrations on existing databases."""
    # Check if placement_fee column exists in pipeline table
    cursor = conn.execute("PRAGMA table_info(pipeline)")
    columns = [row[1] for row in cursor.fetchall()]
    if "placement_fee" not in columns:
        conn.execute("ALTER TABLE pipeline ADD COLUMN placement_fee REAL DEFAULT 0")
        conn.commit()


def init_db():
    """Initialize the database schema if tables don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS employers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            website TEXT,
            city TEXT,
            state TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employer_id INTEGER REFERENCES employers(id),
            title TEXT NOT NULL,
            description TEXT,
            location TEXT,
            practice_area TEXT,
            specialty TEXT,
            graduation_year_min INTEGER,
            graduation_year_max INTEGER,
            salary_min INTEGER,
            salary_max INTEGER,
            bar_required TEXT,
            status TEXT DEFAULT 'Active' CHECK(status IN ('Active','On Hold','Filled','Closed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pipeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL REFERENCES jobs(id),
            attorney_id TEXT NOT NULL,
            attorney_name TEXT,
            attorney_firm TEXT,
            attorney_email TEXT,
            stage TEXT NOT NULL DEFAULT 'Identified',
            notes TEXT,
            placement_fee REAL DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            added_by TEXT DEFAULT 'Admin',
            UNIQUE(job_id, attorney_id)
        );

        CREATE TABLE IF NOT EXISTS pipeline_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id INTEGER NOT NULL REFERENCES pipeline(id),
            from_stage TEXT,
            to_stage TEXT,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            changed_by TEXT DEFAULT 'Admin',
            note TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_pipeline_job ON pipeline(job_id);
        CREATE INDEX IF NOT EXISTS idx_pipeline_attorney ON pipeline(attorney_id);
        CREATE INDEX IF NOT EXISTS idx_pipeline_stage ON pipeline(stage);
        CREATE INDEX IF NOT EXISTS idx_history_pipeline ON pipeline_history(pipeline_id);
        CREATE INDEX IF NOT EXISTS idx_history_changed ON pipeline_history(changed_at);

        CREATE TABLE IF NOT EXISTS firm_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_id TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'Admin'
        );

        CREATE TABLE IF NOT EXISTS firm_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_id TEXT NOT NULL,
            name TEXT NOT NULL,
            title TEXT,
            email TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_firm_notes_firm ON firm_notes(firm_id);
        CREATE INDEX IF NOT EXISTS idx_firm_contacts_firm ON firm_contacts(firm_id);
    """)
    conn.commit()
    _migrate_db(conn)
    conn.close()


def init_users():
    """Initialize users table and seed default admin account."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)
    conn.commit()
    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?", ("admin@firmprospects.com",)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO users (email, password_hash, first_name, last_name) VALUES (?, ?, ?, ?)",
            ("admin@firmprospects.com", generate_password_hash("jaide2026"), "Admin", "User"),
        )
        conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Employer CRUD
# ---------------------------------------------------------------------------

def create_employer(name, website="", city="", state="", notes=""):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO employers (name, website, city, state, notes) VALUES (?, ?, ?, ?, ?)",
        (name, website, city, state, notes),
    )
    employer_id = cur.lastrowid
    conn.commit()
    conn.close()
    return employer_id


def get_employer(employer_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM employers WHERE id = ?", (employer_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_employers(search=""):
    conn = get_db()
    if search:
        rows = conn.execute(
            "SELECT * FROM employers WHERE name LIKE ? ORDER BY name",
            (f"%{search}%",),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM employers ORDER BY name").fetchall()
    result = []
    for r in rows:
        emp = dict(r)
        emp["active_jobs"] = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE employer_id = ? AND status = 'Active'",
            (r["id"],),
        ).fetchone()[0]
        emp["total_candidates"] = conn.execute(
            "SELECT COUNT(DISTINCT p.id) FROM pipeline p JOIN jobs j ON p.job_id = j.id WHERE j.employer_id = ?",
            (r["id"],),
        ).fetchone()[0]
        result.append(emp)
    conn.close()
    return result


def update_employer(employer_id, **kwargs):
    conn = get_db()
    allowed = {"name", "website", "city", "state", "notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [employer_id]
    conn.execute(f"UPDATE employers SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


def delete_employer(employer_id):
    conn = get_db()
    conn.execute("DELETE FROM employers WHERE id = ?", (employer_id,))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

def create_job(employer_id, title, description="", location="", practice_area="",
               specialty="", graduation_year_min=None, graduation_year_max=None,
               salary_min=None, salary_max=None, bar_required="", status="Active"):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO jobs (employer_id, title, description, location, practice_area,
           specialty, graduation_year_min, graduation_year_max, salary_min, salary_max,
           bar_required, status, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (employer_id, title, description, location, practice_area, specialty,
         graduation_year_min, graduation_year_max, salary_min, salary_max,
         bar_required, status, datetime.now().isoformat()),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


def get_job(job_id):
    conn = get_db()
    row = conn.execute(
        """SELECT j.*, e.name as employer_name
           FROM jobs j LEFT JOIN employers e ON j.employer_id = e.id
           WHERE j.id = ?""",
        (job_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    job = dict(row)
    job["candidate_count"] = conn.execute(
        "SELECT COUNT(*) FROM pipeline WHERE job_id = ?", (job_id,)
    ).fetchone()[0]
    conn.close()
    return job


def list_jobs(status=None, employer_id=None, practice_area=None, search=""):
    conn = get_db()
    query = """SELECT j.*, e.name as employer_name,
               (SELECT COUNT(*) FROM pipeline WHERE job_id = j.id) as candidate_count
               FROM jobs j LEFT JOIN employers e ON j.employer_id = e.id WHERE 1=1"""
    params = []
    if status:
        query += " AND j.status = ?"
        params.append(status)
    if employer_id:
        query += " AND j.employer_id = ?"
        params.append(employer_id)
    if practice_area:
        query += " AND j.practice_area LIKE ?"
        params.append(f"%{practice_area}%")
    if search:
        query += " AND (j.title LIKE ? OR e.name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY j.created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_job(job_id, **kwargs):
    conn = get_db()
    allowed = {"employer_id", "title", "description", "location", "practice_area",
               "specialty", "graduation_year_min", "graduation_year_max",
               "salary_min", "salary_max", "bar_required", "status"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        conn.close()
        return False
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


def delete_job(job_id):
    conn = get_db()
    conn.execute("DELETE FROM pipeline_history WHERE pipeline_id IN (SELECT id FROM pipeline WHERE job_id = ?)", (job_id,))
    conn.execute("DELETE FROM pipeline WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Pipeline CRUD
# ---------------------------------------------------------------------------

def add_to_pipeline(job_id, attorney_id, attorney_name="", attorney_firm="",
                    attorney_email="", stage="Identified", notes="", added_by="Admin",
                    placement_fee=0):
    conn = get_db()
    # Check if already in pipeline
    existing = conn.execute(
        "SELECT id, stage FROM pipeline WHERE job_id = ? AND attorney_id = ?",
        (job_id, attorney_id),
    ).fetchone()
    if existing:
        conn.close()
        return {"status": "exists", "id": existing["id"], "stage": existing["stage"]}

    cur = conn.execute(
        """INSERT INTO pipeline (job_id, attorney_id, attorney_name, attorney_firm,
           attorney_email, stage, notes, placement_fee, added_by, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, attorney_id, attorney_name, attorney_firm, attorney_email,
         stage, notes, placement_fee, added_by, datetime.now().isoformat()),
    )
    pipeline_id = cur.lastrowid
    # Log initial add in history
    conn.execute(
        "INSERT INTO pipeline_history (pipeline_id, from_stage, to_stage, changed_by, note) VALUES (?, ?, ?, ?, ?)",
        (pipeline_id, None, stage, added_by, "Added to pipeline"),
    )
    conn.commit()
    conn.close()
    return {"status": "added", "id": pipeline_id}


def move_pipeline_stage(pipeline_id, new_stage, note="", changed_by="Admin"):
    conn = get_db()
    row = conn.execute("SELECT stage FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
    if not row:
        conn.close()
        return False
    old_stage = row["stage"]
    if old_stage == new_stage:
        conn.close()
        return True
    conn.execute(
        "UPDATE pipeline SET stage = ?, updated_at = ? WHERE id = ?",
        (new_stage, datetime.now().isoformat(), pipeline_id),
    )
    conn.execute(
        "INSERT INTO pipeline_history (pipeline_id, from_stage, to_stage, changed_by, note) VALUES (?, ?, ?, ?, ?)",
        (pipeline_id, old_stage, new_stage, changed_by, note),
    )
    conn.commit()
    conn.close()
    return True


def update_pipeline_fee(pipeline_id, placement_fee):
    conn = get_db()
    conn.execute(
        "UPDATE pipeline SET placement_fee = ?, updated_at = ? WHERE id = ?",
        (placement_fee, datetime.now().isoformat(), pipeline_id),
    )
    conn.commit()
    conn.close()
    return True


def update_pipeline_notes(pipeline_id, notes):
    conn = get_db()
    conn.execute(
        "UPDATE pipeline SET notes = ?, updated_at = ? WHERE id = ?",
        (notes, datetime.now().isoformat(), pipeline_id),
    )
    conn.commit()
    conn.close()
    return True


def remove_from_pipeline(pipeline_id):
    conn = get_db()
    conn.execute("DELETE FROM pipeline_history WHERE pipeline_id = ?", (pipeline_id,))
    conn.execute("DELETE FROM pipeline WHERE id = ?", (pipeline_id,))
    conn.commit()
    conn.close()
    return True


def get_pipeline_for_job(job_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM pipeline WHERE job_id = ? ORDER BY stage, added_at",
        (job_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pipeline_all(job_id=None, employer_id=None, stage=None, search=""):
    conn = get_db()
    query = """SELECT p.*, j.title as job_title, e.name as employer_name
               FROM pipeline p
               JOIN jobs j ON p.job_id = j.id
               LEFT JOIN employers e ON j.employer_id = e.id
               WHERE 1=1"""
    params = []
    if job_id:
        query += " AND p.job_id = ?"
        params.append(job_id)
    if employer_id:
        query += " AND j.employer_id = ?"
        params.append(employer_id)
    if stage:
        query += " AND p.stage = ?"
        params.append(stage)
    if search:
        query += " AND (p.attorney_name LIKE ? OR p.attorney_firm LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY p.updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pipeline_entry(pipeline_id):
    conn = get_db()
    row = conn.execute(
        """SELECT p.*, j.title as job_title, e.name as employer_name
           FROM pipeline p
           JOIN jobs j ON p.job_id = j.id
           LEFT JOIN employers e ON j.employer_id = e.id
           WHERE p.id = ?""",
        (pipeline_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_attorney_pipelines(attorney_id):
    """Get all pipeline entries for an attorney across all jobs."""
    conn = get_db()
    rows = conn.execute(
        """SELECT p.*, j.title as job_title, e.name as employer_name
           FROM pipeline p
           JOIN jobs j ON p.job_id = j.id
           LEFT JOIN employers e ON j.employer_id = e.id
           WHERE p.attorney_id = ?""",
        (attorney_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pipeline_status_for_attorneys(attorney_ids):
    """Bulk check: for a list of attorney IDs, return which are in any pipeline."""
    if not attorney_ids:
        return {}
    conn = get_db()
    placeholders = ",".join("?" for _ in attorney_ids)
    rows = conn.execute(
        f"""SELECT p.attorney_id, p.stage, j.title as job_title, e.name as employer_name
            FROM pipeline p
            JOIN jobs j ON p.job_id = j.id
            LEFT JOIN employers e ON j.employer_id = e.id
            WHERE p.attorney_id IN ({placeholders})""",
        attorney_ids,
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        aid = r["attorney_id"]
        if aid not in result:
            result[aid] = []
        result[aid].append({
            "stage": r["stage"],
            "job_title": r["job_title"],
            "employer_name": r["employer_name"],
        })
    return result


# ---------------------------------------------------------------------------
# Activity Log
# ---------------------------------------------------------------------------

def get_activity_log(limit=50, offset=0):
    conn = get_db()
    rows = conn.execute(
        """SELECT h.*, p.attorney_name, p.attorney_firm, p.job_id,
                  j.title as job_title, e.name as employer_name
           FROM pipeline_history h
           JOIN pipeline p ON h.pipeline_id = p.id
           JOIN jobs j ON p.job_id = j.id
           LEFT JOIN employers e ON j.employer_id = e.id
           ORDER BY h.changed_at DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM pipeline_history").fetchone()[0]
    conn.close()
    return [dict(r) for r in rows], total


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_pipeline_stats():
    conn = get_db()
    stage_counts = {}
    rows = conn.execute("SELECT stage, COUNT(*) as cnt FROM pipeline GROUP BY stage").fetchall()
    for r in rows:
        stage_counts[r["stage"]] = r["cnt"]
    total = conn.execute("SELECT COUNT(*) FROM pipeline").fetchone()[0]
    active_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'Active'").fetchone()[0]
    conn.close()
    return {
        "total_candidates": total,
        "active_jobs": active_jobs,
        "stage_counts": stage_counts,
    }


# ---------------------------------------------------------------------------
# Firm CRM: Notes
# ---------------------------------------------------------------------------

def get_firm_notes(firm_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM firm_notes WHERE firm_id = ? ORDER BY created_at DESC",
        (firm_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_firm_note(firm_id, note, created_by="Admin"):
    conn = get_db()
    conn.execute(
        "INSERT INTO firm_notes (firm_id, note, created_by) VALUES (?, ?, ?)",
        (firm_id, note, created_by),
    )
    conn.commit()
    conn.close()
    return True


def delete_firm_note(note_id):
    conn = get_db()
    conn.execute("DELETE FROM firm_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Firm CRM: Contacts
# ---------------------------------------------------------------------------

def get_firm_contacts(firm_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM firm_contacts WHERE firm_id = ? ORDER BY name",
        (firm_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_firm_contact(firm_id, name, title="", email="", phone=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO firm_contacts (firm_id, name, title, email, phone) VALUES (?, ?, ?, ?, ?)",
        (firm_id, name, title, email, phone),
    )
    conn.commit()
    conn.close()
    return True


def delete_firm_contact(contact_id):
    conn = get_db()
    conn.execute("DELETE FROM firm_contacts WHERE id = ?", (contact_id,))
    conn.commit()
    conn.close()
    return True
