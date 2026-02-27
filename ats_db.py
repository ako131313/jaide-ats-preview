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
    # Add new email_log columns (batch tracking + body storage)
    tbl = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='email_log'").fetchone()
    if tbl:
        el_cols = [row[1] for row in conn.execute("PRAGMA table_info(email_log)").fetchall()]
        for col, defn in [
            ("batch_id",   "TEXT"),
            ("sent_by",    "TEXT DEFAULT 'Admin'"),
            ("email_type", "TEXT DEFAULT 'individual'"),
            ("body",       "TEXT DEFAULT ''"),
        ]:
            if col not in el_cols:
                conn.execute(f"ALTER TABLE email_log ADD COLUMN {col} {defn}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_log_batch ON email_log(batch_id)")
        conn.commit()

    # Check if placement_fee column exists in pipeline table
    cursor = conn.execute("PRAGMA table_info(pipeline)")
    columns = [row[1] for row in cursor.fetchall()]
    if "placement_fee" not in columns:
        conn.execute("ALTER TABLE pipeline ADD COLUMN placement_fee REAL DEFAULT 0")
        conn.commit()

    # Migrate pipeline table to support attorney_source / job_source
    if "attorney_source" not in columns:
        # Disable FK checks for the table recreation (pipeline_history refs pipeline)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                attorney_id TEXT NOT NULL,
                attorney_source TEXT NOT NULL DEFAULT 'fp',
                job_source TEXT NOT NULL DEFAULT 'ats',
                attorney_name TEXT,
                attorney_firm TEXT,
                attorney_email TEXT,
                stage TEXT NOT NULL DEFAULT 'Identified',
                notes TEXT,
                placement_fee REAL DEFAULT 0,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                added_by TEXT DEFAULT 'Admin',
                UNIQUE(job_id, job_source, attorney_id, attorney_source)
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO pipeline_new
                (id, job_id, attorney_id, attorney_source, job_source,
                 attorney_name, attorney_firm, attorney_email,
                 stage, notes, placement_fee, added_at, updated_at, added_by)
            SELECT id, job_id, attorney_id, 'fp', 'ats',
                   attorney_name, attorney_firm, attorney_email,
                   stage, notes, placement_fee, added_at, updated_at, added_by
            FROM pipeline
        """)
        conn.execute("DROP TABLE pipeline")
        conn.execute("ALTER TABLE pipeline_new RENAME TO pipeline")
        conn.execute("PRAGMA foreign_keys=ON")
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

        CREATE TABLE IF NOT EXISTS custom_attorneys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            current_firm TEXT,
            title TEXT,
            graduation_year INTEGER,
            law_school TEXT,
            undergraduate TEXT,
            llm_school TEXT,
            llm_specialty TEXT,
            bar_admissions TEXT,
            practice_areas TEXT,
            specialty TEXT,
            bio TEXT,
            summary TEXT,
            prior_experience TEXT,
            clerkships TEXT,
            languages TEXT,
            source_notes TEXT,
            tags TEXT,
            resume_path TEXT,
            gender TEXT,
            diverse TEXT,
            location_city TEXT,
            location_state TEXT,
            linkedin_url TEXT,
            photo_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS custom_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_name TEXT NOT NULL,
            firm_source TEXT DEFAULT 'custom',
            firm_source_id TEXT,
            job_title TEXT NOT NULL,
            job_description TEXT,
            location TEXT,
            practice_areas TEXT,
            specialty TEXT,
            min_years INTEGER,
            max_years INTEGER,
            salary_min INTEGER,
            salary_max INTEGER,
            bar_required TEXT,
            status TEXT DEFAULT 'Open' CHECK(status IN ('Open','On Hold','Closed')),
            confidential INTEGER DEFAULT 0,
            contact_name TEXT,
            contact_email TEXT,
            contact_phone TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS custom_firms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            website TEXT,
            total_attorneys INTEGER,
            partners INTEGER,
            counsel INTEGER,
            associates INTEGER,
            office_locations TEXT,
            practice_areas TEXT,
            ppp INTEGER,
            vault_ranking INTEGER,
            firm_type TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS record_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            record_source TEXT NOT NULL,
            record_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(record_type, record_source, record_id, tag)
        );

        CREATE TABLE IF NOT EXISTS record_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            record_source TEXT NOT NULL,
            record_id TEXT NOT NULL,
            note_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_custom_attorneys_name ON custom_attorneys(last_name, first_name);
        CREATE INDEX IF NOT EXISTS idx_custom_jobs_firm ON custom_jobs(firm_name);
        CREATE INDEX IF NOT EXISTS idx_custom_firms_name ON custom_firms(name);
        CREATE INDEX IF NOT EXISTS idx_record_tags_record ON record_tags(record_type, record_source, record_id);
        CREATE INDEX IF NOT EXISTS idx_record_notes_record ON record_notes(record_type, record_source, record_id);

        CREATE TABLE IF NOT EXISTS worklists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            color TEXT DEFAULT '#0059FF',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            created_by TEXT DEFAULT 'Admin'
        );

        CREATE TABLE IF NOT EXISTS worklist_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worklist_id INTEGER NOT NULL REFERENCES worklists(id) ON DELETE CASCADE,
            attorney_id TEXT NOT NULL,
            attorney_source TEXT NOT NULL DEFAULT 'fp',
            attorney_name TEXT,
            attorney_firm TEXT,
            attorney_email TEXT,
            notes TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            added_by TEXT DEFAULT 'Admin',
            UNIQUE(worklist_id, attorney_id, attorney_source)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            task_type TEXT DEFAULT 'General',
            due_date TEXT,
            due_time TEXT,
            priority TEXT DEFAULT 'Medium' CHECK(priority IN ('High','Medium','Low')),
            status TEXT DEFAULT 'Open' CHECK(status IN ('Open','In Progress','Completed','Cancelled')),
            attorney_id TEXT,
            attorney_source TEXT DEFAULT 'fp',
            attorney_name TEXT,
            job_id INTEGER,
            job_title TEXT,
            firm_name TEXT,
            firm_fp_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_by TEXT DEFAULT 'Admin'
        );

        CREATE INDEX IF NOT EXISTS idx_worklists_name ON worklists(name);
        CREATE INDEX IF NOT EXISTS idx_worklist_members_worklist ON worklist_members(worklist_id);
        CREATE INDEX IF NOT EXISTS idx_worklist_members_attorney ON worklist_members(attorney_id, attorney_source);
        CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_attorney ON tasks(attorney_id, attorney_source);
        CREATE INDEX IF NOT EXISTS idx_tasks_job ON tasks(job_id);

        CREATE TABLE IF NOT EXISTS firm_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_name TEXT NOT NULL,
            firm_fp_id TEXT DEFAULT '',
            client_status TEXT DEFAULT 'Reference Only',
            owner TEXT DEFAULT '',
            priority TEXT DEFAULT 'Normal',
            last_contact_date TEXT,
            next_follow_up TEXT,
            notes TEXT DEFAULT '',
            pinned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(firm_name)
        );

        CREATE TABLE IF NOT EXISTS firm_recently_viewed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_name TEXT NOT NULL,
            firm_fp_id TEXT DEFAULT '',
            viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_firm_status_name ON firm_status(firm_name);
        CREATE INDEX IF NOT EXISTS idx_firm_status_client ON firm_status(client_status);
        CREATE INDEX IF NOT EXISTS idx_firm_recently_viewed ON firm_recently_viewed(viewed_at);

        CREATE TABLE IF NOT EXISTS email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            recipient_email TEXT NOT NULL,
            candidate_name TEXT DEFAULT '',
            attorney_id TEXT DEFAULT '',
            attorney_source TEXT DEFAULT 'fp',
            subject TEXT DEFAULT '',
            job_id INTEGER,
            job_title TEXT DEFAULT '',
            status TEXT DEFAULT 'sent',
            error TEXT DEFAULT '',
            opened_at TIMESTAMP,
            opened_count INTEGER DEFAULT 0,
            clicked_at TIMESTAMP,
            clicked_count INTEGER DEFAULT 0,
            replied_at TIMESTAMP,
            bounced_at TIMESTAMP,
            unsubscribed INTEGER DEFAULT 0,
            nylas_message_id TEXT,
            nylas_thread_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_email_log_recipient ON email_log(recipient_email);
        CREATE INDEX IF NOT EXISTS idx_email_log_attorney ON email_log(attorney_id);
        CREATE INDEX IF NOT EXISTS idx_email_log_sent ON email_log(sent_at);

        CREATE TABLE IF NOT EXISTS attorney_employment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attorney_id TEXT NOT NULL,
            firm_name TEXT NOT NULL,
            firm_logo_url TEXT,
            title TEXT,
            start_date TEXT,
            end_date TEXT,
            duration_months INTEGER,
            location TEXT,
            practice_area TEXT,
            is_current INTEGER DEFAULT 0,
            source TEXT DEFAULT 'API',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_atty_employment ON attorney_employment(attorney_id);
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
                    placement_fee=0, attorney_source="fp", job_source="ats"):
    conn = get_db()
    # Check if already in pipeline
    existing = conn.execute(
        "SELECT id, stage FROM pipeline WHERE job_id = ? AND attorney_id = ? AND attorney_source = ? AND job_source = ?",
        (job_id, attorney_id, attorney_source, job_source),
    ).fetchone()
    if existing:
        conn.close()
        return {"status": "exists", "id": existing["id"], "stage": existing["stage"]}

    cur = conn.execute(
        """INSERT INTO pipeline (job_id, attorney_id, attorney_source, job_source,
           attorney_name, attorney_firm, attorney_email, stage, notes, placement_fee, added_by, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, attorney_id, attorney_source, job_source,
         attorney_name, attorney_firm, attorney_email,
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

def get_pipeline_stats(job_id=None):
    conn = get_db()
    where = " WHERE job_id = ?" if job_id else ""
    params = [job_id] if job_id else []

    stage_counts = {}
    rows = conn.execute(f"SELECT stage, COUNT(*) as cnt FROM pipeline{where} GROUP BY stage", params).fetchall()
    for r in rows:
        stage_counts[r["stage"]] = r["cnt"]
    total = conn.execute(f"SELECT COUNT(*) FROM pipeline{where}", params).fetchone()[0]
    total_value = conn.execute(f"SELECT COALESCE(SUM(placement_fee), 0) FROM pipeline{where}", params).fetchone()[0]
    unique_jobs = conn.execute(f"SELECT COUNT(DISTINCT job_id) FROM pipeline{where}", params).fetchone()[0]
    active_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'Active'").fetchone()[0]

    # placed_this_month: stage=Placed and updated_at in current month
    month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    pm_params = [month_start] + params
    pm_where = " AND job_id = ?" if job_id else ""
    placed_month = conn.execute(
        f"SELECT COUNT(*) FROM pipeline WHERE stage = 'Placed' AND updated_at >= ?{pm_where}",
        pm_params,
    ).fetchone()[0]

    conn.close()
    return {
        "total_candidates": total,
        "active_jobs": active_jobs,
        "unique_jobs": unique_jobs,
        "stage_counts": stage_counts,
        "total_pipeline_value": float(total_value),
        "placed_this_month": placed_month,
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


# ---------------------------------------------------------------------------
# Firm CRM: Status
# ---------------------------------------------------------------------------

def upsert_firm_status(firm_name, firm_fp_id=None, client_status=None, owner=None,
                       priority=None, last_contact_date=None, next_follow_up=None,
                       notes=None, pinned=None):
    """Insert or update a firm's CRM status."""
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM firm_status WHERE firm_name = ?", (firm_name,)
    ).fetchone()
    now = datetime.now().isoformat()
    if existing:
        updates = {"updated_at": now}
        if firm_fp_id is not None:
            updates["firm_fp_id"] = firm_fp_id
        if client_status is not None:
            updates["client_status"] = client_status
        if owner is not None:
            updates["owner"] = owner
        if priority is not None:
            updates["priority"] = priority
        if last_contact_date is not None:
            updates["last_contact_date"] = last_contact_date
        if next_follow_up is not None:
            updates["next_follow_up"] = next_follow_up
        if notes is not None:
            updates["notes"] = notes
        if pinned is not None:
            updates["pinned"] = 1 if pinned else 0
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [firm_name]
        conn.execute(f"UPDATE firm_status SET {set_clause} WHERE firm_name = ?", values)
    else:
        conn.execute(
            """INSERT INTO firm_status
               (firm_name, firm_fp_id, client_status, owner, priority,
                last_contact_date, next_follow_up, notes, pinned, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                firm_name,
                firm_fp_id or "",
                client_status or "Reference Only",
                owner or "",
                priority or "Normal",
                last_contact_date,
                next_follow_up,
                notes or "",
                1 if pinned else 0,
                now,
            ),
        )
    conn.commit()
    conn.close()
    return True


def get_firm_status(firm_name):
    """Get status row for a firm by name."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM firm_status WHERE LOWER(firm_name) = LOWER(?)", (firm_name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_firm_status_by_fp_id(fp_id):
    """Get status row for a firm by FP ID."""
    if not fp_id:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM firm_status WHERE firm_fp_id = ?", (str(fp_id),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_my_clients():
    """Return Active Client + Prospect firms ordered by pin then recency."""
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM firm_status
           WHERE client_status IN ('Active Client', 'Prospect')
           ORDER BY pinned DESC, last_contact_date DESC, updated_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_all_firm_statuses():
    """Return all firm statuses as a dict keyed by lower(firm_name)."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM firm_status").fetchall()
    conn.close()
    return {r["firm_name"].lower(): dict(r) for r in rows}


def track_firm_view(firm_name, firm_fp_id=""):
    """Record that a firm was viewed."""
    conn = get_db()
    conn.execute(
        "INSERT INTO firm_recently_viewed (firm_name, firm_fp_id) VALUES (?, ?)",
        (firm_name, firm_fp_id or ""),
    )
    # Prune old entries (keep last 200)
    conn.execute(
        """DELETE FROM firm_recently_viewed WHERE id NOT IN (
           SELECT id FROM firm_recently_viewed ORDER BY viewed_at DESC LIMIT 200)"""
    )
    conn.commit()
    conn.close()


def get_recently_viewed(limit=8):
    """Return the most recently viewed unique firms."""
    conn = get_db()
    rows = conn.execute(
        """SELECT firm_name, firm_fp_id, MAX(viewed_at) as last_viewed
           FROM firm_recently_viewed
           GROUP BY firm_name
           ORDER BY last_viewed DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def migrate_firm_statuses_from_activity(firm_names_with_jobs, firm_names_with_pipeline):
    """Auto-mark firms as Active Client if they have jobs or pipeline activity."""
    conn = get_db()
    active_firms = set(str(n).strip() for n in firm_names_with_jobs if n and str(n).strip())
    active_firms |= set(str(n).strip() for n in firm_names_with_pipeline if n and str(n).strip())
    now = datetime.now().isoformat()
    for firm_name in active_firms:
        existing = conn.execute(
            "SELECT id FROM firm_status WHERE LOWER(firm_name) = LOWER(?)", (firm_name,)
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT OR IGNORE INTO firm_status (firm_name, client_status, updated_at)
                   VALUES (?, 'Active Client', ?)""",
                (firm_name, now),
            )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Custom Attorney CRUD
# ---------------------------------------------------------------------------

_CUSTOM_ATTORNEY_FIELDS = {
    "first_name", "last_name", "email", "phone", "current_firm", "title",
    "graduation_year", "law_school", "undergraduate", "llm_school", "llm_specialty",
    "bar_admissions", "practice_areas", "specialty", "bio", "summary",
    "prior_experience", "clerkships", "languages", "source_notes", "tags",
    "resume_path", "gender", "diverse", "location_city", "location_state",
    "linkedin_url", "photo_url",
}


def create_custom_attorney(data: dict) -> int:
    conn = get_db()
    fields = {k: v for k, v in data.items() if k in _CUSTOM_ATTORNEY_FIELDS}
    fields["updated_at"] = datetime.now().isoformat()
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO custom_attorneys ({cols}) VALUES ({placeholders})",
        list(fields.values()),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_custom_attorney(atty_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM custom_attorneys WHERE id = ?", (atty_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["source"] = "custom"
    return d


def list_custom_attorneys(search="", practice_area="", location="",
                          grad_year_min=None, grad_year_max=None) -> list:
    conn = get_db()
    query = "SELECT * FROM custom_attorneys WHERE 1=1"
    params = []
    if search:
        query += " AND (first_name || ' ' || last_name LIKE ? OR current_firm LIKE ? OR bio LIKE ? OR practice_areas LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s, s])
    if practice_area:
        query += " AND practice_areas LIKE ?"
        params.append(f"%{practice_area}%")
    if location:
        query += " AND (location_city LIKE ? OR location_state LIKE ?)"
        params.extend([f"%{location}%", f"%{location}%"])
    if grad_year_min is not None:
        query += " AND graduation_year >= ?"
        params.append(grad_year_min)
    if grad_year_max is not None:
        query += " AND graduation_year <= ?"
        params.append(grad_year_max)
    query += " ORDER BY last_name, first_name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["source"] = "custom"
        result.append(d)
    return result


def update_custom_attorney(atty_id: int, data: dict) -> bool:
    conn = get_db()
    fields = {k: v for k, v in data.items() if k in _CUSTOM_ATTORNEY_FIELDS}
    if not fields:
        conn.close()
        return False
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [atty_id]
    conn.execute(f"UPDATE custom_attorneys SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


def delete_custom_attorney(atty_id: int) -> bool:
    conn = get_db()
    # Cascade remove from pipeline
    conn.execute(
        "DELETE FROM pipeline_history WHERE pipeline_id IN "
        "(SELECT id FROM pipeline WHERE attorney_id = ? AND attorney_source = 'custom')",
        (str(atty_id),),
    )
    conn.execute(
        "DELETE FROM pipeline WHERE attorney_id = ? AND attorney_source = 'custom'",
        (str(atty_id),),
    )
    conn.execute("DELETE FROM custom_attorneys WHERE id = ?", (atty_id,))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Custom Job CRUD
# ---------------------------------------------------------------------------

_CUSTOM_JOB_FIELDS = {
    "firm_name", "firm_source", "firm_source_id", "job_title", "job_description",
    "location", "practice_areas", "specialty", "min_years", "max_years",
    "salary_min", "salary_max", "bar_required", "status", "confidential",
    "contact_name", "contact_email", "contact_phone", "notes",
}


def create_custom_job(data: dict) -> int:
    conn = get_db()
    fields = {k: v for k, v in data.items() if k in _CUSTOM_JOB_FIELDS}
    fields["updated_at"] = datetime.now().isoformat()
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO custom_jobs ({cols}) VALUES ({placeholders})",
        list(fields.values()),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_custom_job(job_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM custom_jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["source"] = "custom"
    return d


def list_custom_jobs(search="", status=None, practice_area=None) -> list:
    conn = get_db()
    query = "SELECT * FROM custom_jobs WHERE 1=1"
    params = []
    if search:
        query += " AND (firm_name LIKE ? OR job_title LIKE ? OR job_description LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    if status:
        query += " AND status = ?"
        params.append(status)
    if practice_area:
        query += " AND practice_areas LIKE ?"
        params.append(f"%{practice_area}%")
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["source"] = "custom"
        result.append(d)
    return result


def update_custom_job(job_id: int, data: dict) -> bool:
    conn = get_db()
    fields = {k: v for k, v in data.items() if k in _CUSTOM_JOB_FIELDS}
    if not fields:
        conn.close()
        return False
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    conn.execute(f"UPDATE custom_jobs SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


def delete_custom_job(job_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM custom_jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Custom Firm CRUD
# ---------------------------------------------------------------------------

_CUSTOM_FIRM_FIELDS = {
    "name", "website", "total_attorneys", "partners", "counsel", "associates",
    "office_locations", "practice_areas", "ppp", "vault_ranking", "firm_type", "notes",
}


def create_custom_firm(data: dict) -> int:
    conn = get_db()
    fields = {k: v for k, v in data.items() if k in _CUSTOM_FIRM_FIELDS}
    fields["updated_at"] = datetime.now().isoformat()
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO custom_firms ({cols}) VALUES ({placeholders})",
        list(fields.values()),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_custom_firm(firm_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM custom_firms WHERE id = ?", (firm_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["source"] = "custom"
    return d


def list_custom_firms(search="") -> list:
    conn = get_db()
    query = "SELECT * FROM custom_firms WHERE 1=1"
    params = []
    if search:
        query += " AND (name LIKE ? OR practice_areas LIKE ? OR office_locations LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    query += " ORDER BY name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["source"] = "custom"
        result.append(d)
    return result


def update_custom_firm(firm_id: int, data: dict) -> bool:
    conn = get_db()
    fields = {k: v for k, v in data.items() if k in _CUSTOM_FIRM_FIELDS}
    if not fields:
        conn.close()
        return False
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [firm_id]
    conn.execute(f"UPDATE custom_firms SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


def delete_custom_firm(firm_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM custom_firms WHERE id = ?", (firm_id,))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Record Tags
# ---------------------------------------------------------------------------

def add_record_tag(record_type: str, record_source: str, record_id: str, tag: str) -> bool:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO record_tags (record_type, record_source, record_id, tag) VALUES (?, ?, ?, ?)",
            (record_type, record_source, str(record_id), tag.strip()),
        )
        conn.commit()
    except Exception:
        conn.close()
        return False
    conn.close()
    return True


def get_record_tags(record_type: str, record_source: str, record_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM record_tags WHERE record_type = ? AND record_source = ? AND record_id = ? ORDER BY tag",
        (record_type, record_source, str(record_id)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_record_tag(tag_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM record_tags WHERE id = ?", (tag_id,))
    conn.commit()
    conn.close()
    return True


def get_tags_for_records(record_type: str, record_source: str, record_ids: list) -> dict:
    """Batch lookup: returns {record_id: [tag_dicts]}."""
    if not record_ids:
        return {}
    conn = get_db()
    placeholders = ",".join("?" for _ in record_ids)
    str_ids = [str(r) for r in record_ids]
    rows = conn.execute(
        f"SELECT * FROM record_tags WHERE record_type = ? AND record_source = ? AND record_id IN ({placeholders})",
        [record_type, record_source] + str_ids,
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        rid = r["record_id"]
        if rid not in result:
            result[rid] = []
        result[rid].append(dict(r))
    return result


# ---------------------------------------------------------------------------
# Record Notes
# ---------------------------------------------------------------------------

def add_record_note(record_type: str, record_source: str, record_id: str, note_text: str) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO record_notes (record_type, record_source, record_id, note_text) VALUES (?, ?, ?, ?)",
        (record_type, record_source, str(record_id), note_text),
    )
    note_id = cur.lastrowid
    conn.commit()
    conn.close()
    return note_id


def get_record_notes(record_type: str, record_source: str, record_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM record_notes WHERE record_type = ? AND record_source = ? AND record_id = ? ORDER BY created_at DESC",
        (record_type, record_source, str(record_id)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_record_note(note_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM record_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Worklists
# ---------------------------------------------------------------------------

def create_worklist(name: str, description: str = "", color: str = "#0059FF", created_by: str = "Admin") -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO worklists (name, description, color, created_by) VALUES (?, ?, ?, ?)",
        (name, description, color, created_by),
    )
    worklist_id = cur.lastrowid
    conn.commit()
    conn.close()
    return worklist_id


def get_worklist(worklist_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM worklists WHERE id = ?", (worklist_id,)).fetchone()
    if not row:
        conn.close()
        return None
    wl = dict(row)
    members = conn.execute(
        "SELECT * FROM worklist_members WHERE worklist_id = ? ORDER BY added_at DESC",
        (worklist_id,),
    ).fetchall()
    wl["members"] = [dict(m) for m in members]
    wl["member_count"] = len(wl["members"])
    conn.close()
    return wl


def list_worklists(search: str = "") -> list:
    conn = get_db()
    if search:
        rows = conn.execute(
            "SELECT w.*, COUNT(wm.id) as member_count FROM worklists w "
            "LEFT JOIN worklist_members wm ON w.id = wm.worklist_id "
            "WHERE LOWER(w.name) LIKE ? GROUP BY w.id ORDER BY w.updated_at DESC, w.created_at DESC",
            (f"%{search.lower()}%",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT w.*, COUNT(wm.id) as member_count FROM worklists w "
            "LEFT JOIN worklist_members wm ON w.id = wm.worklist_id "
            "GROUP BY w.id ORDER BY w.updated_at DESC, w.created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_worklist(worklist_id: int, data: dict) -> bool:
    allowed = {"name", "description", "color"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return False
    fields["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn = get_db()
    conn.execute(
        f"UPDATE worklists SET {set_clause} WHERE id = ?",
        list(fields.values()) + [worklist_id],
    )
    conn.commit()
    conn.close()
    return True


def delete_worklist(worklist_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM worklists WHERE id = ?", (worklist_id,))
    conn.commit()
    conn.close()
    return True


def add_worklist_member(worklist_id: int, attorney_id: str, attorney_source: str = "fp",
                        attorney_name: str = "", attorney_firm: str = "",
                        attorney_email: str = "", notes: str = "",
                        added_by: str = "Admin") -> bool:
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO worklist_members
               (worklist_id, attorney_id, attorney_source, attorney_name, attorney_firm, attorney_email, notes, added_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (worklist_id, str(attorney_id), attorney_source, attorney_name, attorney_firm, attorney_email, notes, added_by),
        )
        conn.execute(
            "UPDATE worklists SET updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), worklist_id),
        )
        conn.commit()
    except Exception:
        conn.close()
        return False
    conn.close()
    return True


def remove_worklist_member(worklist_id: int, attorney_id: str, attorney_source: str = "fp") -> bool:
    conn = get_db()
    conn.execute(
        "DELETE FROM worklist_members WHERE worklist_id = ? AND attorney_id = ? AND attorney_source = ?",
        (worklist_id, str(attorney_id), attorney_source),
    )
    conn.execute(
        "UPDATE worklists SET updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), worklist_id),
    )
    conn.commit()
    conn.close()
    return True


def update_worklist_member_notes(worklist_id: int, attorney_id: str, attorney_source: str, notes: str) -> bool:
    conn = get_db()
    conn.execute(
        "UPDATE worklist_members SET notes = ? WHERE worklist_id = ? AND attorney_id = ? AND attorney_source = ?",
        (notes, worklist_id, str(attorney_id), attorney_source),
    )
    conn.commit()
    conn.close()
    return True


def get_worklists_for_attorney(attorney_id: str, attorney_source: str = "fp") -> list:
    """Return all worklists that contain a given attorney."""
    conn = get_db()
    rows = conn.execute(
        """SELECT w.id, w.name, w.color, wm.notes, wm.added_at
           FROM worklists w JOIN worklist_members wm ON w.id = wm.worklist_id
           WHERE wm.attorney_id = ? AND wm.attorney_source = ?
           ORDER BY w.name""",
        (str(attorney_id), attorney_source),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def create_task(data: dict) -> int:
    allowed = {
        "title", "description", "task_type", "due_date", "due_time",
        "priority", "status", "attorney_id", "attorney_source", "attorney_name",
        "job_id", "job_title", "firm_name", "firm_fp_id", "created_by",
    }
    fields = {k: v for k, v in data.items() if k in allowed and v is not None}
    fields.setdefault("created_by", "Admin")
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    conn = get_db()
    cur = conn.execute(f"INSERT INTO tasks ({cols}) VALUES ({placeholders})", list(fields.values()))
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def get_task(task_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_tasks(status: str = None, priority: str = None, due_date: str = None,
               attorney_id: str = None, attorney_source: str = None,
               job_id: int = None, overdue_only: bool = False) -> list:
    conditions = []
    params = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if due_date:
        conditions.append("due_date = ?")
        params.append(due_date)
    if attorney_id:
        conditions.append("attorney_id = ?")
        params.append(str(attorney_id))
    if attorney_source:
        conditions.append("attorney_source = ?")
        params.append(attorney_source)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    if overdue_only:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        conditions.append("due_date < ? AND status NOT IN ('Completed','Cancelled')")
        params.append(today)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    conn = get_db()
    rows = conn.execute(
        f"""SELECT * FROM tasks {where}
            ORDER BY
                CASE
                    WHEN due_date IS NULL THEN 2
                    WHEN due_date < date('now') THEN 0
                    WHEN due_date = date('now') THEN 1
                    ELSE 2
                END ASC,
                due_date ASC,
                CASE WHEN due_time IS NULL OR due_time = '' THEN 1 ELSE 0 END,
                due_time ASC,
                created_at DESC""",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_task(task_id: int, data: dict) -> bool:
    allowed = {
        "title", "description", "task_type", "due_date", "due_time",
        "priority", "status", "attorney_id", "attorney_source", "attorney_name",
        "job_id", "job_title", "firm_name", "firm_fp_id",
    }
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return False
    fields["updated_at"] = datetime.utcnow().isoformat()
    if data.get("status") == "Completed":
        fields["completed_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn = get_db()
    conn.execute(
        f"UPDATE tasks SET {set_clause} WHERE id = ?",
        list(fields.values()) + [task_id],
    )
    conn.commit()
    conn.close()
    return True


def complete_task(task_id: int) -> bool:
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "UPDATE tasks SET status = 'Completed', completed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, task_id),
    )
    conn.commit()
    conn.close()
    return True


def delete_task(task_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Dashboard stats + action items
# ---------------------------------------------------------------------------

def get_dashboard_stats() -> dict:
    """Return all stats needed by the dashboard command center."""
    conn = get_db()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Pipeline
    stage_counts = {}
    rows = conn.execute("SELECT stage, COUNT(*) as cnt FROM pipeline GROUP BY stage").fetchall()
    for r in rows:
        stage_counts[r["stage"]] = r["cnt"]
    total_pipeline = conn.execute("SELECT COUNT(*) FROM pipeline").fetchone()[0]
    active_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'Active'").fetchone()[0]
    total_value = conn.execute("SELECT COALESCE(SUM(placement_fee), 0) FROM pipeline").fetchone()[0]

    # Custom records
    custom_atty_count = conn.execute("SELECT COUNT(*) FROM custom_attorneys").fetchone()[0]
    custom_job_count = conn.execute("SELECT COUNT(*) FROM custom_jobs").fetchone()[0]

    # Tasks
    open_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('Completed','Cancelled')"
    ).fetchone()[0]
    overdue_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE due_date < ? AND status NOT IN ('Completed','Cancelled')",
        (today,),
    ).fetchone()[0]
    due_today_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE due_date = ? AND status NOT IN ('Completed','Cancelled')",
        (today,),
    ).fetchone()[0]

    # Worklists
    worklist_count = conn.execute("SELECT COUNT(*) FROM worklists").fetchone()[0]

    # Response rate: Responded+ / Contacted total (all time)
    contacted = conn.execute(
        "SELECT COUNT(*) FROM pipeline WHERE stage IN ('Contacted','Responded','Phone Screen',"
        "'Submitted to Client','Interview 1','Interview 2','Final Interview','Reference Check',"
        "'Offer Extended','Offer Accepted','Placed')"
    ).fetchone()[0]
    responded = conn.execute(
        "SELECT COUNT(*) FROM pipeline WHERE stage NOT IN ('Identified','Contacted','Rejected','Withdrawn','On Hold')"
    ).fetchone()[0]
    response_rate = round((responded / contacted * 100) if contacted > 0 else 0)

    # Email stats (current month)
    email_row = conn.execute("""
        SELECT COUNT(*) as sent,
               SUM(CASE WHEN opened_count > 0 THEN 1 ELSE 0 END) as opened,
               SUM(CASE WHEN replied_at IS NOT NULL THEN 1 ELSE 0 END) as replied
        FROM email_log
        WHERE strftime('%Y-%m', sent_at) = strftime('%Y-%m', 'now')
    """).fetchone()
    email_sent = email_row["sent"] or 0 if email_row else 0
    email_opened = email_row["opened"] or 0 if email_row else 0
    email_replied = email_row["replied"] or 0 if email_row else 0

    conn.close()
    return {
        "total_pipeline": total_pipeline,
        "active_jobs": active_jobs,
        "total_pipeline_value": float(total_value),
        "stage_counts": stage_counts,
        "custom_attorneys": custom_atty_count,
        "custom_jobs": custom_job_count,
        "open_tasks": open_tasks,
        "overdue_tasks": overdue_tasks,
        "due_today_tasks": due_today_tasks,
        "worklist_count": worklist_count,
        "response_rate": response_rate,
        "email_sent": email_sent,
        "email_opened": email_opened,
        "email_replied": email_replied,
    }


def get_dashboard_candidates(limit: int = 20) -> list:
    """Return recently active pipeline entries for the dashboard My Candidates table."""
    conn = get_db()
    rows = conn.execute("""
        SELECT p.id, p.attorney_id, p.attorney_source, p.attorney_name, p.attorney_firm,
               p.stage, p.placement_fee, p.added_at, p.updated_at, p.job_id,
               j.title as job_title,
               e.id as employer_id, e.name as employer_name,
               CAST(ROUND(julianday('now') - julianday(COALESCE(p.updated_at, p.added_at))) AS INTEGER) as days_in_stage
        FROM pipeline p
        JOIN jobs j ON p.job_id = j.id
        LEFT JOIN employers e ON j.employer_id = e.id
        ORDER BY p.updated_at DESC, p.added_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_dashboard_jobs() -> list:
    """Return all jobs with per-stage pipeline breakdowns for the dashboard My Active Jobs table."""
    conn = get_db()
    rows = conn.execute("""
        SELECT j.id, j.title, j.location, j.status, j.practice_area, j.created_at,
               e.id as employer_id, e.name as employer_name,
               CAST(ROUND(julianday('now') - julianday(j.created_at)) AS INTEGER) as days_open,
               COUNT(p.id) as candidate_count,
               SUM(CASE WHEN p.stage IN ('Identified','Contacted','Responded','Phone Screen',
                   'Submitted to Client') THEN 1 ELSE 0 END) as early_count,
               SUM(CASE WHEN p.stage IN ('Interview 1','Interview 2','Final Interview',
                   'Reference Check') THEN 1 ELSE 0 END) as interview_count,
               SUM(CASE WHEN p.stage IN ('Offer Extended','Placed') THEN 1 ELSE 0 END) as placed_count
        FROM jobs j
        LEFT JOIN employers e ON j.employer_id = e.id
        LEFT JOIN pipeline p ON p.job_id = j.id
        GROUP BY j.id
        ORDER BY candidate_count DESC, j.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Email Log
# ---------------------------------------------------------------------------

def log_email(recipient_email, candidate_name="", subject="", status="sent", error="",
              attorney_id="", attorney_source="fp", job_id=None, job_title="",
              batch_id="", sent_by="Admin", email_type="individual", body=""):
    """Insert an email send record into SQLite.
    # TODO: Nylas webhook will update opened_at/clicked_at/replied_at/nylas_* fields
    #       via POST /api/email/webhook once Nylas integration is configured.
    """
    conn = get_db()
    conn.execute("""
        INSERT INTO email_log
            (recipient_email, candidate_name, subject, status, error,
             attorney_id, attorney_source, job_id, job_title,
             batch_id, sent_by, email_type, body)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (recipient_email, candidate_name or "", subject or "", status or "sent",
          error or "", attorney_id or "", attorney_source or "fp", job_id, job_title or "",
          batch_id or "", sent_by or "Admin", email_type or "individual", body or ""))
    conn.commit()
    conn.close()


def get_email_log(limit=200, status_filter="", q=""):
    """Return email log entries with optional status/text filter."""
    conn = get_db()
    where = []
    params = []
    if status_filter:
        where.append("status = ?")
        params.append(status_filter)
    if q:
        where.append("(recipient_email LIKE ? OR candidate_name LIKE ? OR subject LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT * FROM email_log {where_clause} ORDER BY sent_at DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_email_history_by_attorney(attorney_id, recipient_email="", limit=20):
    """Return email history for a specific attorney (by attorney_id or email fallback)."""
    conn = get_db()
    rows = []
    if attorney_id:
        rows = conn.execute(
            "SELECT * FROM email_log WHERE attorney_id = ? ORDER BY sent_at DESC LIMIT ?",
            (str(attorney_id), limit)
        ).fetchall()
    if not rows and recipient_email:
        rows = conn.execute(
            "SELECT * FROM email_log WHERE recipient_email = ? ORDER BY sent_at DESC LIMIT ?",
            (recipient_email, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_email_stats():
    """Return email engagement stats for the current calendar month."""
    conn = get_db()
    row = conn.execute("""
        SELECT
            COUNT(*) as sent,
            SUM(CASE WHEN opened_count > 0 THEN 1 ELSE 0 END) as opened,
            SUM(CASE WHEN replied_at IS NOT NULL THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN clicked_count > 0 THEN 1 ELSE 0 END) as clicked,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
        FROM email_log
        WHERE strftime('%Y-%m', sent_at) = strftime('%Y-%m', 'now')
    """).fetchone()
    conn.close()
    if row:
        return {
            "sent": row["sent"] or 0,
            "opened": row["opened"] or 0,
            "replied": row["replied"] or 0,
            "clicked": row["clicked"] or 0,
            "failed": row["failed"] or 0,
        }
    return {"sent": 0, "opened": 0, "replied": 0, "clicked": 0, "failed": 0}


def get_email_counts_for_pipeline():
    """Return email send/open counts grouped by attorney_id (for kanban badges)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT attorney_id,
               COUNT(*) as sent_count,
               SUM(CASE WHEN opened_count > 0 THEN 1 ELSE 0 END) as open_count
        FROM email_log
        WHERE status = 'sent' AND attorney_id != ''
        GROUP BY attorney_id
    """).fetchall()
    conn.close()
    return {
        row["attorney_id"]: {"sent": row["sent_count"], "opened": row["open_count"]}
        for row in rows
    }


def get_email_hub_list(q="", status_filter="", days=None, job_id=None, page=1, per_page=25):
    """Return grouped email hub entries (one row per send batch or individual send)."""
    conn = get_db()
    where_parts = []
    where_params = []
    having_parts = []

    if q:
        where_parts.append("(subject LIKE ? OR candidate_name LIKE ? OR recipient_email LIKE ?)")
        where_params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    if status_filter in ("sent", "failed"):
        where_parts.append("status = ?")
        where_params.append(status_filter)
    elif status_filter == "opened":
        having_parts.append("SUM(CASE WHEN opened_count > 0 THEN 1 ELSE 0 END) > 0")
    elif status_filter == "replied":
        having_parts.append("SUM(CASE WHEN replied_at IS NOT NULL THEN 1 ELSE 0 END) > 0")
    elif status_filter == "clicked":
        having_parts.append("SUM(CASE WHEN clicked_count > 0 THEN 1 ELSE 0 END) > 0")

    if days:
        where_parts.append(f"sent_at >= datetime('now', '-{int(days)} days')")

    if job_id is not None:
        where_parts.append("job_id = ?")
        where_params.append(job_id)

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    having_clause = ("HAVING " + " AND ".join(having_parts)) if having_parts else ""
    offset = (page - 1) * per_page

    rows = conn.execute(f"""
        SELECT
            COALESCE(batch_id, CAST(id AS TEXT)) as group_id,
            MIN(id) as min_id,
            MIN(subject) as subject,
            COUNT(*) as recipient_count,
            GROUP_CONCAT(candidate_name, '||') as recipient_names,
            MIN(job_id) as job_id,
            MIN(job_title) as job_title,
            SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as delivered,
            SUM(CASE WHEN opened_count > 0 THEN 1 ELSE 0 END) as opened,
            SUM(CASE WHEN clicked_count > 0 THEN 1 ELSE 0 END) as clicked,
            SUM(CASE WHEN replied_at IS NOT NULL THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            MIN(sent_at) as sent_at,
            COALESCE(MIN(sent_by), 'Admin') as sent_by,
            COALESCE(MIN(email_type), 'individual') as email_type
        FROM email_log
        {where_clause}
        GROUP BY COALESCE(batch_id, CAST(id AS TEXT))
        {having_clause}
        ORDER BY MIN(sent_at) DESC
        LIMIT ? OFFSET ?
    """, where_params + [per_page, offset]).fetchall()

    total = conn.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT COALESCE(batch_id, CAST(id AS TEXT))
            FROM email_log
            {where_clause}
            GROUP BY COALESCE(batch_id, CAST(id AS TEXT))
            {having_clause}
        )
    """, where_params).fetchone()[0]

    stats_row = conn.execute("""
        SELECT
            COALESCE(COUNT(*), 0) as total_sent,
            COALESCE(SUM(CASE WHEN opened_count > 0 THEN 1 ELSE 0 END), 0) as total_opened,
            COALESCE(SUM(CASE WHEN clicked_count > 0 THEN 1 ELSE 0 END), 0) as total_clicked,
            COALESCE(SUM(CASE WHEN replied_at IS NOT NULL THEN 1 ELSE 0 END), 0) as total_replied
        FROM email_log WHERE status = 'sent'
    """).fetchone()
    conn.close()

    result = [dict(r) for r in rows]
    for r in result:
        names = (r.get("recipient_names") or "").split("||")
        r["recipient_names_list"] = [n.strip() for n in names if n.strip()]

    stats = dict(stats_row) if stats_row else {
        "total_sent": 0, "total_opened": 0, "total_clicked": 0, "total_replied": 0
    }
    return result, total, stats


def get_email_hub_detail(group_id):
    """Return all emails in a group (by batch_id UUID or individual row id)."""
    conn = get_db()
    if str(group_id).isdigit():
        rows = conn.execute(
            "SELECT * FROM email_log WHERE id = ? ORDER BY sent_at",
            (int(group_id),)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM email_log WHERE batch_id = ? ORDER BY sent_at",
            (str(group_id),)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_attorney_pipeline_entries(attorney_id, attorney_source="fp", limit=10):
    """Return pipeline entries for a specific attorney (for profile Matched Jobs tab)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT p.id, p.stage, p.placement_fee, p.added_at, p.updated_at, p.notes,
               p.job_id, j.title as job_title, j.location, j.practice_area,
               j.salary_min, j.salary_max, j.status as job_status,
               e.id as employer_id, e.name as employer_name
        FROM pipeline p
        JOIN jobs j ON p.job_id = j.id
        LEFT JOIN employers e ON j.employer_id = e.id
        WHERE p.attorney_id = ? AND p.attorney_source = ?
        ORDER BY p.updated_at DESC, p.added_at DESC
        LIMIT ?
    """, (str(attorney_id), attorney_source, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_attorney_employment(attorney_id):
    """Return employment history for an attorney (stub — data from future API integration).
    # TODO: When Firm Prospects API is connected, populate attorney_employment
    #       from the employment history endpoint and return it here.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM attorney_employment WHERE attorney_id = ? ORDER BY is_current DESC, start_date DESC",
        (str(attorney_id),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_action_items() -> list:
    """Return smart action items derived from pipeline and task data."""
    conn = get_db()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    items = []

    # Overdue tasks
    overdue = conn.execute(
        """SELECT id, title, due_date, priority FROM tasks
           WHERE due_date < ? AND status NOT IN ('Completed','Cancelled')
           ORDER BY due_date ASC LIMIT 5""",
        (today,),
    ).fetchall()
    for t in overdue:
        items.append({
            "type": "overdue_task",
            "priority": "high",
            "message": f"Overdue: {t['title']} (was due {t['due_date']})",
            "action": f"View task #{t['id']}",
            "task_id": t["id"],
        })

    # Tasks due today
    due_today = conn.execute(
        """SELECT id, title, priority FROM tasks
           WHERE due_date = ? AND status NOT IN ('Completed','Cancelled')
           ORDER BY priority DESC LIMIT 5""",
        (today,),
    ).fetchall()
    for t in due_today:
        items.append({
            "type": "task_due_today",
            "priority": "medium",
            "message": f"Due today: {t['title']}",
            "action": f"View task #{t['id']}",
            "task_id": t["id"],
        })

    # Candidates stuck in Identified/Contacted for 7+ days
    stuck = conn.execute(
        """SELECT p.id, p.attorney_name, p.stage, p.added_at, j.title as job_title
           FROM pipeline p JOIN jobs j ON p.job_id = j.id
           WHERE p.stage IN ('Identified','Contacted')
             AND julianday('now') - julianday(p.added_at) >= 7
           ORDER BY p.added_at ASC LIMIT 5"""
    ).fetchall()
    for s in stuck:
        days = int(round(
            (datetime.utcnow() - datetime.fromisoformat(s["added_at"].replace(" ", "T").split(".")[0])).days
        )) if s["added_at"] else 0
        items.append({
            "type": "stuck_candidate",
            "priority": "medium",
            "message": f"{s['attorney_name']} stuck in {s['stage']} for {days}d on {s['job_title']}",
            "action": "View pipeline",
            "pipeline_id": s["id"],
        })

    # Active jobs with no pipeline candidates
    empty_jobs = conn.execute(
        """SELECT j.id, j.title, e.name as firm_name
           FROM jobs j
           LEFT JOIN employers e ON j.employer_id = e.id
           WHERE j.status = 'Active'
             AND NOT EXISTS (SELECT 1 FROM pipeline p WHERE p.job_id = j.id)
           ORDER BY j.created_at DESC LIMIT 3"""
    ).fetchall()
    for jb in empty_jobs:
        items.append({
            "type": "empty_job",
            "priority": "low",
            "message": f"No candidates for: {jb['title']}" + (f" at {jb['firm_name']}" if jb["firm_name"] else ""),
            "action": "Search candidates",
            "job_id": jb["id"],
        })

    conn.close()
    return items
