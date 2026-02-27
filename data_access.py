"""
data_access.py — JAIDE ATS Data Access Layer

Abstracts FP data (CSV / future API) from custom data (SQLite).
Swap FP source by changing only the `_fp_*` functions below.

Usage:
    from data_access import search_attorneys, search_jobs, search_firms
    from data_access import get_attorney, get_job, get_firm
    from data_access import init as da_init

    # At startup, call init with the loaded DataFrames:
    da_init(attorneys_df=ATTORNEYS_DF, jobs_df=JOBS_DF, firms_df=FIRMS_DF)
"""

import ats_db

# ---------------------------------------------------------------------------
# Module state — set at startup via init()
# ---------------------------------------------------------------------------
ATTORNEYS_DF = None
JOBS_DF = None
FIRMS_DF = None


def init(attorneys_df=None, jobs_df=None, firms_df=None):
    """Initialize module-level DataFrames from app.py startup."""
    global ATTORNEYS_DF, JOBS_DF, FIRMS_DF
    if attorneys_df is not None:
        ATTORNEYS_DF = attorneys_df
    if jobs_df is not None:
        JOBS_DF = jobs_df
    if firms_df is not None:
        FIRMS_DF = firms_df


# ---------------------------------------------------------------------------
# Public API — Attorneys
# ---------------------------------------------------------------------------

def search_attorneys(filters: dict) -> list:
    """Search all attorney sources and return a merged, score-sorted list.

    filters keys (all optional):
        search         str
        practice_area  str
        location       str
        grad_year_min  int
        grad_year_max  int
        source         str  "all" | "fp" | "custom"
    """
    source = filters.get("source", "all")
    fp_results = _search_fp_attorneys(filters) if source != "custom" else []
    custom_results = _search_custom_attorneys(filters) if source != "fp" else []
    return _merge(fp_results, custom_results)


def get_attorney(source: str, attorney_id) -> dict | None:
    """Fetch a single attorney by source + id."""
    if source == "fp":
        return _get_fp_attorney(attorney_id)
    return ats_db.get_custom_attorney(int(attorney_id))


# ---------------------------------------------------------------------------
# Public API — Jobs
# ---------------------------------------------------------------------------

def search_jobs(filters: dict) -> list:
    """Search all job sources.

    filters keys:
        search          str
        practice_area   str
        location        str
        status          str
        source          str  "all" | "fp" | "custom"
    """
    source = filters.get("source", "all")
    fp_results = _search_fp_jobs(filters) if source != "custom" else []
    custom_results = _search_custom_jobs(filters) if source != "fp" else []
    return _merge(fp_results, custom_results)


def get_job(source: str, job_id) -> dict | None:
    if source == "fp":
        return _get_fp_job(job_id)
    return ats_db.get_custom_job(int(job_id))


# ---------------------------------------------------------------------------
# Public API — Firms
# ---------------------------------------------------------------------------

def search_firms(filters: dict) -> list:
    """Search all firm sources.

    filters keys:
        search  str
        source  str  "all" | "fp" | "custom"
    """
    source = filters.get("source", "all")
    fp_results = _search_fp_firms(filters) if source != "custom" else []
    custom_results = _search_custom_firms(filters) if source != "fp" else []
    # Custom first, then FP alphabetically
    return custom_results + fp_results


def get_firm(source: str, firm_id) -> dict | None:
    if source == "fp":
        return _get_fp_firm(firm_id)
    return ats_db.get_custom_firm(int(firm_id))


# ---------------------------------------------------------------------------
# Internal helpers — FP (wraps existing pandas logic)
# ---------------------------------------------------------------------------

def _search_fp_attorneys(filters: dict) -> list:
    """Search FP attorneys DataFrame. Returns list of candidate dicts."""
    if ATTORNEYS_DF is None:
        return []
    import pandas as pd
    df = ATTORNEYS_DF.copy()
    search = (filters.get("search") or "").strip().lower()
    practice_area = (filters.get("practice_area") or "").strip().lower()
    location = (filters.get("location") or "").strip().lower()
    grad_year_min = filters.get("grad_year_min")
    grad_year_max = filters.get("grad_year_max")

    if search:
        name_col = (df.get("First Name", pd.Series("", index=df.index)).fillna("") + " " +
                    df.get("Last Name", pd.Series("", index=df.index)).fillna("")).str.lower()
        firm_col = df.get("Current Employer", pd.Series("", index=df.index)).fillna("").str.lower()
        mask = name_col.str.contains(search, regex=False) | firm_col.str.contains(search, regex=False)
        df = df[mask]
    if practice_area:
        pa_col = df.get("Specialties", pd.Series("", index=df.index)).fillna("").str.lower()
        df = df[pa_col.str.contains(practice_area, regex=False)]
    if location:
        loc_col = df.get("Bar Admission", pd.Series("", index=df.index)).fillna("").str.lower()
        df = df[loc_col.str.contains(location, regex=False)]
    if grad_year_min is not None or grad_year_max is not None:
        gy_col = pd.to_numeric(df.get("Graduation Year", pd.Series(None, index=df.index)), errors="coerce")
        if grad_year_min is not None:
            df = df[gy_col.isna() | (gy_col >= grad_year_min)]
        if grad_year_max is not None:
            df = df[gy_col.isna() | (gy_col <= grad_year_max)]

    results = []
    for _, row in df.head(100).iterrows():
        results.append({
            "id": str(row.get("FP ID", "")),
            "source": "fp",
            "name": f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
            "current_firm": row.get("Current Employer", ""),
            "graduation_year": row.get("Graduation Year", ""),
            "law_school": row.get("Law School", ""),
            "practice_areas": row.get("Specialties", ""),
            "email": row.get("Email", ""),
            "match_score": 50,
        })
    return results


def _get_fp_attorney(attorney_id) -> dict | None:
    if ATTORNEYS_DF is None:
        return None
    matches = ATTORNEYS_DF[ATTORNEYS_DF["FP ID"].astype(str) == str(attorney_id)]
    if matches.empty:
        return None
    row = matches.iloc[0]
    return {
        "id": str(row.get("FP ID", "")),
        "source": "fp",
        "name": f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
        "current_firm": row.get("Current Employer", ""),
        "graduation_year": row.get("Graduation Year", ""),
        "law_school": row.get("Law School", ""),
        "practice_areas": row.get("Specialties", ""),
        "email": row.get("Email", ""),
    }


def _search_fp_jobs(filters: dict) -> list:
    if JOBS_DF is None:
        return []
    import pandas as pd
    df = JOBS_DF.copy()
    search = (filters.get("search") or "").strip().lower()
    if search:
        mask = (
            df.get("Job Title", pd.Series("", index=df.index)).fillna("").str.lower().str.contains(search, regex=False) |
            df.get("Firm Name", pd.Series("", index=df.index)).fillna("").str.lower().str.contains(search, regex=False)
        )
        df = df[mask]
    results = []
    for _, row in df.head(50).iterrows():
        results.append({
            "id": str(row.get("FP ID", "")),
            "source": "fp",
            "firm_name": row.get("Firm Name", ""),
            "job_title": row.get("Job Title", ""),
            "job_location": row.get("Job Location", ""),
            "practice_areas": row.get("Practice Areas", ""),
            "status": row.get("Status", ""),
        })
    return results


def _get_fp_job(job_id) -> dict | None:
    if JOBS_DF is None:
        return None
    matches = JOBS_DF[JOBS_DF["FP ID"].astype(str) == str(job_id)]
    if matches.empty:
        return None
    row = matches.iloc[0]
    return {
        "id": str(row.get("FP ID", "")),
        "source": "fp",
        "firm_name": row.get("Firm Name", ""),
        "job_title": row.get("Job Title", ""),
        "job_location": row.get("Job Location", ""),
        "job_description": row.get("Job Description", ""),
    }


def _search_fp_firms(filters: dict) -> list:
    if FIRMS_DF is None:
        return []
    import pandas as pd
    df = FIRMS_DF.copy()
    search = (filters.get("search") or "").strip().lower()
    if search:
        df = df[df["Name"].fillna("").str.lower().str.contains(search, regex=False)]
    results = []
    for _, row in df.head(200).iterrows():
        results.append({
            "name": row.get("Name", ""),
            "source": "fp",
            "fp_id": str(row.get("Firm ID", "")),
            "total_attorneys": row.get("Total Attorneys", ""),
        })
    return results


def _get_fp_firm(firm_id) -> dict | None:
    if FIRMS_DF is None:
        return None
    matches = FIRMS_DF[FIRMS_DF["Firm ID"].astype(str) == str(firm_id)]
    if matches.empty:
        return None
    row = matches.iloc[0]
    return {
        "name": row.get("Name", ""),
        "source": "fp",
        "fp_id": str(row.get("Firm ID", "")),
    }


# ---------------------------------------------------------------------------
# Internal helpers — Custom (wraps ats_db)
# ---------------------------------------------------------------------------

def _search_custom_attorneys(filters: dict) -> list:
    return ats_db.list_custom_attorneys(
        search=filters.get("search", ""),
        practice_area=filters.get("practice_area", ""),
        location=filters.get("location", ""),
        grad_year_min=filters.get("grad_year_min"),
        grad_year_max=filters.get("grad_year_max"),
    )


def _search_custom_jobs(filters: dict) -> list:
    return ats_db.list_custom_jobs(
        search=filters.get("search", ""),
        status=filters.get("status"),
        practice_area=filters.get("practice_area"),
    )


def _search_custom_firms(filters: dict) -> list:
    return ats_db.list_custom_firms(search=filters.get("search", ""))


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------

def _merge(fp: list, custom: list) -> list:
    """Merge FP and custom results, sorted by match_score desc.
    Custom records always bubble to top if they have no match_score."""
    combined = []
    for r in custom:
        r.setdefault("match_score", 75)  # custom records rank high by default
        combined.append(r)
    for r in fp:
        r.setdefault("match_score", 50)
        combined.append(r)
    combined.sort(key=lambda r: -(r.get("match_score") or 0))
    return combined
