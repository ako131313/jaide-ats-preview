import os
import re
import json
import csv
import uuid
import traceback
import smtplib
import time
import threading
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import Counter
from flask import Flask, render_template, request, jsonify, Response, send_file, session, redirect
import io
import math
import numpy as np
import pandas as pd
import anthropic
import ats_db

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.path import Path as MplPath

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
    Table, TableStyle, PageBreak, HRFlowable,
)
from reportlab.lib.utils import ImageReader

# Load .env file if present
from dotenv import load_dotenv
load_dotenv()


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy/pandas types."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if pd.isna(obj):
            return None
        return super().default(obj)


def _repair_truncated_json(text):
    """Attempt to repair JSON that was truncated mid-output by closing
    open strings, arrays, and objects.  Returns a valid JSON string or
    raises ValueError if repair fails."""
    # First try as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    repaired = text.rstrip()

    # Close an unterminated string
    if repaired.count('"') % 2 != 0:
        repaired += '"'

    # Walk through to figure out what brackets/braces are unclosed
    in_string = False
    escape = False
    stack = []
    for ch in repaired:
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{':
            stack.pop()
        elif ch == ']' and stack and stack[-1] == '[':
            stack.pop()

    # Remove trailing comma before closing
    repaired = repaired.rstrip().rstrip(',')

    # Close unclosed brackets/braces in reverse order
    for opener in reversed(stack):
        repaired += ']' if opener == '[' else '}'

    return json.loads(repaired)

from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jaide-ats-2026-secret-key")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True


def _sanitize_for_json(obj):
    """Recursively convert numpy/pandas types to native Python for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return obj

# ---------------------------------------------------------------------------
# Claude API client
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
SHORTLIST_SIZE = 15  # send fewer candidates for speed
BIO_MAX_CHARS = 400  # compact bios

CLAUDE_SYSTEM_PROMPT = """You are an expert legal recruiting analyst. Given a job description, hiring patterns, and candidates, tier and rank them.

Tiers:
- Tier 1+ (Bull's-Eye): Exceptional match on substance AND hiring pattern signals (school, prior firm, specialty all align).
- Tier 1 (Strong Fit): Strong practice match plus at least one pattern signal.
- Tier 2 (Solid Fit): Good substance but missing pattern signals (wrong school, no bar, adjacent area).
- Tier 3 (Adjacent): Not direct but notable — boomerang, transferable skills, unique angle.

Return ONLY valid JSON (no markdown fences):

{
  "chat_summary": "2-3 paragraph recruiter briefing. Name the top 2-3 candidates and why they stand out.",
  "candidates": [
    {
      "rank": 1,
      "tier": "Tier 1+",
      "name": "Full name",
      "current_firm": "Firm",
      "graduation_year": 2021,
      "law_school": "School",
      "bar_admission": "Relevant bars",
      "specialties": "Practice areas",
      "prior_firms": "Prior firms",
      "pattern_matches": "Which signals match",
      "qualifications_summary": "1 sentence: why this tier, key strength, any gap."
    }
  ]
}

Rules:
- Most candidates should be Tier 2. Tier 1+ is rare (2-4 max).
- qualifications_summary must be exactly 1 sentence.
- Be specific — reference actual bio details.
- Missing required bar = downgrade.
- Respond with valid JSON only."""

# ---------------------------------------------------------------------------
# Data loading – runs once on startup
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_ATTORNEY_CSV_PATH = os.path.join(DATA_DIR, "attorneys.csv")

# Columns to load from the attorneys CSV. Heavy unused columns (attorneyBio,
# matters, fullbio_with_tags, matters_with_tags, prior_experience_with_tags,
# raw_memberships, raw_notable_matters) are excluded and loaded on-demand.
ATTORNEY_COLUMNS = {
    'id', 'first_name', 'last_name', 'firm_name', 'firm_type', 'location',
    'title', 'summary', 'practice_areas', 'specialty', 'added_keywords',
    'nlp_specialties', 'barAdmissions', 'lawSchool', 'graduationYear',
    'undergraduate', 'llm_school', 'llm_specialty', 'clerkships',
    'prior_experience', 'gender', 'diverse', 'top_200', 'vault_50',
    'vault_10', 'photo_url', 'profileURL', 'linkedinURL', 'languages',
    'raw_acknowledgements', 'email', 'phone_primary', 'scraped_on',
    'location_secondary',
}

# Bio cache: {str(attorney_id): bio+matters string}
# Populated in background thread at startup — instant lookups once ready.
_attorney_bio_cache: dict = {}
_attorney_bio_cache_ready = False


def _build_attorney_bio_cache():
    """Load bio + matters for all attorneys into an in-memory dict (background thread)."""
    global _attorney_bio_cache, _attorney_bio_cache_ready
    if not os.path.exists(_ATTORNEY_CSV_PATH):
        return
    try:
        df = pd.read_csv(_ATTORNEY_CSV_PATH, usecols=['id', 'attorneyBio', 'matters'], dtype=str)
        cache = {}
        for _, row in df.iterrows():
            aid = str(row.get('id', '') or '').strip()
            bio = str(row.get('attorneyBio', '') or '').strip()
            matters = str(row.get('matters', '') or '').strip()
            cache[aid] = (bio + (" " + matters if matters else "")).strip()
        _attorney_bio_cache = cache
        _attorney_bio_cache_ready = True
        print(f"Attorney bio cache ready: {len(_attorney_bio_cache)} entries")
    except Exception as e:
        print(f"Warning: could not build attorney bio cache: {e}")


def get_attorney_full_bio(attorney_id) -> str:
    """Return bio + matters for an attorney. Uses in-memory cache (built at startup)."""
    return _attorney_bio_cache.get(str(attorney_id), "")


def load_attorneys():
    path = _ATTORNEY_CSV_PATH
    if not os.path.exists(path):
        return pd.DataFrame()
    print("Loading attorneys CSV (filtered columns)...")
    df = pd.read_csv(
        path,
        usecols=lambda c: c in ATTORNEY_COLUMNS,
        dtype=str,
        low_memory=False,
    ).fillna("")
    mem_mb = df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"Attorneys DataFrame loaded: {len(df):,} rows, {len(df.columns)} columns, {mem_mb:.0f} MB")
    return df

def load_hiring_history():
    path = os.path.join(DATA_DIR, "hiring_history.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str).fillna("")
    return df

ATTORNEYS_DF = load_attorneys()
threading.Thread(target=_build_attorney_bio_cache, daemon=True).start()
HIRING_DF = load_hiring_history()

def load_jobs():
    path = os.path.join(DATA_DIR, "jobs.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    return df

JOBS_DF = load_jobs()

def load_firms():
    path = os.path.join(DATA_DIR, "firms.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    return df

FIRMS_DF = load_firms()

# ---------------------------------------------------------------------------
# Hiring DNA — pre-computed hiring pattern profiles for every firm
# ---------------------------------------------------------------------------

def compute_all_hiring_dna(hiring_df, min_hires=5):
    """Compute a Hiring DNA profile for every firm with enough hiring data."""
    if hiring_df.empty:
        return {}
    firm_counts = hiring_df["Firm"].value_counts()
    eligible = firm_counts[firm_counts >= min_hires].index.tolist()
    dna = {}
    for firm_name in eligible:
        fh = hiring_df[hiring_df["Firm"] == firm_name]
        total = len(fh)

        # Feeder schools
        schools = fh["Law School"].value_counts().head(15)
        feeder_schools = [{"school": s, "hires": int(c), "pct": round(c / total, 3)}
                          for s, c in schools.items() if s]

        # Feeder firms (law firm laterals only)
        lf_hires = fh[fh["Previous Entity Type"] == "Law Firm"]
        firms_from = lf_hires["Moved From"].value_counts().head(15)
        feeder_firms = [{"firm": f, "hires": int(c), "pct": round(c / len(lf_hires) if len(lf_hires) else 0, 3)}
                        for f, c in firms_from.items() if f]

        # Practice areas (comma-separated, explode)
        pa_series = fh["Practice Areas New"].str.split(",").explode().str.strip()
        pa_series = pa_series[pa_series != ""]
        pa_counts = pa_series.value_counts()
        practice_areas = [{"area": a, "hires": int(c), "pct": round(c / total, 3)}
                          for a, c in pa_counts.items()]

        # Specialties (comma-separated, explode)
        sp_series = fh["Specialties New"].str.split(",").explode().str.strip()
        sp_series = sp_series[sp_series != ""]
        sp_counts = sp_series.value_counts()
        specialties = [{"specialty": s, "hires": int(c)} for s, c in sp_counts.head(20).items()]

        # Class year range
        cy = pd.to_numeric(fh["Class Year"], errors="coerce").dropna()
        if len(cy) >= 3:
            cy_range = {"min": int(cy.quantile(0.1)), "max": int(cy.quantile(0.9)),
                        "median": int(cy.median())}
        elif len(cy) > 0:
            cy_range = {"min": int(cy.min()), "max": int(cy.max()), "median": int(cy.median())}
        else:
            cy_range = {"min": 2010, "max": 2024, "median": 2018}

        # Hiring locations
        loc_groups = fh.groupby(["City", "State"]).size().sort_values(ascending=False)
        hiring_locations = [{"location": city, "state": state, "hires": int(cnt)}
                            for (city, state), cnt in loc_groups.head(15).items() if city]

        # Title distribution
        title_dist = fh["Title"].value_counts().to_dict()
        title_distribution = {k: int(v) for k, v in title_dist.items() if k}

        dna[firm_name] = {
            "firm_name": firm_name,
            "total_hires": total,
            "feeder_schools": feeder_schools,
            "feeder_firms": feeder_firms,
            "practice_areas": practice_areas,
            "specialties": specialties,
            "class_year_range": cy_range,
            "hiring_locations": hiring_locations,
            "title_distribution": title_distribution,
        }
    return dna

HIRING_DNA = compute_all_hiring_dna(HIRING_DF)

# Cache for top-candidate results (firm_name → list of candidate dicts)
_top_candidates_cache = {}


def _rank_points(rank, tiers):
    """Return points based on rank position in a tiered structure."""
    for max_rank, pts in tiers:
        if rank <= max_rank:
            return pts
    return 0


def score_candidates_for_firm(firm_name):
    """Score all attorneys against a firm's Hiring DNA using vectorized pandas.
    Returns a list of top 50 candidate dicts sorted by score descending."""
    dna = HIRING_DNA.get(firm_name)
    if not dna or ATTORNEYS_DF.empty:
        return []

    df = ATTORNEYS_DF.copy()

    # Pre-compute sets/lists from DNA for fast lookup
    school_list = [s["school"] for s in dna["feeder_schools"]]
    school_set = set(school_list)
    school_rank = {s: i for i, s in enumerate(school_list)}

    firm_list = [f["firm"] for f in dna["feeder_firms"]]
    firm_set = set(f.lower() for f in firm_list)
    firm_rank = {f.lower(): i for i, f in enumerate(firm_list)}

    pa_list = [p["area"] for p in dna["practice_areas"]]
    pa_set = set(a.lower() for a in pa_list)
    pa_rank = {a.lower(): i for i, a in enumerate(pa_list)}

    spec_set = set(s["specialty"].lower() for s in dna["specialties"])

    cy_range = dna["class_year_range"]
    cy_min, cy_max, cy_med = cy_range["min"], cy_range["max"], cy_range["median"]

    loc_cities = set(l["location"].lower() for l in dna["hiring_locations"])
    loc_states = set(l["state"].lower() for l in dna["hiring_locations"])

    # --- 1. FEEDER SCHOOL (max 30) ---
    school_col = df["lawSchool"].fillna("").str.strip()
    school_pts = school_col.map(
        lambda s: _rank_points(school_rank.get(s, 999),
                               [(0, 30), (2, 22), (4, 15), (9, 10), (14, 5)])
    ).fillna(0).astype(int)

    # --- 2. FEEDER FIRM — current (max 25) + prior (max 12) ---
    current_firm_col = df["firm_name"].fillna("").str.lower().str.strip()
    current_firm_pts = current_firm_col.map(
        lambda f: _rank_points(firm_rank.get(f, 999),
                               [(0, 25), (2, 18), (4, 12), (9, 8), (14, 4)])
    ).fillna(0).astype(int)

    prior_col = df.get("prior_experience", pd.Series("", index=df.index)).fillna("").str.lower()
    prior_firm_pts = pd.Series(0, index=df.index)
    for feeder_lower, rank in firm_rank.items():
        mask = prior_col.str.contains(feeder_lower, regex=False, na=False)
        pts = int(_rank_points(rank, [(0, 12), (2, 9), (4, 6), (9, 4), (14, 2)]))
        candidate_pts = mask.astype(int) * pts
        prior_firm_pts = prior_firm_pts.where(prior_firm_pts >= candidate_pts, candidate_pts)

    firm_pts = (current_firm_pts + prior_firm_pts).clip(upper=25)

    # --- 3. PRACTICE AREA (max 20) ---
    pa_col = df["practice_areas"].fillna("").str.lower()
    pa_pts = pd.Series(0, index=df.index)
    for area_lower, rank in pa_rank.items():
        mask = pa_col.str.contains(area_lower, regex=False, na=False)
        pts = _rank_points(rank, [(0, 20), (2, 15), (4, 10), (99, 5)])
        pa_pts += mask.astype(int) * int(pts)
    pa_pts = pa_pts.clip(upper=20)

    # --- 4. SPECIALTY MATCH (max 15) ---
    spec_col = df.get("specialty", pd.Series("", index=df.index)).fillna("").str.lower()
    spec_count = pd.Series(0, index=df.index)
    for spec in spec_set:
        spec_count += spec_col.str.contains(spec, regex=False, na=False).astype(int)
    spec_pts = pd.Series(0, index=df.index)
    spec_pts[spec_count >= 3] = 15
    spec_pts[(spec_count == 2) & (spec_pts == 0)] = 10
    spec_pts[(spec_count == 1) & (spec_pts == 0)] = 5

    # --- 5. CLASS YEAR FIT (max 5) ---
    grad_yr = pd.to_numeric(df["graduationYear"], errors="coerce")
    cy_pts = pd.Series(0, index=df.index)
    cy_pts[(grad_yr >= cy_min) & (grad_yr <= cy_max)] = 5
    cy_pts[(cy_pts == 0) & ((grad_yr - cy_med).abs() <= 2)] = 3

    # --- 6. LOCATION MATCH (max 5) ---
    location_col = df["location"].fillna("").str.lower()
    loc_pts = pd.Series(0, index=df.index)
    for city in loc_cities:
        loc_pts |= location_col.str.contains(city, regex=False, na=False).astype(int) * 5
    loc_pts = loc_pts.clip(upper=5)

    # --- 7. BOOMERANG (max 10) ---
    boom_pts = pd.Series(0, index=df.index)
    fn_lower = firm_name.lower()
    boom_pts[prior_col.str.contains(fn_lower, regex=False, na=False)] = 10

    # Exclude attorneys currently at this firm
    at_firm_mask = current_firm_col.str.contains(fn_lower, regex=False, na=False)
    at_firm_mask |= current_firm_col.apply(lambda f: bool(f) and f in fn_lower)

    # --- Total ---
    total = (school_pts + firm_pts + pa_pts + spec_pts + cy_pts + loc_pts + boom_pts)
    total[at_firm_mask] = 0  # zero out current employees

    # Build match reasons for top candidates
    df["_dna_score"] = total
    df["_school_pts"] = school_pts
    df["_firm_pts"] = firm_pts
    df["_pa_pts"] = pa_pts
    df["_spec_pts"] = spec_pts
    df["_cy_pts"] = cy_pts
    df["_loc_pts"] = loc_pts
    df["_boom_pts"] = boom_pts

    # Filter to score > 0 and take top 50
    result = df[total > 0].nlargest(50, "_dna_score")

    candidates = []
    for _, row in result.iterrows():
        reasons = []
        school = row.get("lawSchool", "").strip()
        if school in school_set:
            r = school_rank[school]
            reasons.append(f"#{r+1} Feeder School" if r < 3 else "Feeder School")
        cur_f = row.get("firm_name", "").lower().strip()
        if cur_f in firm_set:
            r = firm_rank[cur_f]
            reasons.append(f"#{r+1} Feeder Firm" if r < 3 else "Feeder Firm")
        elif row["_boom_pts"] > 0:
            reasons.append("Boomerang")
        elif row["_firm_pts"] > 0 and row["_firm_pts"] != current_firm_pts.get(row.name, 0):
            reasons.append("Ex-Feeder Firm")
        if row["_pa_pts"] > 0:
            reasons.append("Practice Area Match")
        if row["_spec_pts"] > 0:
            reasons.append("Specialty Match")
        if row["_loc_pts"] > 0:
            reasons.append("Location Match")
        if row["_cy_pts"] > 0:
            reasons.append("Class Year Fit")

        candidates.append({
            "id": row.get("id", ""),
            "name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
            "first_name": row.get("first_name", ""),
            "last_name": row.get("last_name", ""),
            "current_firm": row.get("firm_name", ""),
            "title": row.get("title", ""),
            "graduation_year": row.get("graduationYear", ""),
            "law_school": row.get("lawSchool", ""),
            "practice_areas": row.get("practice_areas", ""),
            "specialty": row.get("specialty", ""),
            "location": row.get("location", ""),
            "match_score": int(row["_dna_score"]),
            "match_reasons": reasons[:4],
            "score_breakdown": {
                "school": int(row["_school_pts"]),
                "firm": int(row["_firm_pts"]),
                "practice_area": int(row["_pa_pts"]),
                "specialty": int(row["_spec_pts"]),
                "class_year": int(row["_cy_pts"]),
                "location": int(row["_loc_pts"]),
                "boomerang": int(row["_boom_pts"]),
            },
        })
    return candidates


def _resolve_dna_firm_name(name):
    """Resolve a firm name to its HIRING_DNA key (exact, then case-insensitive, then partial)."""
    if name in HIRING_DNA:
        return name
    name_lower = name.lower()
    for key in HIRING_DNA:
        if key.lower() == name_lower:
            return key
    for key in HIRING_DNA:
        if name_lower in key.lower() or key.lower() in name_lower:
            return key
    return None


def get_top_candidates(firm_name):
    """Return cached top candidates for a firm, or compute and cache."""
    resolved = _resolve_dna_firm_name(firm_name)
    if not resolved:
        return []
    if resolved in _top_candidates_cache:
        return _top_candidates_cache[resolved]
    results = score_candidates_for_firm(resolved)
    _top_candidates_cache[resolved] = results
    return results


# ---------------------------------------------------------------------------
# Fuzzy firm name matching
# ---------------------------------------------------------------------------
# Pre-compute a clean word-set for every unique firm in the hiring data
_FIRM_NOISE = {"llp", "lp", "llc", "pc", "plc", "pllc", "l.l.p.", "p.c.",
               "and", "&", "the", ",", ".", "of"}

def _firm_words(name):
    """Return set of lower-cased significant words in a firm name."""
    tokens = re.split(r"[\s,&.]+", name.lower())
    return {t for t in tokens if t and t not in _FIRM_NOISE}

# Build index: {canonical_name: word_set}
FIRM_INDEX = {}
if not HIRING_DF.empty:
    for firm in HIRING_DF["Firm"].dropna().unique():
        FIRM_INDEX[firm] = _firm_words(firm)

def fuzzy_match_firm(query):
    """Match a user-provided firm name against the hiring history firms.

    Returns (canonical_firm_name, score) or (None, 0).

    Scoring: fraction of query words found in the candidate firm name,
    plus a bonus when candidate words appear in the query (bidirectional).
    Picks the best match above a threshold.
    """
    if not query or not FIRM_INDEX:
        return None, 0

    query_words = _firm_words(query)
    if not query_words:
        return None, 0

    best_firm = None
    best_score = 0

    for firm, firm_words in FIRM_INDEX.items():
        if not firm_words:
            continue
        # What fraction of the query words appear in the firm name?
        forward = len(query_words & firm_words) / len(query_words)
        # What fraction of the firm words appear in the query?
        backward = len(query_words & firm_words) / len(firm_words)
        # Combined score – weight forward higher (user typed it)
        score = 0.6 * forward + 0.4 * backward
        if score > best_score:
            best_score = score
            best_firm = firm

    # Require at least 50% overlap to accept
    if best_score >= 0.5:
        return best_firm, best_score
    return None, 0

# ---------------------------------------------------------------------------
# JD parsing helpers
# ---------------------------------------------------------------------------

def extract_firm_name(text):
    """Try to pull a firm name from the JD text.

    Strategy:
    1. Look for contextual clues — phrases like "hiring for", "position at",
       "opportunity at", "is seeking" — that identify the *hiring* firm.
    2. Look for explicit firm name patterns (e.g. ending in LLP/LLC).
    3. Fallback: fuzzy-match sliding windows against the known firm index.
    """
    # 1. Contextual: find the firm that is hiring (not just any firm mentioned)
    hiring_patterns = [
        r"(?:hiring\s+for|position\s+at|role\s+at|opportunity\s+at|join|seeking\s+(?:a|an)\s+\w+\s+(?:for|at))\s+([A-Z][A-Za-z &,.']+?)(?:\.|,|\s+is\b|\s+in\b|\s+for\b|\s+has\b)",
        r"^([A-Z][A-Za-z &,.']+?)(?:\s+is\s+(?:hiring|seeking|looking|recruiting))",
        r"(?:about\s+(?:the\s+)?(?:firm|company|employer)[:\s]+)([A-Z][A-Za-z &,.']+)",
    ]
    for pat in hiring_patterns:
        m = re.search(pat, text, re.MULTILINE)
        if m:
            candidate = m.group(1).strip().rstrip(",.")
            # Verify it's a known firm
            firm, score = fuzzy_match_firm(candidate)
            if firm and score >= 0.6:
                return candidate

    # 2. Explicit suffix patterns (LLP, LLC, etc.)
    suffix_patterns = [
        r"(?:hiring\s+for|position\s+at|role\s+at|opportunity\s+at|join)\s+([A-Z][A-Za-z &,.']+(?:LLP|LLC|PC|L\.L\.P\.|P\.C\.))",
        r"([\w &,.']+(?:LLP|LLC|PC|L\.L\.P\.|P\.C\.))",
    ]
    for pat in suffix_patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()

    # 3. Fallback: slide a window over the text and fuzzy-match against known firms
    #    Prioritize matches near the start of the text (more likely to be the hiring firm)
    words = text.split()
    best_match = None
    best_score = 0
    best_pos = len(words)
    for size in range(1, 5):
        for i in range(len(words) - size + 1):
            window = " ".join(words[i:i + size])
            firm, score = fuzzy_match_firm(window)
            if firm and (score > best_score or (score == best_score and i < best_pos)):
                best_score = score
                best_match = window
                best_pos = i
    if best_match and best_score >= 0.5:
        return best_match
    return ""

def extract_location(text):
    """Extract all cities/states from JD. Returns a list of (city, state) tuples."""
    state_map = {"MA": "Massachusetts", "NY": "New York", "CA": "California",
                 "IL": "Illinois", "TX": "Texas", "DC": "District of Columbia",
                 "FL": "Florida", "GA": "Georgia", "CO": "Colorado", "PA": "Pennsylvania"}
    city_state = re.findall(r"(Boston|New York|San Francisco|Chicago|Los Angeles|Washington|Houston|Dallas|Austin|Seattle|Miami|Atlanta|Denver|Philadelphia),?\s*(Massachusetts|MA|New York|NY|California|CA|Illinois|IL|Texas|TX|Washington|DC|Florida|FL|Georgia|GA|Colorado|CO|Pennsylvania|PA)?", text, re.IGNORECASE)
    seen = set()
    locations = []
    for match in city_state:
        city = match[0].strip()
        state = match[1].strip() if match[1] else ""
        state = state_map.get(state.upper(), state) if state else ""
        key = city.lower()
        if key not in seen:
            seen.add(key)
            locations.append((city, state))
    return locations

CURRENT_YEAR = 2026

def extract_grad_years(text):
    """Extract graduation year range from JD.

    Handles:
      - Explicit class years: "class of 2019-2022"
      - Years of experience: "3-5 years", "3 to 5 years of experience"
      - Single experience: "5+ years", "at least 5 years"
    """
    # 1. Explicit class year ranges
    m = re.search(r"class\s+(?:of\s+)?(?:years?\s+)?(\d{4})\s*[-–to]+\s*(\d{4})", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{4})\s*[-–to]+\s*(\d{4})\s*(?:class|grad)", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 2. Years of experience range: "3-5 years", "3 to 5 years of experience"
    m = re.search(r"(\d{1,2})\s*[-–to]+\s*(\d{1,2})\s*(?:\+\s*)?years?\b", text, re.IGNORECASE)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= 30 and 1 <= hi <= 30:
            return CURRENT_YEAR - hi, CURRENT_YEAR - lo

    # 3. Single experience: "5+ years", "at least 5 years", "minimum 5 years"
    m = re.search(r"(?:at\s+least|minimum|min\.?|over)?\s*(\d{1,2})\+?\s*years?\s+(?:of\s+)?(?:experience|practice)", text, re.IGNORECASE)
    if m:
        yrs = int(m.group(1))
        if 1 <= yrs <= 30:
            return CURRENT_YEAR - yrs - 3, CURRENT_YEAR - yrs  # allow 3-year band above

    # 4. Explicit class years
    years = re.findall(r"(?:class\s+(?:of\s+)?|graduat\w+\s+(?:in\s+)?)(\d{4})", text, re.IGNORECASE)
    if len(years) >= 2:
        yrs = sorted(int(y) for y in years)
        return yrs[0], yrs[-1]
    if len(years) == 1:
        y = int(years[0])
        return y - 2, y + 2

    return None, None


_ASSOCIATE_TITLES = [
    "associate", "senior associate", "managing associate",
    "senior managing associate", "staff attorney", "attorney",
    "senior attorney", "project attorney", "discovery attorney",
    "senior staff attorney", "senior discovery attorney",
    "foreign associate", "international associate",
    "career associate", "senior career associate",
    "practice group associate", "practice area associate",
    "foreign associate attorney",
]

_PARTNER_COUNSEL_TITLES = [
    "partner", "managing partner", "office managing partner",
    "of counsel", "counsel", "senior counsel",
    "special counsel", "member", "shareholder", "principal",
    "co-chair", "chair", "vice chair", "director",
    "co-head", "head", "practice leader", "co-leader",
]


def extract_title_level(text):
    """Detect the seniority level the JD is looking for.

    Returns a list of acceptable title patterns (lowercase) or empty list
    if no specific level is detected.

    Uses word-boundary matching and context-aware counting to avoid
    false positives from incidental mentions (e.g. "work with our partners"
    in an associate-level JD).
    """
    text_lower = text.lower()

    # Partner-level signals
    partner_signals = [
        "income partner", "non-equity partner", "equity partner",
        "of counsel", "counsel-level", "partner",
    ]
    # Associate-level signals
    associate_signals = [
        "senior associate", "junior associate",
        "mid-level associate", "midlevel associate",
        "senior-level associate", "associate",
    ]

    # Use word-boundary regex to avoid matching "partnering", "associated", etc.
    # Allow optional plural (partners, associates)
    found_partner = any(
        re.search(r'\b' + re.escape(s) + r's?\b', text_lower)
        for s in partner_signals
    )
    found_associate = any(
        re.search(r'\b' + re.escape(s) + r's?\b', text_lower)
        for s in associate_signals
    )

    if found_partner and found_associate:
        # Both detected — resolve by filtering out non-title references.
        # Phrases like "our partners", "with partners", "the associates"
        # are references to existing people, not the role being hired.
        _NONTITLE_PREFIXES = r'\b(?:our|the|with|alongside|by)\s+(?:\w+\s+){0,2}'

        partner_total = sum(
            len(re.findall(r'\b' + re.escape(s) + r's?\b', text_lower))
            for s in partner_signals
        )
        partner_nontitle = len(re.findall(
            _NONTITLE_PREFIXES + r'partners?\b', text_lower))
        partner_title = max(0, partner_total - partner_nontitle)

        assoc_total = sum(
            len(re.findall(r'\b' + re.escape(s) + r's?\b', text_lower))
            for s in associate_signals
        )
        assoc_nontitle = len(re.findall(
            _NONTITLE_PREFIXES + r'associates?\b', text_lower))
        assoc_title = max(0, assoc_total - assoc_nontitle)

        if assoc_title > 0 and partner_title == 0:
            found_partner = False
        elif partner_title > 0 and assoc_title == 0:
            found_associate = False
        elif assoc_title >= partner_title * 2:
            found_partner = False
        elif partner_title >= assoc_title * 2:
            found_associate = False
        else:
            return []  # truly mixed — don't filter

    if found_associate:
        return list(_ASSOCIATE_TITLES)

    if found_partner:
        return list(_PARTNER_COUNSEL_TITLES)

    return []  # no clear signal — don't filter

def extract_practice_area(text):
    areas = {
        "Fund Formation": ["fund formation", "fund structuring"],
        "Private Equity": ["private equity"],
        "Venture Capital": ["venture capital"],
        "M&A": ["m&a", "mergers and acquisitions", "merger"],
        "Corporate": ["corporate"],
        "Tax": ["tax"],
        "Litigation": ["litigation"],
        "Investment Management": ["investment management", "investment adviser"],
        "Real Estate": ["real estate"],
        "IP": ["intellectual property", "patent", "trademark"],
    }
    text_lower = text.lower()
    found = []
    for area, keywords in areas.items():
        for kw in keywords:
            if kw in text_lower:
                found.append(area)
                break
    return found

def extract_bar(text):
    bars = {
        "Massachusetts": ["massachusetts bar", "admitted in massachusetts", "massachusetts"],
        "New York": ["new york bar", "admitted in new york", "new york"],
        "California": ["california bar", "admitted in california", "california"],
    }
    text_lower = text.lower()
    found = []
    for state, keywords in bars.items():
        for kw in keywords:
            if kw in text_lower:
                found.append(state)
                break
    return found

# ---------------------------------------------------------------------------
# Law school alias map — auto-generated from data + manual abbreviations
# ---------------------------------------------------------------------------

# Manual abbreviations that can't be auto-derived from school names
_MANUAL_SCHOOL_ABBREVS = {
    "hls": "Harvard University",
    "yls": "Yale University",
    "sls": "Stanford University",
    "nyu": "New York University",
    "nyu law": "New York University",
    "uchicago": "University of Chicago",
    "upenn": "University of Pennsylvania",
    "penn": "University of Pennsylvania",
    "penn law": "University of Pennsylvania",
    "uva": "University of Virginia",
    "uva law": "University of Virginia",
    "umich": "University of Michigan",
    "gulc": "Georgetown University",
    "gwu": "George Washington University",
    "gw": "George Washington University",
    "bc law": "Boston College",
    "bu law": "Boston University",
    "boalt": "University of California Berkeley",
    "uc berkeley": "University of California Berkeley",
    "berkeley": "University of California Berkeley",
    "ucla": "University of California Los Angeles",
    "uc davis": "University of California Davis",
    "uci": "University of California Irvine",
    "usc": "University of Southern California",
    "ut law": "University of Texas",
    "usf": "University of San Francisco",
    "unc": "University of North Carolina",
}

# Words too common/ambiguous to use as standalone school aliases
_SCHOOL_STOPWORDS = {
    "law", "school", "university", "college", "institute", "center",
    "the", "of", "and", "at", "in", "for", "de", "del",
    # Geographic terms that overlap with city/state extraction
    "new", "york", "san", "los", "saint", "south", "north", "west", "east",
    "national", "international", "american", "catholic", "central", "western",
    "southern", "northern", "eastern", "pacific", "atlantic", "royal",
}


def _build_school_alias_map(attorneys_df):
    """Auto-generate a law school alias map from the lawSchool column.

    For each unique school name, generates lookup keys:
      - Full name lowercase:         "harvard university" → Harvard University
      - Strip 'University' suffix:   "harvard" → Harvard University
      - Strip 'Law School' suffix:   "brooklyn" → Brooklyn Law School
      - Strip 'School of Law':       "columbus" → Columbus School of Law
      - 'University of X' → 'X':     "virginia" → University of Virginia
      - Plus ' law' variants:        "harvard law" → Harvard University

    Skips keys that are too short (< 4 chars), are stopwords, or would create
    ambiguous collisions (e.g. two schools mapping to the same short alias).
    In collision cases, the school with more attorneys wins.
    """
    if attorneys_df.empty:
        return {}

    schools_series = attorneys_df["lawSchool"].dropna().str.strip()
    schools_series = schools_series[schools_series != ""]
    school_counts = schools_series.value_counts()

    # Build candidate alias → (canonical_name, attorney_count) pairs
    candidates = {}  # alias → list of (canonical, count)

    def _add(alias, canonical, count):
        alias = alias.lower().strip()
        if len(alias) < 4 or alias in _SCHOOL_STOPWORDS:
            return
        # Skip if alias is just digits or all stopwords
        words = set(alias.split())
        if words <= _SCHOOL_STOPWORDS:
            return
        if alias not in candidates:
            candidates[alias] = []
        candidates[alias].append((canonical, count))

    for canonical, count in school_counts.items():
        name = str(canonical).strip()
        if not name:
            continue

        # 1. Full name
        _add(name, name, count)

        # 2. Strip " University" suffix → "Harvard", "Georgetown", etc.
        if name.endswith(" University"):
            short = name[:-len(" University")]
            _add(short, name, count)
            _add(short + " law", name, count)

        # 3. Strip " Law School" suffix → "Brooklyn", "Albany", etc.
        if name.endswith(" Law School"):
            short = name[:-len(" Law School")]
            _add(short, name, count)
            _add(short + " law", name, count)

        # 4. Strip " School of Law" suffix → "Columbus", etc.
        if "School of Law" in name:
            short = name.replace(" School of Law", "").strip()
            _add(short, name, count)
            _add(short + " law", name, count)

        # 5. "University of X" → "X"
        m = re.match(r"University of (.+)", name)
        if m:
            short = m.group(1).strip()
            # Also handle "University of California, Berkeley" → "berkeley"
            if "," in short:
                parts = short.split(",")
                _add(parts[-1].strip(), name, count)
            _add(short, name, count)
            _add(short + " law", name, count)

        # 6. "X College" → "X"
        if name.endswith(" College"):
            short = name[:-len(" College")]
            _add(short, name, count)
            _add(short + " law", name, count)

        # 7. "X College of Law" → "X"
        if "College of Law" in name:
            short = name.replace(" College of Law", "").strip()
            _add(short, name, count)

        # 8. Names with " Law" (e.g. "Cardozo Law") — also add without
        if name.endswith(" Law"):
            short = name[:-len(" Law")]
            _add(short, name, count)

    # Resolve collisions: highest-count school wins the alias
    alias_map = {}
    for alias, options in candidates.items():
        # Sort by count descending — most attorneys wins
        options.sort(key=lambda x: x[1], reverse=True)
        alias_map[alias] = options[0][0]

    # Layer on manual abbreviations (always win over auto-generated)
    for abbrev, canonical in _MANUAL_SCHOOL_ABBREVS.items():
        # Verify the canonical name actually exists in the data
        if canonical in school_counts.index:
            alias_map[abbrev.lower()] = canonical

    return alias_map


_LAW_SCHOOL_ALIASES = _build_school_alias_map(ATTORNEYS_DF)
# Pre-sort keys longest-first for matching priority
_LAW_SCHOOL_SORTED_KEYS = sorted(_LAW_SCHOOL_ALIASES.keys(), key=len, reverse=True)


def extract_law_school(text):
    """Extract law school name from search text. Returns the canonical school name or empty string.

    Tries longest alias first so 'boston college' matches before 'boston'.
    Normalizes '&' / 'and' so 'washington and lee' matches 'washington & lee'.
    """
    text_lower = text.lower()
    # Normalize: also try with & ↔ and swap so user can type either form
    text_and = text_lower.replace("&", "and")
    text_amp = re.sub(r'\band\b', '&', text_lower)
    for alias in _LAW_SCHOOL_SORTED_KEYS:
        pattern = r'\b' + re.escape(alias) + r'\b'
        if re.search(pattern, text_lower) or re.search(pattern, text_and) or re.search(pattern, text_amp):
            return _LAW_SCHOOL_ALIASES[alias]
    return ""


def extract_keywords(text):
    """Pull substantive keywords from JD for scoring."""
    keyword_phrases = [
        # Fund Formation / PE / VC
        "fund formation", "private equity", "venture capital", "growth equity",
        "hedge fund", "credit fund", "real estate fund",
        "partnership agreement", "limited partnership", "LPA",
        "side letter", "subscription agreement", "offering document",
        "investor negotiation", "institutional investor",
        "carried interest", "GP commitment", "management fee", "GP economics",
        "co-investment", "secondary transaction",
        "emerging manager", "first-time fund",
        "fund structuring", "fund sponsor", "fund manager",
        "investment management", "portfolio company",
        "private investment fund", "registered investment adviser",
        # M&A / Corporate
        "M&A", "mergers and acquisitions", "leveraged buyout",
        "securities offering", "capital markets",
        "corporate governance", "joint venture", "due diligence",
        "stock purchase", "asset purchase", "tender offer",
        "proxy statement", "board advisory", "shareholder",
        "purchase agreement", "merger agreement", "reorganization",
        # Securities / Regulatory
        "Investment Advisers Act", "Investment Company Act", "Securities Act",
        "SEC compliance", "SEC examination", "regulatory compliance",
        "securities regulation", "broker-dealer", "public offering", "IPO",
        # Real Estate
        "real estate", "commercial real estate", "real property",
        "lease", "leasing", "commercial lease",
        "mortgage", "CMBS", "real estate finance",
        "zoning", "land use", "development", "construction",
        "acquisition and disposition", "title", "easement",
        "condominium", "cooperative", "mixed-use",
        "real estate joint venture", "REIT",
        "landlord", "tenant", "property management",
        # Litigation
        "litigation", "trial", "arbitration", "mediation",
        "class action", "securities litigation", "commercial litigation",
        "antitrust litigation", "product liability", "tort",
        "discovery", "deposition", "motion practice",
        "appellate", "white collar", "government investigation",
        "insurance coverage", "employment litigation",
        # Banking / Finance
        "banking", "lending", "credit facility", "loan",
        "leveraged finance", "syndicated loan", "asset-based lending",
        "project finance", "structured finance", "securitization",
        "debt financing", "mezzanine", "revolving credit",
        # IP
        "intellectual property", "patent", "trademark", "copyright",
        "trade secret", "licensing", "IP litigation",
        "patent prosecution", "patent litigation",
        # Labor / Employment
        "labor", "employment", "ERISA", "employee benefits",
        "wage and hour", "discrimination", "workplace",
        "NLRB", "collective bargaining", "OSHA",
        # Tax
        "tax", "tax planning", "tax controversy", "transfer pricing",
        "state and local tax", "SALT", "international tax",
        "tax-exempt", "partnership tax",
        # Bankruptcy / Restructuring
        "bankruptcy", "restructuring", "insolvency",
        "chapter 11", "creditor", "debtor",
        "distressed debt", "workout",
        # Energy / Environmental
        "energy", "environmental", "renewable energy",
        "oil and gas", "power", "utilities", "clean energy",
        "climate", "ESG", "sustainability",
        # Healthcare
        "healthcare", "health care", "FDA", "life sciences",
        "pharmaceutical", "HIPAA", "medical device",
        # Antitrust
        "antitrust", "competition", "FTC", "DOJ",
        "Hart-Scott-Rodino", "merger clearance",
        # General
        "regulatory", "compliance", "government contracts",
        "international trade", "sanctions", "CFIUS",
        "data privacy", "cybersecurity", "GDPR", "CCPA",
        "executive compensation", "equity incentive",
        "technology transactions", "SaaS", "cloud",
        "pro bono",
    ]
    text_lower = text.lower()
    return [kw for kw in keyword_phrases if kw.lower() in text_lower]

# ---------------------------------------------------------------------------
# Scoring & tiering
# ---------------------------------------------------------------------------

def score_attorneys_vectorized(df, keywords, firm_patterns):
    """Score all attorneys in df at once using vectorized pandas operations.

    Returns a new DataFrame with only rows that meet the tier threshold (score >= 20),
    sorted by match_score descending, with scoring columns added.

    With firm (100 pts total):
      - Contextual match   (50 pts) — JD keywords found in bio/summary/matters
      - Feeder firm        (14 pts) — candidate from/at a firm the hiring firm pulls from
      - Practice area      (14 pts) — practice_areas + specialty field overlap
      - Feeder school      (10 pts) — candidate attended a top feeder school
      - Credential bonus    (8 pts) — top200, vault50, clerkship, accolades
      - Specialty match     (4 pts) — candidate's specialty matches firm's common hires

    Without firm (100 pts total — pattern points redistributed):
      - Contextual match   (64 pts)
      - Practice area      (22 pts)
      - Credential bonus   (14 pts)
      - Patterns            (0 pts)
    """
    if df.empty:
        return df.iloc[0:0].copy()

    has_firm = bool(firm_patterns.get("matched_firm"))

    # --- Build combined text columns once (vectorized string concat) ---
    bio_col = (
        df.get("attorneyBio", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("summary", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("matters", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("added_keywords", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("nlp_specialties", pd.Series("", index=df.index)).fillna("")
    ).str.lower()

    spec_col = (
        df.get("practice_areas", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("specialty", pd.Series("", index=df.index)).fillna("")
    ).str.lower()

    combined_col = bio_col + " " + spec_col

    # --- 1. Keyword match (0-50) ---
    kw_count = pd.Series(0, index=df.index)
    kw_matched_lists = pd.Series([[] for _ in range(len(df))], index=df.index)
    for kw in keywords:
        kw_lower = kw.lower()
        mask = combined_col.str.contains(kw_lower, regex=False, na=False)
        kw_count += mask.astype(int)
        # Track which keywords matched for rationale (only for top candidates later)

    kw_ratio = kw_count / max(len(keywords), 1)
    kw_max = 50 if has_firm else 64
    kw_pts = (kw_ratio.clip(upper=1.0) * kw_max).round().astype(int)

    # --- 2. Practice area overlap ---
    # Build PA terms from both keywords AND extracted practice areas
    jd_pa_terms = set()
    for kw in keywords:
        jd_pa_terms.update(kw.lower().split())
    # Also include practice areas extracted from the JD (passed via firm_patterns)
    for pa in firm_patterns.get("_practice_areas", []):
        jd_pa_terms.update(pa.lower().split())
    num_jd_terms = max(len(jd_pa_terms), 1)

    pa_count = pd.Series(0, index=df.index)
    for term in jd_pa_terms:
        pa_count += spec_col.str.contains(r'(?:^|[\s,;/])' + re.escape(term) + r'(?:$|[\s,;/])',
                                           regex=True, na=False).astype(int)
    pa_max = 14 if has_firm else 22
    pa_pts = ((pa_count / num_jd_terms).clip(upper=1.0) * pa_max).round().astype(int)

    # --- 3. Hiring pattern signals (0-28: firm 14 + school 10 + spec 4) ---
    pattern_pts = pd.Series(0, index=df.index)

    feeder_firms = firm_patterns.get("feeder_firms", [])
    if feeder_firms:
        prior_col = df.get("prior_experience", pd.Series("", index=df.index)).fillna("").str.lower()
        firm_col = df.get("firm_name", pd.Series("", index=df.index)).fillna("").str.lower()
        feeder_mask = pd.Series(False, index=df.index)
        for feeder in feeder_firms:
            fl = feeder.lower()
            feeder_mask |= prior_col.str.contains(fl, regex=False, na=False)
            feeder_mask |= firm_col.str.contains(fl, regex=False, na=False)
        pattern_pts += feeder_mask.astype(int) * 14

    feeder_schools = set(firm_patterns.get("feeder_schools", []))
    if feeder_schools:
        school_col = df.get("lawSchool", pd.Series("", index=df.index)).fillna("").str.strip()
        pattern_pts += school_col.isin(feeder_schools).astype(int) * 10

    top_specialties = firm_patterns.get("top_specialties", [])
    if top_specialties:
        spec_mask = pd.Series(False, index=df.index)
        for spec in top_specialties:
            spec_mask |= spec_col.str.contains(spec.lower(), regex=False, na=False)
        pattern_pts += spec_mask.astype(int) * 4

    pattern_pts = pattern_pts.clip(upper=28)

    # --- 4. Credential bonus (0-8) ---
    cred_pts = pd.Series(0, index=df.index)
    if "top_200" in df.columns:
        cred_pts += (df["top_200"].fillna("").str.upper() == "TRUE").astype(int) * 3
    if "vault_50" in df.columns:
        cred_pts += (df["vault_50"].fillna("").str.upper() == "TRUE").astype(int) * 2
    if "clerkships" in df.columns:
        cred_pts += (df["clerkships"].fillna("").str.strip() != "").astype(int) * 2
    if "raw_acknowledgements" in df.columns:
        cred_pts += (df["raw_acknowledgements"].fillna("").str.strip() != "").astype(int) * 1
    cred_max = 8 if has_firm else 14
    cred_pts = cred_pts.clip(upper=cred_max)

    # --- Total & tier ---
    if not has_firm:
        pattern_pts = pd.Series(0, index=df.index)
    total_score = kw_pts + pa_pts + pattern_pts + cred_pts

    # Filter: score threshold depends on how many keywords we had to score on
    # With many keywords, require higher match; with few/none, lower threshold
    # since the pre-filtering (location, practice area, grad year) already ensured relevance
    min_score = 20 if len(keywords) >= 3 else (10 if len(keywords) >= 1 else 2)
    mask = total_score >= min_score
    result = df[mask].copy()
    result["match_score"] = total_score[mask]
    result["keyword_score"] = kw_pts[mask]
    result["practice_score"] = pa_pts[mask]
    result["pattern_score"] = pattern_pts[mask]
    result["credential_score"] = cred_pts[mask]
    result["kw_count"] = kw_count[mask]

    # Tier assignment — thresholds adjust when no firm (scores are spread differently)
    tier2_thresh = 40 if has_firm else 35
    tier1_thresh = 65 if has_firm else 55
    result["tier"] = "3"
    result.loc[result["match_score"] >= tier2_thresh, "tier"] = "2"
    result.loc[result["match_score"] >= tier1_thresh, "tier"] = "1"

    # Sort by score descending
    result = result.sort_values("match_score", ascending=False)

    return result


def build_rationale_for_row(row, keywords, firm_patterns):
    """Build rationale and pattern_matches for a single scored row.
    Called only for the final shortlist (top ~25-100 rows), not all 53K."""
    kw_pts = row.get("keyword_score", 0)
    pa_pts = row.get("practice_score", 0)
    pattern_pts_val = row.get("pattern_score", 0)
    cred_pts = row.get("credential_score", 0)

    # Determine which keywords matched
    bio_text = " ".join([
        str(row.get("attorneyBio", "")), str(row.get("summary", "")),
        str(row.get("matters", "")), str(row.get("added_keywords", "")),
        str(row.get("nlp_specialties", "")),
    ]).lower()
    spec_text = " ".join([
        str(row.get("practice_areas", "")), str(row.get("specialty", "")),
    ]).lower()
    combined = bio_text + " " + spec_text
    kw_matches = [kw for kw in keywords if kw.lower() in combined]

    # Pattern matches
    pattern_matches = []
    feeder_schools = set(firm_patterns.get("feeder_schools", []))
    law_school = str(row.get("lawSchool", "")).strip()
    if law_school and law_school in feeder_schools:
        pattern_matches.append(f"Feeder school ({law_school})")

    prior = str(row.get("prior_experience", "")).lower()
    current_firm = str(row.get("firm_name", "")).lower()
    for feeder in firm_patterns.get("feeder_firms", []):
        if feeder.lower() in prior or feeder.lower() in current_firm:
            pattern_matches.append(f"Feeder firm ({feeder})")
            break

    for spec in firm_patterns.get("top_specialties", []):
        if spec.lower() in spec_text:
            pattern_matches.append(f"In-demand specialty ({spec})")
            break

    # Build rationale text
    reasons = []
    if kw_pts >= 35:
        reasons.append("strong contextual match with JD")
    elif kw_pts >= 20:
        reasons.append("good contextual overlap with JD")
    else:
        reasons.append("partial contextual match")
    if pattern_matches:
        reasons.append("; ".join(pattern_matches).lower())
    if pa_pts >= 8:
        reasons.append("practice area closely matches")
    elif pa_pts >= 4:
        reasons.append("related practice area")
    if cred_pts >= 5:
        reasons.append("strong credentials")

    rationale = ". ".join(r.capitalize() for r in reasons) + "." if reasons else ""

    return {
        "keyword_matches": kw_matches,
        "pattern_matches": pattern_matches,
        "rationale": rationale,
    }

# ---------------------------------------------------------------------------
# Hiring pattern analysis
# ---------------------------------------------------------------------------

def analyze_hiring_patterns(firm_name, cities=None, state="", exact_firm=False):
    """Analyze hiring patterns. cities can be a list of city names or a single string.
    If exact_firm=True, look up firm_name exactly in hiring data (no fuzzy matching).
    """
    # Normalize cities to a list
    if isinstance(cities, str):
        cities = [cities] if cities else []
    elif cities is None:
        cities = []

    if HIRING_DF.empty or not firm_name:
        return {"firm_name": firm_name, "matched_firm": None, "cards": [],
                "feeder_schools": [], "feeder_firms": [], "top_specialties": []}

    if exact_firm:
        # Try exact match first, then case-insensitive
        firms = HIRING_DF["Firm"].dropna().unique()
        matched_firm = None
        for f in firms:
            if f == firm_name or f.lower() == firm_name.lower():
                matched_firm = f
                break
        if not matched_firm:
            # Try partial: firm_name is contained in or contains a known firm
            for f in firms:
                if firm_name.lower() in f.lower() or f.lower() in firm_name.lower():
                    matched_firm = f
                    break
        if not matched_firm:
            # Fall back to fuzzy as last resort
            matched_firm, _ = fuzzy_match_firm(firm_name)
    else:
        matched_firm, score = fuzzy_match_firm(firm_name)

    if not matched_firm:
        return {"firm_name": firm_name, "matched_firm": None, "cards": [],
                "feeder_schools": [], "feeder_firms": [], "top_specialties": []}

    firm_hires = HIRING_DF[HIRING_DF["Firm"] == matched_firm].copy()

    if firm_hires.empty:
        return {"firm_name": firm_name, "matched_firm": matched_firm, "cards": [],
                "feeder_schools": [], "feeder_firms": [], "top_specialties": []}

    total = len(firm_hires)
    cards = []

    # Location-specific hires — OR across all cities
    if cities:
        city_mask = pd.Series(False, index=firm_hires.index)
        for c in cities:
            city_mask |= firm_hires["City"].str.lower() == c.lower()
        city_hires = firm_hires[city_mask]
        city_total = len(city_hires)
        loc_label = " — " + " / ".join(c.upper() for c in cities)
    else:
        city_hires = firm_hires
        city_total = total
        loc_label = ""

    # Feeder schools (city-specific)
    schools = city_hires["Law School"].value_counts()
    feeder_schools_list = schools.index.tolist()[:5]
    feeder_schools_data = [{"name": s, "count": int(c)} for s, c in schools.head(5).items()]
    for i, (school, count) in enumerate(schools.head(3).items()):
        pct = round(count / city_total * 100) if city_total else 0
        cards.append({
            "label": f"#{i+1} FEEDER SCHOOL{loc_label}",
            "detail": f"{school} — {count} of {city_total} hires ({pct}%)",
            "description": f"Candidates from {school} have a strong track record of being hired into this office."
        })

    # Feeder firms
    law_firm_hires = city_hires[city_hires["Previous Entity Type"].str.lower() == "law firm"]
    feeder_firms_series = law_firm_hires["Moved From"].value_counts()
    feeder_firms_list = feeder_firms_series.index.tolist()[:5]
    feeder_firms_data = [{"name": f, "count": int(c)} for f, c in feeder_firms_series.head(5).items()]
    for i, (firm, count) in enumerate(feeder_firms_series.head(3).items()):
        pct = round(count / len(law_firm_hires) * 100) if len(law_firm_hires) else 0
        cards.append({
            "label": f"#{i+1} FEEDER FIRM",
            "detail": f"{firm} — {count} lateral hires ({pct}%)",
            "description": f"Attorneys moving from {firm} have been a consistent pipeline."
        })

    # Top specialties
    all_specs = []
    for specs in city_hires["Specialties Old"].dropna():
        all_specs.extend([s.strip() for s in specs.split(",") if s.strip()])
    spec_counts = Counter(all_specs)
    top_specialties_list = [s for s, _ in spec_counts.most_common(5)]
    for i, (spec, count) in enumerate(spec_counts.most_common(2)):
        cards.append({
            "label": f"TOP PRIOR SPECIALTY",
            "detail": f"{spec} — {count} hires had this specialty",
            "description": f"Attorneys with {spec} experience are frequently hired."
        })

    return {
        "firm_name": firm_name,
        "matched_firm": matched_firm,
        "total_hires": total,
        "city_hires": city_total,
        "city": " / ".join(cities) if cities else "",
        "cards": cards,
        "feeder_schools": feeder_schools_list,
        "feeder_firms": feeder_firms_list,
        "top_specialties": top_specialties_list,
        "feeder_schools_chart": feeder_schools_data,
        "feeder_firms_chart": feeder_firms_data,
    }


# ---------------------------------------------------------------------------
# Firm Pitch — data computation
# ---------------------------------------------------------------------------

_FP_PRACTICE_COLS = [
    "Antitrust", "Banking", "Bankruptcy", "Corporate", "Data Privacy",
    "ERISA", "Energy", "Entertainment", "Environmental", "FDA",
    "Government", "Health Care", "Insurance", "Intellectual Property",
    "International Trade", "Labor & Employment", "Litigation", "Media",
    "Real Estate", "Tax", "Telecommunications", "Transportation", "Trusts & Estates",
]


def _compute_firm_pitch_data(firm_name, office=None, practice_group=None, candidate_id=None):
    """Compute all data needed for a firm pitch PDF.

    Returns a dict with hires_by_year, departures_by_year, net_growth,
    feeder_firms, feeder_schools, dest_breakdown, inhouse_destinations,
    team_by_title, firm_meta, candidate (optional), and more.
    """
    result = {}

    # 1. Resolve firm name via fuzzy match
    matched_firm, score = fuzzy_match_firm(firm_name)
    result["matched_firm"] = matched_firm or firm_name
    result["match_score"] = score

    # 2. Look up FIRMS_DF row
    firm_row = {}
    if FIRMS_DF is not None and not FIRMS_DF.empty:
        mask = FIRMS_DF["Name"].fillna("").str.lower() == result["matched_firm"].lower()
        if not mask.any():
            mask = FIRMS_DF["Name"].fillna("").str.lower().str.contains(
                result["matched_firm"].lower(), regex=False)
        matches = FIRMS_DF[mask]
        if not matches.empty:
            firm_row = matches.iloc[0].to_dict()

    total_atty = str(firm_row.get("Total Attorneys", "") or "").replace(".0", "")
    ppp_raw = firm_row.get("PPP", "")
    ppp_str = ""
    if ppp_raw and str(ppp_raw) not in ("", "nan", "None"):
        try:
            ppp_val = float(str(ppp_raw).replace(",", ""))
            ppp_str = f"${ppp_val/1_000_000:.1f}M" if ppp_val >= 1_000_000 else f"${int(ppp_val):,}"
        except Exception:
            ppp_str = str(ppp_raw)

    result["firm_meta"] = {
        "total_attorneys": total_atty,
        "ppp": ppp_str,
        "ppp_raw": str(ppp_raw),
        "partners": str(firm_row.get("Partners", "") or "").replace(".0", ""),
        "counsel": str(firm_row.get("Counsel", "") or "").replace(".0", ""),
        "associates": str(firm_row.get("Associates", "") or "").replace(".0", ""),
        "fp_id": str(firm_row.get("FP ID", "") or ""),
    }

    # Practice areas from boolean columns
    firm_practices = [col for col in _FP_PRACTICE_COLS
                      if str(firm_row.get(col, "")).upper() in ("TRUE", "1", "YES")]
    result["firm_practices"] = firm_practices

    # Offices
    offices_raw = str(firm_row.get("Firm Office Locations", "") or "")
    result["offices"] = [o.strip() for o in offices_raw.split(";") if o.strip()]

    current_year = datetime.now().year
    years = list(range(current_year - 5, current_year + 1))

    # Empty-data defaults
    empty_year_dict = {str(y): 0 for y in years}

    if HIRING_DF is None or HIRING_DF.empty:
        result.update({
            "hires_by_year": empty_year_dict, "feeder_firms": [], "feeder_schools": [],
            "title_dist": {}, "departures_by_year": empty_year_dict, "dest_breakdown": {},
            "inhouse_destinations": [], "inhouse_pct": 0, "lateral_out_pct": 0,
            "govt_pct": 0, "lateral_out_destinations": [], "govt_destinations": [],
            "net_growth": empty_year_dict, "team_size": 0, "team_by_title": {},
            "team_schools": [], "candidate": None,
        })
        return result

    # 3. Hires INTO firm
    hires_df = HIRING_DF[HIRING_DF["Firm"] == result["matched_firm"]].copy()
    if office:
        hires_df = hires_df[hires_df["City"].fillna("").str.lower() == office.lower()]
    if practice_group:
        hires_df = hires_df[
            hires_df["Practice Areas New"].fillna("").str.lower().str.contains(
                practice_group.lower(), regex=False)]

    hires_df["_year"] = pd.to_datetime(hires_df["Move Date"], errors="coerce").dt.year
    hby_s = hires_df["_year"].value_counts()
    result["hires_by_year"] = {str(y): int(hby_s.get(y, 0)) for y in years}

    # Feeder firms (law firm laterals)
    law_lat = hires_df[
        hires_df["Previous Entity Type"].fillna("").str.lower() == "law firm"]
    ff_s = law_lat["Moved From"].value_counts()
    result["feeder_firms"] = [{"name": n, "count": int(c)} for n, c in ff_s.head(10).items()]

    # Feeder schools
    fs_s = hires_df["Law School"].dropna().value_counts()
    result["feeder_schools"] = [{"name": n, "count": int(c)} for n, c in fs_s.head(10).items()]

    # Title distribution
    td_s = hires_df["Title"].value_counts()
    result["title_dist"] = {t: int(c) for t, c in td_s.head(8).items()}

    # 4. Departures FROM firm
    dept_df = HIRING_DF[HIRING_DF["Moved From"] == result["matched_firm"]].copy()
    if practice_group:
        dept_df = dept_df[
            dept_df["Practice Areas Old"].fillna("").str.lower().str.contains(
                practice_group.lower(), regex=False)]

    dept_df["_year"] = pd.to_datetime(dept_df["Move Date"], errors="coerce").dt.year
    dby_s = dept_df["_year"].value_counts()
    result["departures_by_year"] = {str(y): int(dby_s.get(y, 0)) for y in years}

    dest_s = dept_df["Entity Type"].value_counts()
    result["dest_breakdown"] = {t: int(c) for t, c in dest_s.items()}

    total_dept = max(len(dept_df), 1)

    inhouse_mask = dept_df["Entity Type"].fillna("").str.lower().str.contains(
        "company|corporation|in-house|corporate", na=False)
    inhouse_df = dept_df[inhouse_mask]
    result["inhouse_pct"] = round(len(inhouse_df) / total_dept * 100, 1)
    ih_s = inhouse_df["Firm"].value_counts()
    result["inhouse_destinations"] = [{"name": n, "count": int(c)} for n, c in ih_s.head(15).items()]

    lat_out_mask = dept_df["Entity Type"].fillna("").str.lower() == "law firm"
    lat_out_df = dept_df[lat_out_mask]
    result["lateral_out_pct"] = round(len(lat_out_df) / total_dept * 100, 1)
    lo_s = lat_out_df["Firm"].value_counts()
    result["lateral_out_destinations"] = [{"name": n, "count": int(c)} for n, c in lo_s.head(10).items()]

    govt_mask = dept_df["Entity Type"].fillna("").str.lower().str.contains(
        "government|agency|federal|state|city|public", na=False)
    govt_df = dept_df[govt_mask]
    result["govt_pct"] = round(len(govt_df) / total_dept * 100, 1)
    gv_s = govt_df["Firm"].value_counts()
    result["govt_destinations"] = [{"name": n, "count": int(c)} for n, c in gv_s.head(8).items()]

    # 5. Net growth
    result["net_growth"] = {
        str(y): result["hires_by_year"].get(str(y), 0) - result["departures_by_year"].get(str(y), 0)
        for y in years
    }

    # 6. Current team from ATTORNEYS_DF
    result["team_size"] = 0
    result["team_by_title"] = {}
    result["team_schools"] = []
    if ATTORNEYS_DF is not None and not ATTORNEYS_DF.empty:
        team_df = ATTORNEYS_DF[
            ATTORNEYS_DF["firm_name"].fillna("").str.lower() == result["matched_firm"].lower()
        ].copy()
        if office and "location" in team_df.columns:
            team_df = team_df[
                team_df["location"].fillna("").str.lower().str.contains(office.lower(), regex=False)]
        if practice_group and "practice_areas" in team_df.columns:
            team_df = team_df[
                team_df["practice_areas"].fillna("").str.lower().str.contains(
                    practice_group.lower(), regex=False)]
        result["team_size"] = len(team_df)
        if "title" in team_df.columns:
            t2_s = team_df["title"].value_counts()
            result["team_by_title"] = {t: int(c) for t, c in t2_s.head(8).items()}
        school_col = "lawSchool" if "lawSchool" in team_df.columns else "law_school"
        if school_col in team_df.columns:
            sc2_s = team_df[school_col].dropna().value_counts()
            result["team_schools"] = [{"name": n, "count": int(c)} for n, c in sc2_s.head(10).items()]

    # 7. Candidate fit (optional)
    result["candidate"] = None
    if candidate_id is not None and ATTORNEYS_DF is not None and not ATTORNEYS_DF.empty:
        cid_str = str(candidate_id)
        cid_mask = ATTORNEYS_DF["id"].astype(str) == cid_str
        if cid_mask.any():
            cand_row = ATTORNEYS_DF[cid_mask].iloc[0].to_dict()
            cand_data = _serialize_candidate(cand_row)
            cand_school = (cand_data.get("law_school") or "").lower().strip()
            cand_firm_str = (cand_data.get("current_firm") or "").lower().strip()
            school_rank = next(
                (i + 1 for i, s in enumerate(result["feeder_schools"])
                 if s["name"].lower().strip() == cand_school), None)
            firm_rank = next(
                (i + 1 for i, f in enumerate(result["feeder_firms"])
                 if f["name"].lower().strip() == cand_firm_str), None)
            result["candidate"] = {**cand_data, "school_rank": school_rank, "firm_rank": firm_rank}

    return result


# ---------------------------------------------------------------------------
# Claude API integration
# ---------------------------------------------------------------------------

def build_candidate_block(row):
    """Format a single attorney row for the Claude prompt (compact)."""
    fields = {
        "Name": f"{row.get('first_name', '')} {row.get('last_name', '')}",
        "Firm": row.get("firm_name", ""),
        "Title": row.get("title", ""),
        "Year": row.get("graduationYear", ""),
        "School": row.get("lawSchool", ""),
        "Bar": row.get("barAdmissions", ""),
        "Practice": row.get("practice_areas", ""),
        "Specialties": row.get("specialty", ""),
        "Location": row.get("location", ""),
        "Prior": row.get("prior_experience", ""),
        "Clerkships": row.get("clerkships", ""),
        "Accolades": row.get("raw_acknowledgements", ""),
        "Top200/V50/V10": "/".join(filter(None, [
            "Top200" if str(row.get("top_200", "")).upper() == "TRUE" else "",
            "V50" if str(row.get("vault_50", "")).upper() == "TRUE" else "",
            "V10" if str(row.get("vault_10", "")).upper() == "TRUE" else "",
        ])),
    }
    lines = [f"  {k}: {v}" for k, v in fields.items() if v and str(v).strip()]
    bio = str(row.get("attorneyBio", "")).strip()
    if not bio:
        bio = get_attorney_full_bio(row.get("id", ""))
    if bio:
        if len(bio) > BIO_MAX_CHARS:
            bio = bio[:BIO_MAX_CHARS] + "..."
        lines.append(f"  Bio: {bio}")
    return "\n".join(lines)


def build_patterns_summary(patterns):
    """Format hiring pattern data for the Claude prompt."""
    parts = []
    matched = patterns.get("matched_firm", patterns.get("firm_name", "Unknown"))
    parts.append(f"Firm: {matched}")
    parts.append(f"Total hires in dataset: {patterns.get('total_hires', 'N/A')}")
    if patterns.get("city"):
        parts.append(f"Hires in {patterns['city']}: {patterns.get('city_hires', 'N/A')}")
    if patterns.get("feeder_schools"):
        parts.append(f"Top feeder schools: {', '.join(patterns['feeder_schools'])}")
    if patterns.get("feeder_firms"):
        parts.append(f"Top feeder firms: {', '.join(patterns['feeder_firms'])}")
    if patterns.get("top_specialties"):
        parts.append(f"Top prior specialties of hires: {', '.join(patterns['top_specialties'])}")
    if patterns.get("cards"):
        parts.append("\nDetailed pattern cards:")
        for c in patterns["cards"]:
            parts.append(f"  [{c['label']}] {c['detail']} — {c.get('description', '')}")
    return "\n".join(parts)


def _build_claude_prompt(jd_text, patterns, candidate_rows):
    """Build the user prompt for Claude."""
    candidate_blocks = []
    for i, row in enumerate(candidate_rows):
        candidate_blocks.append(f"--- Candidate {i+1} ---\n{build_candidate_block(row)}")

    candidates_text = "\n\n".join(candidate_blocks)
    patterns_text = build_patterns_summary(patterns)

    return f"""## Job Description

{jd_text}

## Firm Hiring Patterns

{patterns_text}

## Candidate Shortlist ({len(candidate_rows)} candidates)

{candidates_text}

Analyze each candidate and return your assessment as the specified JSON structure."""


def call_claude_api(jd_text, patterns, candidate_rows, meta):
    """Send candidates to Claude (non-streaming). Returns parsed JSON or None."""
    if not ANTHROPIC_API_KEY:
        return None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    user_prompt = _build_claude_prompt(jd_text, patterns, candidate_rows)

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8000,
        temperature=0,
        system=CLAUDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print("[Claude API] JSON truncated — attempting repair...")
        return _repair_truncated_json(text)


def stream_claude_api(jd_text, patterns, candidate_rows, meta):
    """Stream Claude response as SSE events. Yields 'data: ...\n\n' strings."""
    if not ANTHROPIC_API_KEY:
        yield f"data: {json.dumps({'type': 'error', 'message': 'No API key configured'})}\n\n"
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    user_prompt = _build_claude_prompt(jd_text, patterns, candidate_rows)

    full_text = ""
    try:
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=8000,
            temperature=0,
            system=CLAUDE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            chunk_buffer = ""
            for text_chunk in stream.text_stream:
                full_text += text_chunk
                chunk_buffer += text_chunk
                # Send progress chunks every ~100 chars to avoid flooding
                if len(chunk_buffer) >= 100:
                    yield f"data: {json.dumps({'type': 'chunk', 'text': chunk_buffer})}\n\n"
                    chunk_buffer = ""
            # Flush remaining buffer
            if chunk_buffer:
                yield f"data: {json.dumps({'type': 'chunk', 'text': chunk_buffer})}\n\n"
    except Exception as e:
        print(f"[Claude streaming error] {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    # Parse the complete response
    text = full_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        try:
            result = _repair_truncated_json(text)
        except (json.JSONDecodeError, ValueError):
            yield f"data: {json.dumps({'type': 'error', 'message': 'Failed to parse AI response'})}\n\n"
            return

    # Send the final parsed result
    yield f"data: {json.dumps({'type': 'done', 'result': result}, cls=NumpyEncoder)}\n\n"


# ---------------------------------------------------------------------------
# Preflight endpoint — lightweight JD parse for firm detection
# ---------------------------------------------------------------------------

@app.route("/api/search/preflight", methods=["POST"])
def search_preflight():
    data = request.get_json()
    jd_text = data.get("jd", "")
    if not jd_text.strip():
        return jsonify({"firm_name": "", "firm_detected": False})
    firm_name = extract_firm_name(jd_text)
    return jsonify({"firm_name": firm_name, "firm_detected": bool(firm_name)})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.before_request
def require_login():
    """Block unauthenticated requests to API routes (except login)."""
    public_paths = {"/", "/api/login"}
    if request.path.startswith("/static/") or request.path in public_paths:
        return None
    if request.path.startswith("/api/") and "user_id" not in session:
        return jsonify({"error": "Not authenticated"}), 401


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    conn = ats_db.get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now().isoformat(), row["id"]),
        )
        conn.commit()
    conn.close()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401
    session["user_id"] = row["id"]
    session["user_email"] = row["email"]
    session["user_name"] = f"{row['first_name']} {row['last_name']}".strip() or row["email"]
    return jsonify({"success": True, "name": session["user_name"]})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Main route
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    import json as _json
    # Pre-render dashboard data server-side so it displays on page load
    # without depending on JavaScript fetches succeeding.
    pipeline_stats = {}
    pipeline_rows = []
    if session.get("user_id"):
        try:
            pipeline_stats = ats_db.get_pipeline_stats()
            pipeline_rows = ats_db.get_pipeline_all()
        except Exception:
            pass
    from flask import make_response
    resp = render_template(
        "index.html",
        pipeline_stats=pipeline_stats,
        pipeline_rows=pipeline_rows,
        pipeline_rows_json=_json.dumps(pipeline_rows),
        pipeline_stats_json=_json.dumps(pipeline_stats),
    )
    r = make_response(resp)
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    return r

def _serialize_candidate(r):
    """Build a candidate dict with all fields needed for profile cards."""
    return _sanitize_for_json({
        "id": r.get("id", ""),
        "rank": r.get("rank", 0),
        "tier": r.get("tier", "") if r.get("tier", "").startswith("Tier") else f"Tier {r.get('tier', '3')}",
        "name": r.get("name") or f"{r.get('first_name', '')} {r.get('last_name', '')}",
        "first_name": r.get("first_name", ""),
        "last_name": r.get("last_name", ""),
        "current_firm": r.get("current_firm") or r.get("firm_name", ""),
        "title": r.get("title", ""),
        "graduation_year": r.get("graduation_year") or r.get("graduationYear", ""),
        "law_school": r.get("law_school") or r.get("lawSchool", ""),
        "bar_admission": r.get("bar_admission") or r.get("barAdmissions", ""),
        "specialties": r.get("specialties") or r.get("specialty", ""),
        "practice_areas": r.get("practice_areas", ""),
        "prior_firms": r.get("prior_firms") or r.get("prior_experience", ""),
        "pattern_matches": ", ".join(r.get("pattern_matches", [])) if isinstance(r.get("pattern_matches"), list) else r.get("pattern_matches", ""),
        "qualifications_summary": r.get("qualifications_summary") or r.get("rationale", ""),
        "match_score": r.get("match_score", 0),
        # Profile card fields
        "photo_url": r.get("photo_url", ""),
        "email": r.get("email", ""),
        "phone_primary": r.get("phone_primary", ""),
        "linkedinURL": r.get("linkedinURL", ""),
        "profileURL": r.get("profileURL", ""),
        "attorneyBio": r.get("attorneyBio", ""),
        "undergraduate": r.get("undergraduate", ""),
        "llm_school": r.get("llm_school", ""),
        "llm_year": r.get("llm_year", ""),
        "llm_specialty": r.get("llm_specialty", ""),
        "clerkships": r.get("clerkships", ""),
        "raw_acknowledgements": r.get("raw_acknowledgements", ""),
        "languages": r.get("languages", ""),
        "location": r.get("location", ""),
        "scraped_on": r.get("scraped_on") or r.get("real_modified", ""),
        "is_boomerang": r.get("is_boomerang", False),
    })


# ---------------------------------------------------------------------------
# Candidate Pitch PDF — scoring, narratives, charts, assembly
# ---------------------------------------------------------------------------

PITCH_SYSTEM_PROMPT = """You are a senior legal recruiter creating a confidential candidate pitch document.
Given a candidate profile, job details, firm hiring DNA, and fit scores, produce a compelling narrative.

Return ONLY valid JSON (no markdown fences) with these keys:
{
  "headline": "One compelling sentence: why this candidate is perfect for the role",
  "job_overview": "2-3 sentences describing the opportunity and what makes it attractive",
  "fit_narrative": "3-4 sentences explaining why this candidate is an excellent match. Reference specific data points — school, firm pedigree, practice area alignment, class year.",
  "career_trajectory_narrative": "2-3 sentences about the candidate's career arc and how it positions them well for this move.",
  "custom_angle_narrative": "2-3 sentences addressing the specific focus angle requested (if any). Leave empty string if no angle provided.",
  "closing_hook": "1-2 sentences — a compelling reason to act now or a unique differentiator.",
  "anonymized_firm_descriptor": "A short descriptor for the candidate's current firm that doesn't reveal the name (e.g. 'Am Law 50 firm', 'Top-tier boutique', 'V10 firm'). Use the firm's actual ranking/reputation."
}

Rules:
- Be specific — use actual data from the profile, not generic language.
- The tone should be professional, confident, and persuasive — like a top recruiter's pitch.
- Never fabricate qualifications or credentials.
- Keep each section concise — this goes into a 1-2 page PDF."""


def _compute_pitch_scores(attorney_row, firm_name, job_data):
    """Compute 6 fit-dimension scores (0-100) for a candidate against a job/firm."""
    dna = HIRING_DNA.get(firm_name, {})
    scores = {}

    # --- school_match ---
    school = str(attorney_row.get("lawSchool") or attorney_row.get("law_school", "")).strip()
    if dna.get("feeder_schools") and school:
        feeder_names = [s["school"].lower() for s in dna["feeder_schools"]]
        sl = school.lower()
        if sl in feeder_names:
            rank = feeder_names.index(sl)
            scores["school_match"] = max(95 - rank * 8, 40)
        else:
            scores["school_match"] = 25
    else:
        scores["school_match"] = 50  # neutral when no data

    # --- firm_pedigree ---
    current_firm = str(attorney_row.get("firm_name") or attorney_row.get("current_firm", "")).strip()
    if dna.get("feeder_firms") and current_firm:
        feeder_firms = [f["firm"].lower() for f in dna["feeder_firms"]]
        cf = current_firm.lower()
        if cf in feeder_firms:
            rank = feeder_firms.index(cf)
            scores["firm_pedigree"] = max(95 - rank * 6, 40)
        else:
            # Check vault/top200 status as fallback
            is_v10 = str(attorney_row.get("vault_10", "")).upper() == "TRUE"
            is_v50 = str(attorney_row.get("vault_50", "")).upper() == "TRUE"
            is_top200 = str(attorney_row.get("top_200", "")).upper() == "TRUE"
            if is_v10:
                scores["firm_pedigree"] = 70
            elif is_v50:
                scores["firm_pedigree"] = 60
            elif is_top200:
                scores["firm_pedigree"] = 50
            else:
                scores["firm_pedigree"] = 30
    else:
        is_v10 = str(attorney_row.get("vault_10", "")).upper() == "TRUE"
        is_v50 = str(attorney_row.get("vault_50", "")).upper() == "TRUE"
        scores["firm_pedigree"] = 70 if is_v10 else (60 if is_v50 else 50)

    # --- practice_fit ---
    job_pa = str(job_data.get("practice_area", "")).lower()
    cand_pa = str(attorney_row.get("practice_areas") or attorney_row.get("practiceArea", "")).lower()
    if job_pa and cand_pa:
        job_terms = set(t.strip() for t in job_pa.replace(";", ",").split(",") if t.strip())
        cand_terms = set(t.strip() for t in cand_pa.replace(";", ",").split(",") if t.strip())
        if job_terms & cand_terms:
            scores["practice_fit"] = 90
        elif any(jt in ct or ct in jt for jt in job_terms for ct in cand_terms):
            scores["practice_fit"] = 70
        else:
            scores["practice_fit"] = 35
    else:
        scores["practice_fit"] = 50

    # --- specialty_align ---
    job_spec = str(job_data.get("specialty", "")).lower()
    cand_spec = str(attorney_row.get("specialty") or attorney_row.get("specialties", "")).lower()
    if job_spec and cand_spec:
        job_sp = set(t.strip() for t in job_spec.replace(";", ",").split(",") if t.strip())
        cand_sp = set(t.strip() for t in cand_spec.replace(";", ",").split(",") if t.strip())
        if job_sp & cand_sp:
            scores["specialty_align"] = 95
        elif any(js in cs or cs in js for js in job_sp for cs in cand_sp):
            scores["specialty_align"] = 70
        else:
            scores["specialty_align"] = 30
    else:
        scores["specialty_align"] = 50

    # --- class_year_fit ---
    cand_year = pd.to_numeric(attorney_row.get("graduationYear") or attorney_row.get("graduation_year"), errors="coerce")
    job_yr_min = pd.to_numeric(job_data.get("graduation_year_min"), errors="coerce")
    job_yr_max = pd.to_numeric(job_data.get("graduation_year_max"), errors="coerce")
    if not pd.isna(cand_year):
        if not pd.isna(job_yr_min) and not pd.isna(job_yr_max):
            if job_yr_min <= cand_year <= job_yr_max:
                scores["class_year_fit"] = 95
            else:
                gap = min(abs(cand_year - job_yr_min), abs(cand_year - job_yr_max))
                scores["class_year_fit"] = max(90 - gap * 15, 10)
        elif dna.get("class_year_range"):
            cyr = dna["class_year_range"]
            if cyr["min"] <= cand_year <= cyr["max"]:
                scores["class_year_fit"] = 85
            else:
                gap = min(abs(cand_year - cyr["min"]), abs(cand_year - cyr["max"]))
                scores["class_year_fit"] = max(80 - gap * 12, 10)
        else:
            scores["class_year_fit"] = 60
    else:
        scores["class_year_fit"] = 40

    # --- location_match ---
    cand_loc = str(attorney_row.get("location", "")).lower()
    job_loc = str(job_data.get("location", "")).lower()
    if cand_loc and job_loc:
        # Simple city/state overlap
        cand_parts = set(t.strip() for t in cand_loc.replace(",", " ").split() if len(t.strip()) > 2)
        job_parts = set(t.strip() for t in job_loc.replace(",", " ").split() if len(t.strip()) > 2)
        if cand_parts & job_parts:
            scores["location_match"] = 90
        else:
            scores["location_match"] = 30
    else:
        scores["location_match"] = 50

    return scores


def _generate_pitch_narratives(attorney_data, job_data, firm_name, dna, scores, focus_angle, anonymize):
    """Call Claude to generate pitch narratives. Returns parsed JSON dict."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build a rich profile block
    profile_lines = []
    name = attorney_data.get("name") or f"{attorney_data.get('first_name', '')} {attorney_data.get('last_name', '')}".strip()
    profile_lines.append(f"Name: {name}")
    profile_lines.append(f"Current Firm: {attorney_data.get('current_firm') or attorney_data.get('firm_name', '')}")
    profile_lines.append(f"Title: {attorney_data.get('title', '')}")
    profile_lines.append(f"Law School: {attorney_data.get('law_school') or attorney_data.get('lawSchool', '')}")
    profile_lines.append(f"Graduation Year: {attorney_data.get('graduation_year') or attorney_data.get('graduationYear', '')}")
    profile_lines.append(f"Bar Admissions: {attorney_data.get('bar_admission') or attorney_data.get('barAdmissions', '')}")
    profile_lines.append(f"Practice Areas: {attorney_data.get('practice_areas') or attorney_data.get('practiceArea', '')}")
    profile_lines.append(f"Specialties: {attorney_data.get('specialties') or attorney_data.get('specialty', '')}")
    profile_lines.append(f"Prior Firms: {attorney_data.get('prior_firms') or attorney_data.get('prior_experience', '')}")
    profile_lines.append(f"Location: {attorney_data.get('location', '')}")
    profile_lines.append(f"Undergraduate: {attorney_data.get('undergraduate', '')}")
    profile_lines.append(f"Clerkships: {attorney_data.get('clerkships', '')}")
    profile_lines.append(f"Languages: {attorney_data.get('languages', '')}")
    bio = attorney_data.get("attorneyBio", "")
    if bio:
        profile_lines.append(f"Bio: {bio[:800]}")
    profile_text = "\n".join(profile_lines)

    # Job details
    job_lines = []
    job_lines.append(f"Job Title: {job_data.get('title', '')}")
    job_lines.append(f"Employer: {job_data.get('employer_name', '') or firm_name}")
    job_lines.append(f"Location: {job_data.get('location', '')}")
    job_lines.append(f"Practice Area: {job_data.get('practice_area', '')}")
    job_lines.append(f"Specialty: {job_data.get('specialty', '')}")
    job_lines.append(f"Class Year Range: {job_data.get('graduation_year_min', '')} - {job_data.get('graduation_year_max', '')}")
    desc = job_data.get("description", "")
    if desc:
        job_lines.append(f"Description: {desc[:600]}")
    job_text = "\n".join(job_lines)

    # DNA summary
    dna_text = "No hiring pattern data available."
    if dna:
        dna_parts = [f"Firm: {dna.get('firm_name', firm_name)}, Total hires: {dna.get('total_hires', 'N/A')}"]
        if dna.get("feeder_schools"):
            schools = [s["school"] for s in dna["feeder_schools"][:5]]
            dna_parts.append(f"Top feeder schools: {', '.join(schools)}")
        if dna.get("feeder_firms"):
            firms = [f["firm"] for f in dna["feeder_firms"][:5]]
            dna_parts.append(f"Top feeder firms: {', '.join(firms)}")
        dna_text = "\n".join(dna_parts)

    scores_text = "\n".join(f"  {k}: {v}/100" for k, v in scores.items())

    focus_line = f"\nFOCUS ANGLE: {focus_angle}" if focus_angle else "\nNo specific focus angle requested — leave custom_angle_narrative as empty string."

    # Vault/ranking info for anonymized descriptor
    vault_info = ""
    is_v10 = str(attorney_data.get("vault_10", "")).upper() == "TRUE"
    is_v50 = str(attorney_data.get("vault_50", "")).upper() == "TRUE"
    is_top200 = str(attorney_data.get("top_200", "")).upper() == "TRUE"
    if is_v10:
        vault_info = "The candidate's current firm is a Vault 10 firm."
    elif is_v50:
        vault_info = "The candidate's current firm is a Vault 50 firm."
    elif is_top200:
        vault_info = "The candidate's current firm is a Top 200 firm."

    user_prompt = f"""## Candidate Profile
{profile_text}
{vault_info}

## Job Opportunity
{job_text}

## Hiring DNA / Firm Patterns
{dna_text}

## Fit Scores
{scores_text}
{focus_line}

Generate the pitch narratives as specified JSON."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            temperature=0,
            system=PITCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return _repair_truncated_json(text)
    except Exception as e:
        print(f"[Pitch narrative error] {e}")
        traceback.print_exc()
        # Return fallback narratives
        return {
            "headline": f"Strong candidate for {job_data.get('title', 'this role')}",
            "job_overview": f"This is an opportunity at {firm_name or 'the firm'} for a {job_data.get('title', 'legal professional')}.",
            "fit_narrative": "This candidate shows strong alignment with the role requirements.",
            "career_trajectory_narrative": "The candidate's career trajectory demonstrates consistent growth.",
            "custom_angle_narrative": "",
            "closing_hook": "This candidate is actively open to new opportunities.",
            "anonymized_firm_descriptor": "prominent law firm",
        }


def _generate_radar_chart(scores):
    """Generate a 6-axis spider/radar chart. Returns BytesIO with PNG."""
    categories = list(scores.keys())
    values = list(scores.values())
    N = len(categories)

    # Close the polygon
    angles = [n / float(N) * 2 * math.pi for n in range(N)]
    values_plot = values + [values[0]]
    angles_plot = angles + [angles[0]]

    fig, ax = plt.subplots(figsize=(3.5, 3.5), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor("white")

    # Draw the radar
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)

    # Labels
    labels = [c.replace("_", " ").title() for c in categories]
    ax.set_xticks(angles)
    ax.set_xticklabels(labels, fontsize=7, fontweight="bold", color="#313131")

    # Y-axis
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=6, color="#B4B4B4")
    ax.yaxis.grid(True, color="#EDEDED", linewidth=0.5)
    ax.xaxis.grid(True, color="#EDEDED", linewidth=0.5)

    # Plot data
    ax.plot(angles_plot, values_plot, "o-", linewidth=2, color="#0059FF", markersize=4)
    ax.fill(angles_plot, values_plot, alpha=0.2, color="#0059FF")

    # Style spines
    ax.spines["polar"].set_color("#e2e8f0")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _generate_feeder_bar_chart(items, candidate_value, title):
    """Generate a horizontal bar chart (top 8 items). Candidate's value highlighted blue.
    items: list of dicts with 'name' and 'count' keys.
    candidate_value: the candidate's value to highlight.
    Returns BytesIO PNG."""
    if not items:
        return None

    top = items[:8]
    names = [it["name"] for it in top]
    counts = [it["count"] for it in top]
    cand_lower = candidate_value.lower().strip() if candidate_value else ""

    colors = []
    for n in names:
        if n.lower().strip() == cand_lower:
            colors.append("#0059FF")
        else:
            colors.append("#B4B4B4")

    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    fig.patch.set_facecolor("white")
    y_pos = range(len(names) - 1, -1, -1)
    ax.barh(list(y_pos), counts, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(names, fontsize=7, color="#313131")
    ax.set_xlabel("Hires", fontsize=7, color="#696969")
    ax.set_title(title, fontsize=9, fontweight="bold", color="#151515", pad=8)
    ax.tick_params(axis="x", labelsize=7, colors="#696969")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _generate_career_trajectory_chart(firm_name):
    """Generate chart showing where attorneys from this firm moved to. Returns BytesIO or None."""
    if HIRING_DF.empty:
        return None
    # Find attorneys who moved FROM this firm
    moved = HIRING_DF[HIRING_DF["Moved From"].str.lower() == firm_name.lower()]
    if len(moved) < 5:
        return None
    dest_counts = moved["Firm"].value_counts().head(8)
    if dest_counts.empty:
        return None

    names = dest_counts.index.tolist()
    counts = dest_counts.values.tolist()

    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    fig.patch.set_facecolor("white")
    y_pos = range(len(names) - 1, -1, -1)
    ax.barh(list(y_pos), counts, color="#0059FF", height=0.6, edgecolor="none", alpha=0.8)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(names, fontsize=7, color="#313131")
    ax.set_xlabel("Lateral Moves", fontsize=7, color="#696969")
    ax.set_title(f"Where {firm_name} Alumni Go", fontsize=9, fontweight="bold", color="#151515", pad=8)
    ax.tick_params(axis="x", labelsize=7, colors="#696969")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Firm Pitch — chart generators
# ---------------------------------------------------------------------------

def _gen_fp_hiring_trend_chart(hires_by_year, firm_name):
    """Vertical bar: lateral hiring activity last 6 years. Returns BytesIO or None."""
    if not hires_by_year:
        return None
    years = sorted(hires_by_year.keys())
    counts = [hires_by_year[y] for y in years]
    if sum(counts) == 0:
        return None

    fig, ax = plt.subplots(figsize=(4, 2.5))
    fig.patch.set_facecolor("white")
    x = list(range(len(years)))
    bars = ax.bar(x, counts, color="#0059FF", width=0.6, edgecolor="none")
    for bar, val in zip(bars, counts):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15,
                    str(val), ha="center", va="bottom", fontsize=7, color="#151515")
    ax.set_xticks(x)
    ax.set_xticklabels([str(y)[-2:] for y in years], fontsize=7, color="#696969")
    ax.set_title(f"Lateral Hiring — {firm_name[:30]}", fontsize=9,
                 fontweight="bold", color="#151515", pad=8)
    ax.tick_params(axis="y", labelsize=7, colors="#696969")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _gen_fp_net_growth_chart(net_growth, firm_name):
    """Vertical bar: net attorney growth. Positive=green, negative=red. Returns BytesIO or None."""
    if not net_growth:
        return None
    years = sorted(net_growth.keys())
    counts = [net_growth[y] for y in years]
    if all(c == 0 for c in counts):
        return None

    colors = ["#22c55e" if c >= 0 else "#ef4444" for c in counts]
    fig, ax = plt.subplots(figsize=(4, 2.5))
    fig.patch.set_facecolor("white")
    x = list(range(len(years)))
    ax.bar(x, counts, color=colors, width=0.6, edgecolor="none")
    ax.axhline(0, color="#e2e8f0", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([str(y)[-2:] for y in years], fontsize=7, color="#696969")
    ax.set_title(f"Net Growth — {firm_name[:30]}", fontsize=9,
                 fontweight="bold", color="#151515", pad=8)
    ax.tick_params(axis="y", labelsize=7, colors="#696969")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _gen_fp_exit_breakdown_chart(dest_breakdown, firm_name):
    """Horizontal bar: exit destination types colored by category. Returns BytesIO or None."""
    if not dest_breakdown:
        return None
    items = sorted(dest_breakdown.items(), key=lambda x: x[1], reverse=True)[:10]
    if not items:
        return None
    names = [i[0] for i in items]
    counts = [i[1] for i in items]
    colors = []
    for n in names:
        nl = n.lower()
        if "law" in nl:
            colors.append("#0059FF")
        elif any(k in nl for k in ("company", "in-house", "corporation", "corporate")):
            colors.append("#22c55e")
        elif any(k in nl for k in ("government", "agency", "federal", "public")):
            colors.append("#F59E0B")
        else:
            colors.append("#B4B4B4")

    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    fig.patch.set_facecolor("white")
    y_pos = list(range(len(names) - 1, -1, -1))
    ax.barh(y_pos, counts, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=7, color="#313131")
    ax.set_title(f"Career Paths After {firm_name[:25]}", fontsize=9,
                 fontweight="bold", color="#151515", pad=8)
    ax.tick_params(axis="x", labelsize=7, colors="#696969")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _gen_fp_inhouse_destinations_chart(inhouse_destinations, firm_name):
    """Horizontal bar: top in-house destinations. Returns None if <5 entries."""
    if not inhouse_destinations or len(inhouse_destinations) < 5:
        return None
    top = inhouse_destinations[:12]
    names = [i["name"] for i in top]
    counts = [i["count"] for i in top]

    fig, ax = plt.subplots(figsize=(4, 3))
    fig.patch.set_facecolor("white")
    y_pos = list(range(len(names) - 1, -1, -1))
    ax.barh(y_pos, counts, color="#0059FF", height=0.6, edgecolor="none", alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=7, color="#313131")
    ax.set_title(f"Top In-House Destinations from {firm_name[:22]}", fontsize=9,
                 fontweight="bold", color="#151515", pad=8)
    ax.tick_params(axis="x", labelsize=7, colors="#696969")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _gen_fp_team_seniority_chart(team_by_title, label):
    """Horizontal bar: team seniority breakdown. Returns BytesIO or None."""
    if not team_by_title:
        return None
    items = list(team_by_title.items())[:8]
    names = [i[0] for i in items]
    counts = [i[1] for i in items]

    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    fig.patch.set_facecolor("white")
    y_pos = list(range(len(names) - 1, -1, -1))
    ax.barh(y_pos, counts, color="#0059FF", height=0.6, edgecolor="none", alpha=0.8)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=7, color="#313131")
    ax.set_title(label, fontsize=9, fontweight="bold", color="#151515", pad=8)
    ax.tick_params(axis="x", labelsize=7, colors="#696969")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _assemble_pitch_pdf(narratives, scores, chart_buffers, attorney_data, job_data,
                        firm_data, dna, sections, anonymize, recruiter_info):
    """Assemble a polished PDF pitch document. Returns BytesIO."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch)

    styles = getSampleStyleSheet()
    PRIMARY = HexColor("#0059FF")
    DARK = HexColor("#151515")
    GRAY = HexColor("#696969")
    LIGHT_BG = HexColor("#F6F6F6")

    style_headline = ParagraphStyle("Headline", parent=styles["Heading1"],
                                     fontSize=16, leading=20, textColor=DARK,
                                     spaceAfter=6)
    style_subhead = ParagraphStyle("Subhead", parent=styles["Heading2"],
                                    fontSize=12, leading=15, textColor=DARK,
                                    spaceBefore=10, spaceAfter=4)
    style_body = ParagraphStyle("PitchBody", parent=styles["Normal"],
                                 fontSize=9.5, leading=13, textColor=HexColor("#313131"),
                                 spaceAfter=6)
    style_small = ParagraphStyle("Small", parent=styles["Normal"],
                                  fontSize=8, leading=10, textColor=GRAY)
    style_label = ParagraphStyle("Label", parent=styles["Normal"],
                                  fontSize=8, leading=10, textColor=GRAY,
                                  fontName="Helvetica-Bold")
    style_detail = ParagraphStyle("Detail", parent=styles["Normal"],
                                   fontSize=9, leading=12, textColor=DARK)
    style_footer = ParagraphStyle("Footer", parent=styles["Normal"],
                                   fontSize=8, leading=10, textColor=GRAY,
                                   alignment=TA_CENTER)

    elements = []

    # Candidate name handling
    cand_name = attorney_data.get("name") or f"{attorney_data.get('first_name', '')} {attorney_data.get('last_name', '')}".strip()
    cand_firm = attorney_data.get("current_firm") or attorney_data.get("firm_name", "")
    if anonymize:
        cand_name = "Candidate"
        cand_firm = narratives.get("anonymized_firm_descriptor", "Prominent Firm")

    # ========== HEADER BAR ==========
    header_items = []

    # Logo (if uploaded)
    logo_path = os.path.join(DATA_DIR, "recruiter_logo.png")
    if os.path.exists(logo_path):
        try:
            logo_img = RLImage(logo_path, width=1.0 * inch, height=0.5 * inch)
            logo_img.hAlign = "LEFT"
            header_items.append(logo_img)
        except Exception:
            pass

    conf_text = Paragraph('<font color="#B4B4B4" size="8">CONFIDENTIAL</font>', styles["Normal"])
    header_data = [[conf_text, Paragraph(f'<font color="#B4B4B4" size="8">{datetime.now().strftime("%B %d, %Y")}</font>',
                    ParagraphStyle("RightSmall", parent=styles["Normal"], alignment=TA_RIGHT))]]
    header_table = Table(header_data, colWidths=[3.5 * inch, 3.5 * inch])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK),
        ("TEXTCOLOR", (0, 0), (-1, -1), white),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, 0), 12),
        ("RIGHTPADDING", (-1, -1), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 12))

    # ========== HEADLINE ==========
    headline = narratives.get("headline", "Candidate Overview")
    elements.append(Paragraph(headline, style_headline))
    elements.append(Spacer(1, 4))

    # ========== CANDIDATE + JOB SUMMARY BOX ==========
    job_title = job_data.get("title", "")
    employer = job_data.get("employer_name", "") or firm_data.get("Name", "")
    job_loc = job_data.get("location", "")
    cand_school = attorney_data.get("law_school") or attorney_data.get("lawSchool", "")
    cand_year = attorney_data.get("graduation_year") or attorney_data.get("graduationYear", "")

    left_col = []
    left_col.append(Paragraph(f'<b>{cand_name}</b>', style_detail))
    left_col.append(Paragraph(f'{cand_firm}', style_small))
    if cand_school:
        left_col.append(Paragraph(f'{cand_school}{" " + str(cand_year) if cand_year else ""}', style_small))

    right_col = []
    right_col.append(Paragraph(f'<b>{job_title}</b>', style_detail))
    if employer:
        right_col.append(Paragraph(f'{employer}', style_small))
    if job_loc:
        right_col.append(Paragraph(f'{job_loc}', style_small))

    info_data = [[left_col, right_col]]
    info_table = Table(info_data, colWidths=[3.5 * inch, 3.5 * inch])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor("#EDEDED")),
        ("LINEABOVE", (0, 0), (-1, -1), 0.5, HexColor("#EDEDED")),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 10))

    # ========== JOB OVERVIEW ==========
    if sections.get("job_overview", True):
        overview = narratives.get("job_overview", "")
        if overview:
            elements.append(Paragraph("The Opportunity", style_subhead))
            elements.append(Paragraph(overview, style_body))

    # ========== FIT NARRATIVE + RADAR CHART (side by side) ==========
    if sections.get("fit_narrative", True):
        elements.append(Paragraph("Why This Candidate", style_subhead))
        fit_text = narratives.get("fit_narrative", "")

        radar_buf = chart_buffers.get("radar")
        if fit_text and radar_buf:
            radar_buf.seek(0)
            radar_img = RLImage(radar_buf, width=2.5 * inch, height=2.5 * inch)
            fit_para = Paragraph(fit_text, style_body)
            fit_data = [[fit_para, radar_img]]
            fit_table = Table(fit_data, colWidths=[4.0 * inch, 3.0 * inch])
            fit_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (-1, -1), (-1, -1), 0),
            ]))
            elements.append(fit_table)
        elif fit_text:
            elements.append(Paragraph(fit_text, style_body))

    # ========== FEEDER CHARTS (side by side) ==========
    if sections.get("feeder_charts", True):
        school_buf = chart_buffers.get("feeder_schools")
        firm_buf = chart_buffers.get("feeder_firms")
        chart_cells = []
        if school_buf:
            school_buf.seek(0)
            chart_cells.append(RLImage(school_buf, width=3.3 * inch, height=2.2 * inch))
        if firm_buf:
            firm_buf.seek(0)
            chart_cells.append(RLImage(firm_buf, width=3.3 * inch, height=2.2 * inch))
        if chart_cells:
            if len(chart_cells) == 1:
                chart_cells.append("")
            chart_table = Table([chart_cells], colWidths=[3.5 * inch, 3.5 * inch])
            chart_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            elements.append(Spacer(1, 6))
            elements.append(chart_table)

    # ========== CAREER TRAJECTORY ==========
    if sections.get("career_trajectory", True):
        traj_text = narratives.get("career_trajectory_narrative", "")
        traj_chart = chart_buffers.get("career_trajectory")
        if traj_text or traj_chart:
            elements.append(Spacer(1, 8))
            elements.append(Paragraph("Career Trajectory", style_subhead))
            if traj_text:
                elements.append(Paragraph(traj_text, style_body))
            if traj_chart:
                traj_chart.seek(0)
                elements.append(RLImage(traj_chart, width=4.5 * inch, height=2.0 * inch))

    # ========== CUSTOM ANGLE ==========
    if sections.get("custom_angle", True):
        angle_text = narratives.get("custom_angle_narrative", "")
        if angle_text:
            elements.append(Spacer(1, 8))
            elements.append(Paragraph("Additional Perspective", style_subhead))
            elements.append(Paragraph(angle_text, style_body))

    # ========== CLOSING HOOK ==========
    if sections.get("closing_hook", True):
        hook = narratives.get("closing_hook", "")
        if hook:
            elements.append(Spacer(1, 10))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#EDEDED")))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(f'<i>{hook}</i>', ParagraphStyle(
                "Hook", parent=style_body, fontSize=10, textColor=DARK)))

    # ========== RECRUITER FOOTER ==========
    elements.append(Spacer(1, 16))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#EDEDED")))
    footer_parts = []
    if recruiter_info.get("name"):
        footer_parts.append(f'<b>{recruiter_info["name"]}</b>')
    if recruiter_info.get("title"):
        footer_parts.append(recruiter_info["title"])
    if recruiter_info.get("contact"):
        footer_parts.append(recruiter_info["contact"])
    if footer_parts:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(" | ".join(footer_parts), style_footer))

    # Build PDF
    doc.build(elements)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Firm Pitch — Claude narrative generation
# ---------------------------------------------------------------------------

FIRM_PITCH_SYSTEM_PROMPT = """\
You are JAIDE, an expert legal recruiting strategist. You write polished, data-driven firm pitch \
documents that recruiters use to present a law firm to a candidate.

You will receive structured data about a law firm — hiring trends, exit patterns, team composition, \
feeder schools and firms, and optionally a candidate profile.

Return ONLY a valid JSON object with these exact keys:
{
  "headline": "A compelling 1-line headline pitching the firm (max 80 chars)",
  "executive_pitch": "2-3 paragraphs: why this firm is a compelling move. Data-driven but written like a polished recruiter memo.",
  "growth_narrative": "1-2 paragraphs on the firm's growth story using hiring trend and net growth data.",
  "team_narrative": "1-2 paragraphs on the team the candidate would join — size, seniority, schools.",
  "career_paths_narrative": "2-3 paragraphs on what this firm does for a career. Reference exit data — in-house rates, top destinations, lateral moves.",
  "candidate_fit_narrative": "2-3 paragraphs personalizing the pitch to the specific candidate using their school, current firm, practice area, and graduation year. If no candidate data, write a compelling generic 'ideal candidate' profile.",
  "custom_section_title": "Title for the custom section (empty string if no custom prompt provided)",
  "custom_section_narrative": "Response to the custom prompt if provided, otherwise empty string",
  "closing": "1-2 sentence punchy close that creates urgency or frames the opportunity"
}

Write in a professional but engaging tone. Use specific data. All text is ready to drop into a PDF.\
"""


def _generate_firm_pitch_narratives(data, custom_prompt, tone, anonymize):
    """Call Claude to generate firm pitch narratives. Returns parsed JSON dict."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    matched_firm = data.get("matched_firm", "")
    meta = data.get("firm_meta", {})

    lines = []
    lines.append(f"FIRM: {matched_firm}")
    lines.append(f"Total Attorneys: {meta.get('total_attorneys', 'N/A')}")
    lines.append(f"PPP: {meta.get('ppp', 'N/A')}")
    lines.append(
        f"Partners: {meta.get('partners', 'N/A')} | "
        f"Counsel: {meta.get('counsel', 'N/A')} | "
        f"Associates: {meta.get('associates', 'N/A')}"
    )
    offices = data.get("offices", [])
    lines.append(f"Offices ({len(offices)}): {', '.join(offices[:8])}")
    practices = data.get("firm_practices", [])
    lines.append(f"Practice Areas: {', '.join(practices[:10])}")

    lines.append("")
    lines.append("HIRING TREND (laterals INTO firm by year):")
    for y, c in sorted(data.get("hires_by_year", {}).items()):
        lines.append(f"  {y}: {c} hires")

    lines.append("")
    lines.append("NET GROWTH (hires minus departures by year):")
    for y, c in sorted(data.get("net_growth", {}).items()):
        lines.append(f"  {y}: {c:+d}")

    lines.append("")
    lines.append("EXIT BREAKDOWN (where attorneys go after this firm):")
    for t, c in sorted(data.get("dest_breakdown", {}).items(), key=lambda x: x[1], reverse=True)[:8]:
        lines.append(f"  {t}: {c}")
    lines.append(f"  In-house rate: {data.get('inhouse_pct', 0)}%")
    lines.append(f"  Lateral-out rate: {data.get('lateral_out_pct', 0)}%")
    lines.append(f"  Government rate: {data.get('govt_pct', 0)}%")
    top_ih = data.get("inhouse_destinations", [])[:5]
    if top_ih:
        lines.append(f"  Top in-house: {', '.join(d['name'] for d in top_ih)}")

    lines.append("")
    lines.append("TOP FEEDER FIRMS (law firm laterals INTO this firm):")
    for f in data.get("feeder_firms", [])[:5]:
        lines.append(f"  {f['name']}: {f['count']} hires")

    lines.append("")
    lines.append("TOP FEEDER SCHOOLS:")
    for s in data.get("feeder_schools", [])[:5]:
        lines.append(f"  {s['name']}: {s['count']} hires")

    team_by_title = data.get("team_by_title", {})
    if team_by_title:
        lines.append("")
        lines.append(f"CURRENT TEAM ({data.get('team_size', 0)} attorneys in DB):")
        for t, c in list(team_by_title.items())[:5]:
            lines.append(f"  {t}: {c}")

    cand = data.get("candidate")
    if cand:
        lines.append("")
        lines.append("CANDIDATE PROFILE:")
        lines.append(f"  Name: {cand.get('name', '')}")
        lines.append(f"  Current Firm: {cand.get('current_firm', '')}")
        lines.append(f"  Title: {cand.get('title', '')}")
        lines.append(f"  Law School: {cand.get('law_school', '')}")
        lines.append(f"  Graduation Year: {cand.get('graduation_year', '')}")
        lines.append(f"  Practice Areas: {cand.get('practice_areas', '')}")
        lines.append(f"  School Rank in Feeder List: #{cand.get('school_rank', 'N/A')}")
        lines.append(f"  Current Firm Rank in Feeder List: #{cand.get('firm_rank', 'N/A')}")
        if anonymize:
            lines.append(
                "  NOTE: Do not use the candidate's name or current firm name in "
                "candidate_fit_narrative — refer to them generically."
            )

    if custom_prompt:
        lines.append("")
        lines.append(f"CUSTOM SECTION REQUEST: {custom_prompt}")

    tone_line = f"\nTONE: {tone}" if tone and tone != "professional" else ""
    user_prompt = "\n".join(lines) + tone_line + "\n\nGenerate the firm pitch narratives as the specified JSON."

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            temperature=0,
            system=FIRM_PITCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return _repair_truncated_json(text)
    except Exception as e:
        print(f"[Firm pitch narrative error] {e}")
        traceback.print_exc()
        return {
            "headline": f"{matched_firm} — A Platform for Your Next Chapter",
            "executive_pitch": f"{matched_firm} is a leading firm with strong lateral hiring momentum.",
            "growth_narrative": "The firm has demonstrated consistent growth over recent years.",
            "team_narrative": "The team offers a collaborative environment for senior legal professionals.",
            "career_paths_narrative": "Alumni pursue diverse paths including in-house roles, government, and lateral moves.",
            "candidate_fit_narrative": "Based on your background, this firm represents an excellent fit.",
            "custom_section_title": "",
            "custom_section_narrative": "",
            "closing": "This is an opportunity worth serious consideration.",
        }


# ---------------------------------------------------------------------------
# Firm Pitch — PDF assembly
# ---------------------------------------------------------------------------

def _assemble_firm_pitch_pdf(narratives, data, recruiter_info, anonymize):
    """Assemble the firm pitch PDF. Returns BytesIO."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch)

    styles = getSampleStyleSheet()
    PRIMARY = HexColor("#0059FF")
    DARK = HexColor("#151515")
    GRAY = HexColor("#696969")
    LIGHT_BG = HexColor("#E0F1FF")

    style_headline = ParagraphStyle("FPHeadline", parent=styles["Heading1"],
                                    fontSize=16, leading=20, textColor=DARK, spaceAfter=6)
    style_body = ParagraphStyle("FPBody", parent=styles["Normal"],
                                fontSize=9.5, leading=13, textColor=HexColor("#313131"), spaceAfter=6)
    style_small = ParagraphStyle("FPSmall", parent=styles["Normal"],
                                 fontSize=8, leading=10, textColor=GRAY)
    style_footer = ParagraphStyle("FPFooter", parent=styles["Normal"],
                                  fontSize=8, leading=10, textColor=GRAY, alignment=TA_CENTER)
    style_metric_label = ParagraphStyle("FPMLabel", parent=styles["Normal"],
                                        fontSize=7, leading=9, textColor=GRAY, alignment=TA_CENTER)
    style_metric_value = ParagraphStyle("FPMVal", parent=styles["Normal"],
                                        fontSize=14, leading=16, textColor=PRIMARY,
                                        fontName="Helvetica-Bold", alignment=TA_CENTER)
    style_pill = ParagraphStyle("FPPill", parent=styles["Normal"],
                                fontSize=8, leading=12, textColor=PRIMARY)

    matched_firm = data.get("matched_firm", "")
    meta = data.get("firm_meta", {})

    def _section_header(title):
        p = Paragraph(
            f"<b>{title}</b>",
            ParagraphStyle("FPSH", parent=styles["Normal"], fontSize=9, leading=11,
                           textColor=white, fontName="Helvetica-Bold")
        )
        t = Table([[p]], colWidths=[7.0 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PRIMARY),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        return t

    def _header_bar():
        conf_text = Paragraph('<font color="#B4B4B4" size="8">CONFIDENTIAL</font>', styles["Normal"])
        date_text = Paragraph(
            f'<font color="#B4B4B4" size="8">{datetime.now().strftime("%B %d, %Y")}</font>',
            ParagraphStyle("FPRight", parent=styles["Normal"], alignment=TA_RIGHT)
        )
        ht = Table([[conf_text, date_text]], colWidths=[3.5 * inch, 3.5 * inch])
        ht.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), DARK),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (0, 0), 12),
            ("RIGHTPADDING", (-1, -1), (-1, -1), 12),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return ht

    def _side_by_side_charts(buf1, buf2, w=3.3, h=2.2):
        cells = []
        if buf1:
            buf1.seek(0)
            cells.append(RLImage(buf1, width=w * inch, height=h * inch))
        if buf2:
            buf2.seek(0)
            cells.append(RLImage(buf2, width=w * inch, height=h * inch))
        if not cells:
            return None
        while len(cells) < 2:
            cells.append("")
        ct = Table([cells], colWidths=[3.5 * inch, 3.5 * inch])
        ct.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        return ct

    elements = []
    charts = data.get("_charts", {})

    # ══════════════ PAGE 1 ══════════════
    elements.append(_header_bar())
    elements.append(Spacer(1, 12))

    # Headline
    headline = narratives.get("headline", f"{matched_firm} — Career Opportunity Overview")
    elements.append(Paragraph(headline, style_headline))
    elements.append(Spacer(1, 4))

    # The Opportunity
    elements.append(_section_header("THE OPPORTUNITY"))
    elements.append(Spacer(1, 4))
    exec_pitch = narratives.get("executive_pitch", "")
    if exec_pitch:
        elements.append(Paragraph(exec_pitch, style_body))

    # Firm Snapshot metrics
    elements.append(Spacer(1, 8))
    offices = data.get("offices", [])
    m1 = [Paragraph("ATTORNEYS", style_metric_label),
          Paragraph(str(meta.get("total_attorneys", "—")), style_metric_value)]
    m2 = [Paragraph("PPP", style_metric_label),
          Paragraph(str(meta.get("ppp", "—")), style_metric_value)]
    m3 = [Paragraph("OFFICES", style_metric_label),
          Paragraph(str(len(offices)), style_metric_value)]
    snap = Table([[m1, m2, m3]], colWidths=[2.33 * inch, 2.33 * inch, 2.33 * inch])
    snap.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEAFTER", (0, 0), (1, -1), 0.5, HexColor("#B4D4FF")),
    ]))
    elements.append(snap)

    practices = data.get("firm_practices", [])
    if practices:
        elements.append(Spacer(1, 6))
        pills_text = "  ".join(
            f'<font color="#0059FF">[{p}]</font>' for p in practices[:12])
        elements.append(Paragraph(pills_text, style_pill))

    # Growth Story
    elements.append(Spacer(1, 10))
    elements.append(_section_header("GROWTH STORY"))
    elements.append(Spacer(1, 4))
    growth_nar = narratives.get("growth_narrative", "")
    if growth_nar:
        elements.append(Paragraph(growth_nar, style_body))

    growth_ct = _side_by_side_charts(charts.get("hiring_trend"), charts.get("net_growth"))
    if growth_ct:
        elements.append(Spacer(1, 4))
        elements.append(growth_ct)

    # ══════════════ PAGE 2 ══════════════
    elements.append(PageBreak())
    elements.append(_header_bar())
    elements.append(Spacer(1, 12))

    # Your Fit
    elements.append(_section_header("YOUR FIT"))
    elements.append(Spacer(1, 4))
    fit_nar = narratives.get("candidate_fit_narrative", "")
    if fit_nar:
        elements.append(Paragraph(fit_nar, style_body))

    feeder_ct = _side_by_side_charts(charts.get("feeder_schools"), charts.get("feeder_firms"))
    if feeder_ct:
        elements.append(Spacer(1, 6))
        elements.append(feeder_ct)

    # The Team You'd Join
    elements.append(Spacer(1, 8))
    elements.append(_section_header("THE TEAM YOU'D JOIN"))
    elements.append(Spacer(1, 4))
    team_nar = narratives.get("team_narrative", "")
    if team_nar:
        elements.append(Paragraph(team_nar, style_body))
    team_chart = charts.get("team_seniority")
    if team_chart:
        team_chart.seek(0)
        elements.append(RLImage(team_chart, width=4.5 * inch, height=2.2 * inch))

    # Career Paths & Exit Opportunities
    elements.append(Spacer(1, 8))
    elements.append(_section_header("CAREER PATHS & EXIT OPPORTUNITIES"))
    elements.append(Spacer(1, 4))
    paths_nar = narratives.get("career_paths_narrative", "")
    if paths_nar:
        elements.append(Paragraph(paths_nar, style_body))

    exit_ct = _side_by_side_charts(charts.get("exit_breakdown"), charts.get("inhouse_destinations"),
                                   w=3.3, h=2.2)
    if exit_ct:
        elements.append(exit_ct)

    # ══════════════ PAGE 3 (custom section only if present) ══════════════
    custom_title = narratives.get("custom_section_title", "")
    custom_nar = narratives.get("custom_section_narrative", "")
    if custom_nar:
        elements.append(PageBreak())
        elements.append(_header_bar())
        elements.append(Spacer(1, 12))
        elements.append(_section_header(custom_title or "Additional Insights"))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(custom_nar, style_body))

    # Closing
    closing = narratives.get("closing", "")
    if closing:
        elements.append(Spacer(1, 14))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#EDEDED")))
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(
            f"<i>{closing}</i>",
            ParagraphStyle("FPHook", parent=style_body, fontSize=10, textColor=DARK)
        ))

    # Recruiter footer
    elements.append(Spacer(1, 16))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#EDEDED")))
    footer_parts = []
    if recruiter_info.get("name"):
        footer_parts.append(f'<b>{recruiter_info["name"]}</b>')
    if recruiter_info.get("title"):
        footer_parts.append(recruiter_info["title"])
    if recruiter_info.get("contact"):
        footer_parts.append(recruiter_info["contact"])
    if footer_parts:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(" | ".join(footer_parts), style_footer))

    doc.build(elements)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Pitch API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/pitch/logo", methods=["POST"])
def upload_pitch_logo():
    """Upload recruiter logo for pitch PDFs."""
    if "logo" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["logo"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    save_path = os.path.join(DATA_DIR, "recruiter_logo.png")
    f.save(save_path)
    return jsonify({"ok": True, "path": save_path})


@app.route("/api/pitch/generate", methods=["POST"])
def generate_pitch_pdf():
    """Generate a candidate pitch PDF."""
    try:
        data = request.get_json()
        attorney_id = str(data.get("attorney_id", ""))
        job_id = data.get("job_id")
        job_source = data.get("job_source", "ats")  # "ats" or "csv"
        anonymize = data.get("anonymize", True)
        focus_angle = data.get("focus_angle", "")
        sections = data.get("sections", {
            "job_overview": True, "fit_narrative": True, "feeder_charts": True,
            "career_trajectory": True, "custom_angle": True, "closing_hook": True,
        })
        recruiter_info = {
            "name": data.get("recruiter_name", ""),
            "title": data.get("recruiter_title", ""),
            "contact": data.get("recruiter_contact", ""),
        }
        pipeline_id = data.get("pipeline_id")

        # 1. Load attorney
        if ATTORNEYS_DF.empty:
            return jsonify({"error": "No attorney data loaded"}), 500
        match = ATTORNEYS_DF[ATTORNEYS_DF["id"].astype(str) == attorney_id]
        if match.empty:
            return jsonify({"error": "Attorney not found"}), 404
        attorney_row = match.iloc[0]
        att_dict = attorney_row.to_dict()
        att_dict["attorneyBio"] = get_attorney_full_bio(att_dict.get("id", ""))
        attorney_data = _serialize_candidate(att_dict)

        # 2. Load job
        job_data = {}
        firm_name = ""
        firm_data = {}
        if job_source == "ats" and job_id:
            job = ats_db.get_job(int(job_id))
            if job:
                job_data = dict(job)
                # Get employer name
                emp = ats_db.get_employer(job["employer_id"]) if job.get("employer_id") else None
                if emp:
                    job_data["employer_name"] = emp["name"]
                    firm_name = emp["name"]
                    # Find firm data
                    if not FIRMS_DF.empty:
                        fm = FIRMS_DF[FIRMS_DF["Name"].str.lower() == firm_name.lower()]
                        if not fm.empty:
                            firm_data = fm.iloc[0].to_dict()
        elif job_source == "csv" and job_id is not None:
            idx = int(job_id)
            if not JOBS_DF.empty and idx < len(JOBS_DF):
                row = JOBS_DF.iloc[idx]
                job_data = row.to_dict()
                firm_name = job_data.get("firm_name", "") or job_data.get("company", "")

        # 3. Resolve firm DNA
        dna = HIRING_DNA.get(firm_name, {})

        # 4. Compute scores
        scores = _compute_pitch_scores(attorney_row, firm_name, job_data)

        # 5. Generate narratives
        if not ANTHROPIC_API_KEY:
            return jsonify({"error": "AI not configured (no API key)"}), 500
        narratives = _generate_pitch_narratives(attorney_data, job_data, firm_name, dna, scores, focus_angle, anonymize)

        # 6. Generate charts
        chart_buffers = {}
        chart_buffers["radar"] = _generate_radar_chart(scores)

        cand_school = str(attorney_row.get("lawSchool") or attorney_row.get("law_school", ""))
        if dna.get("feeder_schools"):
            items = [{"name": s["school"], "count": s["hires"]} for s in dna["feeder_schools"][:8]]
            chart_buffers["feeder_schools"] = _generate_feeder_bar_chart(items, cand_school, "Feeder Schools")

        cand_firm_name = str(attorney_row.get("firm_name") or attorney_row.get("current_firm", ""))
        if dna.get("feeder_firms"):
            items = [{"name": f["firm"], "count": f["hires"]} for f in dna["feeder_firms"][:8]]
            chart_buffers["feeder_firms"] = _generate_feeder_bar_chart(items, cand_firm_name, "Feeder Firms")

        if cand_firm_name:
            traj = _generate_career_trajectory_chart(cand_firm_name)
            if traj:
                chart_buffers["career_trajectory"] = traj

        # 7. Assemble PDF
        pdf_buf = _assemble_pitch_pdf(narratives, scores, chart_buffers, attorney_data,
                                       job_data, firm_data, dna, sections, anonymize, recruiter_info)

        # 8. Log to pipeline history if applicable
        if pipeline_id:
            try:
                conn = ats_db.get_db()
                conn.execute(
                    "INSERT INTO pipeline_history (pipeline_id, from_stage, to_stage, changed_by, note) VALUES (?, ?, ?, ?, ?)",
                    (int(pipeline_id), None, None, "System", "Generated pitch PDF"),
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[Pitch history log error] {e}")

        # 9. Return PDF
        cand_name = attorney_data.get("name", "candidate").replace(" ", "-")
        if anonymize:
            cand_name = "Candidate"
        filename = f"pitch-{cand_name}-{datetime.now().strftime('%Y%m%d')}.pdf"

        return send_file(pdf_buf, mimetype="application/pdf", as_attachment=True, download_name=filename)

    except Exception as e:
        print(f"[Pitch PDF generation error] {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _custom_attorney_to_candidate(ca, keywords=None, practice_areas=None):
    """Convert a custom_attorney dict to the same shape as _serialize_candidate."""
    name = f"{ca.get('first_name', '')} {ca.get('last_name', '')}".strip()
    # Basic keyword-based score
    score = 50  # baseline for custom records
    if keywords:
        text = " ".join([
            ca.get("bio", "") or "",
            ca.get("practice_areas", "") or "",
            ca.get("specialty", "") or "",
            ca.get("prior_experience", "") or "",
        ]).lower()
        hits = sum(1 for kw in keywords if kw.lower() in text)
        score = min(95, 50 + hits * 8)
    if practice_areas:
        pa_text = (ca.get("practice_areas", "") or "").lower()
        if any(pa.lower() in pa_text for pa in practice_areas):
            score = min(99, score + 15)

    tier = "Tier 1" if score >= 80 else ("Tier 2" if score >= 60 else "Tier 3")
    return {
        "id": f"custom_{ca['id']}",
        "rank": 0,
        "tier": tier,
        "name": name,
        "first_name": ca.get("first_name", ""),
        "last_name": ca.get("last_name", ""),
        "current_firm": ca.get("current_firm", ""),
        "title": ca.get("title", ""),
        "graduation_year": ca.get("graduation_year", ""),
        "law_school": ca.get("law_school", ""),
        "bar_admission": ca.get("bar_admissions", ""),
        "specialties": ca.get("specialty", ""),
        "practice_areas": ca.get("practice_areas", ""),
        "prior_firms": ca.get("prior_experience", ""),
        "pattern_matches": "",
        "qualifications_summary": ca.get("bio", "") or ca.get("summary", ""),
        "match_score": score,
        "photo_url": ca.get("photo_url", ""),
        "email": ca.get("email", ""),
        "phone_primary": ca.get("phone", ""),
        "linkedinURL": ca.get("linkedin_url", ""),
        "profileURL": "",
        "attorneyBio": ca.get("bio", ""),
        "undergraduate": ca.get("undergraduate", ""),
        "llm_school": ca.get("llm_school", ""),
        "llm_year": "",
        "llm_specialty": ca.get("llm_specialty", ""),
        "clerkships": ca.get("clerkships", ""),
        "raw_acknowledgements": "",
        "languages": ca.get("languages", ""),
        "location": ", ".join(filter(None, [ca.get("location_city", ""), ca.get("location_state", "")])),
        "scraped_on": ca.get("updated_at", ""),
        "is_boomerang": False,
        "source": "custom",
        "attorney_source": "custom",
    }


@app.route("/api/search", methods=["POST"])
def search():
    data = request.get_json()
    jd_text = data.get("jd", "")
    use_ai = data.get("use_ai", True)
    exact_firm = data.get("firm_name", "")  # When provided, skip fuzzy extraction
    skip_patterns = data.get("skip_patterns", False)
    source_filter = data.get("source", "all")  # "all", "fp", "custom"
    if not jd_text.strip():
        return jsonify({"error": "Please provide a job description."}), 400

    # 1. Parse JD
    firm_name = exact_firm if exact_firm else extract_firm_name(jd_text)
    locations = extract_location(jd_text)
    cities = [loc[0] for loc in locations]
    state = locations[0][1] if locations else ""
    yr_min, yr_max = extract_grad_years(jd_text)
    practice_areas = extract_practice_area(jd_text)
    required_bars = extract_bar(jd_text)
    keywords = extract_keywords(jd_text)
    title_filter = extract_title_level(jd_text)
    law_school_filter = extract_law_school(jd_text)

    # 2. Hiring pattern analysis
    if skip_patterns:
        patterns = {"firm_name": "", "matched_firm": None, "cards": [],
                    "feeder_schools": [], "feeder_firms": [], "top_specialties": []}
        firm_name = ""
    else:
        patterns = analyze_hiring_patterns(firm_name, cities, state, exact_firm=bool(exact_firm))

    # 3. Filter attorneys
    df = ATTORNEYS_DF.copy()
    total_attorneys = len(df)

    if yr_min and yr_max:
        df["_grad"] = pd.to_numeric(df["graduationYear"], errors="coerce")
        df = df[(df["_grad"] >= yr_min) & (df["_grad"] <= yr_max)]
        df = df.drop(columns=["_grad"])

    if cities:
        location_mask = pd.Series(False, index=df.index)
        for c in cities:
            location_mask |= df["location"].str.lower().str.contains(c.lower(), na=False)
            location_mask |= df["location_secondary"].str.lower().str.contains(c.lower(), na=False)
        df = df[location_mask]

    if practice_areas:
        pa_mask = pd.Series(False, index=df.index)
        for pa in practice_areas:
            pa_mask |= df["practice_areas"].str.lower().str.contains(pa.lower(), na=False)
            pa_mask |= df["specialty"].str.lower().str.contains(pa.lower(), na=False)
        df = df[pa_mask]

    if law_school_filter:
        school_col = df["lawSchool"].fillna("").str.strip()
        df = df[school_col.str.lower() == law_school_filter.lower()]

    if title_filter:
        title_col = df["title"].str.lower().str.strip()
        title_mask = title_col.isin(title_filter)
        # Secondary blocklist: explicitly exclude counsel/partner titles for associate searches
        _COUNSEL_PARTNER_BLOCKLIST = ["counsel", "partner", "of counsel", "senior counsel",
            "special counsel", "shareholder", "member", "principal", "director",
            "chair", "co-chair", "vice chair", "head", "co-head"]
        if "associate" in title_filter:
            for blocked in _COUNSEL_PARTNER_BLOCKLIST:
                title_mask &= ~title_col.str.contains(blocked, regex=False, na=False)
        df = df[title_mask]

    # Exclude attorneys currently at the hiring firm
    hiring_firm = patterns.get("matched_firm", "") or firm_name
    excluded_count = 0
    if hiring_firm:
        hf_lower = hiring_firm.lower()
        current_firm_col = df["firm_name"].fillna("").str.lower().str.strip()
        same_firm_mask = current_firm_col.str.contains(hf_lower, regex=False, na=False)
        # Also check reverse containment for short names (e.g. "Kirkland" in "Kirkland & Ellis LLP")
        same_firm_mask |= current_firm_col.apply(lambda f: bool(f) and f in hf_lower)
        excluded_count = int(same_firm_mask.sum())
        df = df[~same_firm_mask]

    filtered_count = len(df)

    # 4. Vectorized scoring of all filtered attorneys
    patterns["_practice_areas"] = practice_areas  # Pass to scorer for PA overlap
    scored_df = score_attorneys_vectorized(df, keywords, patterns)
    total_matched = len(scored_df)

    # Build rationale only for the top candidates we'll actually use
    shortlist_limit = max(SHORTLIST_SIZE, 25)  # enough for both AI and Quick paths
    top_df = scored_df.head(shortlist_limit)
    scored = []
    for _, row in top_df.iterrows():
        entry = row.to_dict()
        extras = build_rationale_for_row(entry, keywords, patterns)
        entry.update(extras)
        # Flag boomerang candidates (previously at the hiring firm, now elsewhere)
        if hiring_firm:
            prior = str(entry.get("prior_experience", "")).lower()
            if hiring_firm.lower() in prior:
                entry["is_boomerang"] = True
        scored.append(entry)

    # Build custom attorneys and merge (if source_filter allows)
    if source_filter != "fp":
        city_str = " / ".join(cities) if cities else ""
        custom_atts = ats_db.list_custom_attorneys(
            search="",
            practice_area=practice_areas[0] if practice_areas else "",
            location=cities[0] if cities else "",
            grad_year_min=yr_min,
            grad_year_max=yr_max,
        )
        custom_candidates = [_custom_attorney_to_candidate(ca, keywords, practice_areas) for ca in custom_atts]
    else:
        custom_candidates = []

    # Mark FP candidates with source
    for s in scored:
        s.setdefault("source", "fp")
        s.setdefault("attorney_source", "fp")

    # Filter by source_filter
    if source_filter == "fp":
        pass  # scored already contains only FP
    elif source_filter == "custom":
        scored = []
    # else "all" — keep scored as-is, will merge below

    # 5. Determine analysis mode
    city = " / ".join(cities) if cities else ""
    meta = {
        "firm_name": firm_name,
        "matched_firm": patterns.get("matched_firm", ""),
        "city": city,
        "state": state,
        "grad_year_min": yr_min,
        "grad_year_max": yr_max,
        "practice_areas": practice_areas,
        "required_bars": required_bars,
        "title_filter": title_filter,
        "keywords": keywords,
        "total_attorneys": total_attorneys,
        "filtered_count": filtered_count,
        "total_matched": total_matched,
        "excluded_hiring_firm": excluded_count,
    }

    ai_used = False
    ai_error = None

    if use_ai and ANTHROPIC_API_KEY and scored:
        shortlist = scored[:SHORTLIST_SIZE]
        # Build a name→row lookup for merging profile data back
        shortlist_by_name = {}
        for s in shortlist:
            sname = f"{s.get('first_name', '')} {s.get('last_name', '')}".strip().lower()
            shortlist_by_name[sname] = s
        try:
            claude_result = call_claude_api(jd_text, patterns, shortlist, meta)
            if claude_result:
                ai_used = True
                raw_ai = claude_result.get("candidates", [])
                # Merge Claude's assessment with full profile data
                ai_candidates = []
                for ac in raw_ai:
                    ac_name = (ac.get("name") or "").strip().lower()
                    original = shortlist_by_name.get(ac_name, {})
                    merged = {**original, **ac}  # Claude fields override
                    cand = _serialize_candidate(merged)
                    cand["source"] = "fp"
                    cand["attorney_source"] = "fp"
                    ai_candidates.append(cand)
                # Merge custom candidates
                if source_filter != "fp":
                    all_candidates = ai_candidates + custom_candidates
                    all_candidates.sort(key=lambda c: -(c.get("match_score") or 0))
                else:
                    all_candidates = ai_candidates
                _session["jd"] = jd_text
                _session["candidates"] = all_candidates
                _session["patterns"] = patterns
                _session["meta"] = meta
                _session["history"] = []
                return jsonify({
                    "mode": "ai",
                    "chat_response": claude_result.get("chat_summary", ""),
                    "candidates": all_candidates,
                    "hiring_patterns": _sanitize_for_json(patterns),
                    "meta": _sanitize_for_json({**meta, "result_count": len(all_candidates), "ai_used": True}),
                })
        except Exception:
            ai_error = traceback.format_exc()
            print(f"[Claude API error] {ai_error}")

    # -----------------------------------------------------------------------
    # Fallback: keyword-based analysis (Quick Match mode)
    # -----------------------------------------------------------------------
    MAX_RESULTS = 25
    results = scored[:MAX_RESULTS]
    for i, r in enumerate(results):
        r["rank"] = i + 1

    # Build tier summaries
    tier_summaries = {}
    for r in results:
        t = r["tier"]
        if t not in tier_summaries:
            tier_summaries[t] = {"count": 0, "names": []}
        tier_summaries[t]["count"] += 1
        tier_summaries[t]["names"].append(f"{r['first_name']} {r['last_name']}")

    # Build conversational summary
    matched_firm = patterns.get("matched_firm", "")
    summary_parts = []

    if ai_error:
        summary_parts.append(
            "**Note:** AI analysis unavailable — showing keyword-based ranking."
        )

    if firm_name:
        display_firm = matched_firm if matched_firm else firm_name
        summary_parts.append(f"I analyzed your job description for **{display_firm}**")
        if matched_firm and matched_firm.lower() != firm_name.lower():
            summary_parts[-1] += f' (matched from "{firm_name}")'
        if city:
            summary_parts[-1] += f" in **{city}**"
        summary_parts[-1] += "."
    else:
        summary_parts.append("I analyzed your job description.")

    filter_note = (
        f"From **{total_attorneys:,}** attorneys, **{filtered_count}** passed "
        f"initial filters and **{total_matched}** scored above the match threshold."
    )
    if excluded_count:
        filter_note += f" ({excluded_count} current {hiring_firm} attorney{'s' if excluded_count != 1 else ''} excluded.)"
    summary_parts.append(filter_note)

    if results:
        shown = len(results)
        if total_matched > shown:
            summary_parts.append(f"Showing the top **{shown}** candidates (of {total_matched} matches).")

        tier_labels = {"1": "Tier 1 — Strong Fit", "2": "Tier 2 — Good Fit", "3": "Tier 3 — Possible Fit"}
        for t in ["1", "2", "3"]:
            info = tier_summaries.get(t)
            if not info:
                continue
            names_preview = ", ".join(info["names"][:4])
            if info["count"] > 4:
                names_preview += f" + {info['count'] - 4} more"
            summary_parts.append(f"\n**{tier_labels[t]}** ({info['count']}): {names_preview}")

        if patterns.get("cards"):
            summary_parts.append(
                f"\nI also identified **{len(patterns['cards'])} hiring patterns** "
                f"from the firm's lateral history — see the right panel for details."
            )
        elif not matched_firm and excluded_count == 0:
            summary_parts.append(
                "\nScoring is based on practice area relevance and credentials "
                "(no firm-specific hiring patterns applied)."
            )
    else:
        summary_parts.append(
            "No candidates matched with sufficient relevance. "
            "Try broadening the graduation year range or practice area."
        )

    chat_response = "\n\n".join(summary_parts)

    # Serialize candidates for Quick Match (include all profile fields)
    candidates = []
    for r in results:
        cand = _serialize_candidate(r)
        cand["source"] = "fp"
        cand["attorney_source"] = "fp"
        candidates.append(cand)

    # Merge custom candidates into quick-match results
    if source_filter != "fp":
        all_candidates = candidates + custom_candidates
        all_candidates.sort(key=lambda c: -(c.get("match_score") or 0))
        # Re-number ranks
        for i, c in enumerate(all_candidates):
            c["rank"] = i + 1
    else:
        all_candidates = candidates

    # Save to session for follow-ups
    _session["jd"] = jd_text
    _session["candidates"] = all_candidates
    _session["patterns"] = patterns
    _session["meta"] = meta
    _session["history"] = []

    return jsonify({
        "mode": "quick",
        "chat_response": chat_response,
        "candidates": all_candidates,
        "tier_summaries": [
            {"tier": f"Tier {t}", "title": lbl, "names": ", ".join(tier_summaries[t]["names"]),
             "description": f"{tier_summaries[t]['count']} candidates matched at this level."}
            for t, lbl in [("1", "Strong Fit"), ("2", "Good Fit"), ("3", "Possible Fit")]
            if t in tier_summaries
        ],
        "hiring_patterns": _sanitize_for_json(patterns),
        "meta": _sanitize_for_json({**meta, "result_count": len(all_candidates), "ai_used": False}),
    })


# ---------------------------------------------------------------------------
# Streaming search endpoint (AI mode)
# ---------------------------------------------------------------------------

@app.route("/api/search/stream", methods=["POST"])
def search_stream():
    """SSE endpoint — streams AI analysis progress, then final JSON result."""
    data = request.get_json()
    jd_text = data.get("jd", "")
    exact_firm = data.get("firm_name", "")  # When provided, skip fuzzy extraction
    skip_patterns = data.get("skip_patterns", False)
    if not jd_text.strip():
        return jsonify({"error": "Please provide a job description."}), 400

    # Parse & filter (same as /api/search)
    firm_name = exact_firm if exact_firm else extract_firm_name(jd_text)
    locations = extract_location(jd_text)
    cities = [loc[0] for loc in locations]
    state = locations[0][1] if locations else ""
    yr_min, yr_max = extract_grad_years(jd_text)
    practice_areas = extract_practice_area(jd_text)
    required_bars = extract_bar(jd_text)
    keywords = extract_keywords(jd_text)
    title_filter = extract_title_level(jd_text)
    if skip_patterns:
        patterns = {"firm_name": "", "matched_firm": None, "cards": [],
                    "feeder_schools": [], "feeder_firms": [], "top_specialties": []}
        firm_name = ""
    else:
        patterns = analyze_hiring_patterns(firm_name, cities, state, exact_firm=bool(exact_firm))

    df = ATTORNEYS_DF.copy()
    total_attorneys = len(df)
    if yr_min and yr_max:
        df["_grad"] = pd.to_numeric(df["graduationYear"], errors="coerce")
        df = df[(df["_grad"] >= yr_min) & (df["_grad"] <= yr_max)]
        df = df.drop(columns=["_grad"])
    if cities:
        loc_mask = pd.Series(False, index=df.index)
        for c in cities:
            loc_mask |= df["location"].str.lower().str.contains(c.lower(), na=False)
            loc_mask |= df["location_secondary"].str.lower().str.contains(c.lower(), na=False)
        df = df[loc_mask]
    if practice_areas:
        pa_mask = pd.Series(False, index=df.index)
        for pa in practice_areas:
            pa_mask |= df["practice_areas"].str.lower().str.contains(pa.lower(), na=False)
            pa_mask |= df["specialty"].str.lower().str.contains(pa.lower(), na=False)
        df = df[pa_mask]
    if title_filter:
        title_col = df["title"].str.lower().str.strip()
        title_mask = title_col.isin(title_filter)
        _COUNSEL_PARTNER_BLOCKLIST = ["counsel", "partner", "of counsel", "senior counsel",
            "special counsel", "shareholder", "member", "principal", "director",
            "chair", "co-chair", "vice chair", "head", "co-head"]
        if "associate" in title_filter:
            for blocked in _COUNSEL_PARTNER_BLOCKLIST:
                title_mask &= ~title_col.str.contains(blocked, regex=False, na=False)
        df = df[title_mask]

    # Exclude attorneys currently at the hiring firm
    hiring_firm = patterns.get("matched_firm", "") or firm_name
    excluded_count = 0
    if hiring_firm:
        hf_lower = hiring_firm.lower()
        current_firm_col = df["firm_name"].fillna("").str.lower().str.strip()
        same_firm_mask = current_firm_col.str.contains(hf_lower, regex=False, na=False)
        same_firm_mask |= current_firm_col.apply(lambda f: bool(f) and f in hf_lower)
        excluded_count = int(same_firm_mask.sum())
        df = df[~same_firm_mask]

    filtered_count = len(df)
    patterns["_practice_areas"] = practice_areas  # Pass to scorer for PA overlap
    scored_df = score_attorneys_vectorized(df, keywords, patterns)
    total_matched = len(scored_df)

    top_df = scored_df.head(SHORTLIST_SIZE)
    scored = []
    for _, row in top_df.iterrows():
        entry = row.to_dict()
        extras = build_rationale_for_row(entry, keywords, patterns)
        entry.update(extras)
        # Flag boomerang candidates
        if hiring_firm:
            prior = str(entry.get("prior_experience", "")).lower()
            if hiring_firm.lower() in prior:
                entry["is_boomerang"] = True
        scored.append(entry)

    city = " / ".join(cities) if cities else ""
    meta = {
        "firm_name": firm_name,
        "matched_firm": patterns.get("matched_firm", ""),
        "city": city, "state": state,
        "grad_year_min": yr_min, "grad_year_max": yr_max,
        "practice_areas": practice_areas,
        "required_bars": required_bars,
        "keywords": keywords,
        "total_attorneys": total_attorneys,
        "filtered_count": filtered_count,
        "total_matched": total_matched,
        "excluded_hiring_firm": excluded_count,
    }

    shortlist = scored[:SHORTLIST_SIZE]
    # Pre-serialize shortlist profiles for the client to merge
    shortlist_profiles = [_serialize_candidate(s) for s in shortlist]
    shortlist_by_name = {p["name"].strip().lower(): p for p in shortlist_profiles}

    # Sanitize numpy types before JSON serialization
    safe_patterns = _sanitize_for_json(patterns)
    safe_meta = _sanitize_for_json(meta)

    def generate():
        # Send patterns/meta + profiles immediately
        yield f"data: {json.dumps({'type': 'meta', 'hiring_patterns': safe_patterns, 'meta': safe_meta, 'profiles': shortlist_profiles})}\n\n"

        # Stream the Claude response
        for event in stream_claude_api(jd_text, patterns, shortlist, meta):
            yield event
            # When done, merge and save to session
            if '"type": "done"' in event:
                try:
                    evt_data = json.loads(event.replace("data: ", "").strip())
                    raw_candidates = evt_data.get("result", {}).get("candidates", [])
                    merged = []
                    for ac in raw_candidates:
                        ac_name = (ac.get("name") or "").strip().lower()
                        original = shortlist_by_name.get(ac_name, {})
                        merged.append({**original, **ac})
                    _session["jd"] = jd_text
                    _session["candidates"] = merged
                    _session["patterns"] = patterns
                    _session["meta"] = meta
                    _session["history"] = []
                except Exception:
                    pass

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Follow-up conversation
# ---------------------------------------------------------------------------

# In-memory context for the current session (single-user POC)
_session = {
    "jd": "",
    "candidates": [],
    "patterns": {},
    "meta": {},
    "history": [],  # list of {"role": ..., "content": ...}
}

FOLLOWUP_SYSTEM = """You are an expert legal recruiting analyst continuing a conversation about attorney candidates.

You have access to the current search results — a list of candidates that were already analyzed and tiered for a specific job description. The user is asking follow-up questions about these candidates.

You can:
- Answer questions about specific candidates (background, strengths, concerns)
- Compare candidates to each other
- Explain why a candidate was placed in a specific tier
- Suggest which candidates to prioritize for outreach
- Provide additional context from their bios or hiring patterns
- Filter or re-rank candidates based on new criteria

Respond conversationally in 2-4 paragraphs. Use **bold** for candidate names and key points. Be specific — reference actual details from the candidate data.

If the user asks to filter candidates (e.g., "show only Tier 1" or "remove anyone without NY bar"), respond with your explanation AND include a JSON block at the end of your response in this exact format:

```json
{"action": "filter", "candidates": [array of updated candidate objects with same structure as original]}
```

Only include the JSON block if the user's question requires changing what's displayed in the results panel. For pure Q&A, just respond with text."""


@app.route("/api/followup", methods=["POST"])
def followup():
    data = request.get_json()
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "Please ask a question."}), 400

    if not _session["candidates"]:
        return jsonify({"error": "No search results to discuss. Run a search first."}), 400

    if not ANTHROPIC_API_KEY:
        return jsonify({
            "chat_response": "Follow-up questions require the AI API key. Please set ANTHROPIC_API_KEY and restart.",
            "updated_candidates": None,
        })

    # Build context with current candidates
    candidates_summary = []
    for c in _session["candidates"]:
        name = c.get("name", "")
        tier = c.get("tier", "")
        firm = c.get("current_firm", "")
        school = c.get("law_school", "")
        year = c.get("graduation_year", "")
        specs = c.get("specialties", "")
        assessment = c.get("qualifications_summary", "")
        bar = c.get("bar_admission", "")
        prior = c.get("prior_firms", "")
        pattern = c.get("pattern_matches", "")
        candidates_summary.append(
            f"#{c.get('rank','')}) {name} | {tier} | {firm} | {school} {year} | "
            f"Bar: {bar} | Specs: {specs} | Prior: {prior} | "
            f"Patterns: {pattern} | Assessment: {assessment}"
        )

    candidates_text = "\n".join(candidates_summary)
    context = f"""## Current Job Description
{_session['jd']}

## Current Candidates ({len(_session['candidates'])} results)
{candidates_text}
"""

    # Build conversation history
    messages = [{"role": "user", "content": context + "\n\n---\nUser question: " + question}]

    # Add prior follow-up history (keep last 6 turns)
    history = _session["history"][-6:]
    if history:
        messages = [{"role": "user", "content": context}] + history + [{"role": "user", "content": question}]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            temperature=0,
            system=FOLLOWUP_SYSTEM,
            messages=messages,
        )
        answer = response.content[0].text.strip()

        # Track history
        _session["history"].append({"role": "user", "content": question})
        _session["history"].append({"role": "assistant", "content": answer})

        # Check if response contains a filter action
        updated_candidates = None
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", answer, re.DOTALL)
        if json_match:
            try:
                action_data = json.loads(json_match.group(1))
                if action_data.get("action") == "filter" and action_data.get("candidates"):
                    updated_candidates = action_data["candidates"]
                    _session["candidates"] = updated_candidates
            except (json.JSONDecodeError, KeyError):
                pass
            # Remove the JSON block from the chat response
            chat_text = answer[:json_match.start()].strip()
        else:
            chat_text = answer

        return jsonify({
            "chat_response": chat_text,
            "updated_candidates": updated_candidates,
        })

    except Exception:
        traceback.print_exc()
        return jsonify({
            "chat_response": "Sorry, I couldn't process that question. Please try again.",
            "updated_candidates": None,
        })


# ---------------------------------------------------------------------------
# Email integration
# ---------------------------------------------------------------------------

SMTP_PROVIDERS = {
    "gmail": {"host": "smtp.gmail.com", "port": 587},
    "outlook": {"host": "smtp-mail.outlook.com", "port": 587},
    "custom": {"host": "", "port": 587},
}

_email_settings_path = os.path.join(DATA_DIR, "email_settings.json")
_email_password = {}  # in-memory only, never saved to disk


def _load_email_settings():
    if os.path.exists(_email_settings_path):
        with open(_email_settings_path, "r") as f:
            return json.load(f)
    return {
        "mode": "mailto",
        "provider": "gmail",
        "email": "",
        "display_name": "",
        "title": "",
        "phone": "",
        "custom_host": "",
        "custom_port": 587,
    }


def _save_email_settings(settings):
    with open(_email_settings_path, "w") as f:
        json.dump(settings, f, indent=2)


def _resolve_merge(template, candidate, settings):
    """Replace {field_name} placeholders with candidate/settings values."""
    mapping = {
        "first_name": candidate.get("first_name") or (candidate.get("name", "").split()[0] if candidate.get("name") else ""),
        "last_name": candidate.get("last_name") or (candidate.get("name", "").split()[-1] if candidate.get("name") else ""),
        "name": candidate.get("name") or f"{candidate.get('first_name', '')} {candidate.get('last_name', '')}".strip(),
        "firm": candidate.get("current_firm") or candidate.get("firm_name", ""),
        "title": candidate.get("title", ""),
        "law_school": candidate.get("law_school") or candidate.get("lawSchool", ""),
        "graduation_year": str(candidate.get("graduation_year") or candidate.get("graduationYear", "")),
        "specialties": candidate.get("specialties") or candidate.get("specialty", ""),
        "location": candidate.get("location", ""),
        "sender_name": settings.get("display_name", ""),
        "sender_title": settings.get("title", ""),
        "sender_phone": settings.get("phone", ""),
        "sender_email": settings.get("email", ""),
    }
    result = template
    for key, val in mapping.items():
        result = result.replace("{" + key + "}", str(val) if val else "")
    return result


def _send_single_email(to_addr, subject, body, settings):
    """Send a single email via SMTP. Returns (success, error_message)."""
    provider = settings.get("provider", "gmail")
    smtp_cfg = SMTP_PROVIDERS.get(provider, SMTP_PROVIDERS["gmail"])
    host = settings.get("custom_host") or smtp_cfg["host"]
    port = int(settings.get("custom_port") or smtp_cfg["port"])
    from_email = settings.get("email", "")
    password = _email_password.get("password", "")
    display_name = settings.get("display_name", "")

    if not from_email or not password:
        return False, "Email credentials not configured"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{display_name} <{from_email}>" if display_name else from_email
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(from_email, password)
            server.sendmail(from_email, [to_addr], msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)


def _log_email(to_addr, candidate_name, subject, status, error="", body="", **kwargs):
    """Log an email send to SQLite.
    # TODO: Nylas webhook will update opened_at/clicked_at/replied_at/nylas_* fields
    #       via POST /api/email/webhook once Nylas integration is configured.
    """
    ats_db.log_email(
        recipient_email=to_addr,
        candidate_name=candidate_name,
        subject=subject,
        status=status,
        error=error,
        body=body,
        attorney_id=kwargs.get("attorney_id", ""),
        attorney_source=kwargs.get("attorney_source", "fp"),
        job_id=kwargs.get("job_id"),
        job_title=kwargs.get("job_title", ""),
        batch_id=kwargs.get("batch_id", ""),
        sent_by=kwargs.get("sent_by", "Admin"),
        email_type=kwargs.get("email_type", "individual"),
    )


@app.route("/api/email/draft", methods=["POST"])
def api_email_draft():
    """Use AI to draft a recruiting email based on the current job description."""
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "API key not configured"}), 500

    data = request.get_json()
    jd_text = data.get("jd", "")
    firm_name = data.get("firm_name", "")
    meta = data.get("meta", {})

    # Build context for the AI
    city = meta.get("city", "")
    practice_areas = meta.get("practice_areas", [])
    if isinstance(practice_areas, list):
        practice_areas = ", ".join(practice_areas)

    context_parts = []
    if firm_name:
        context_parts.append(f"Hiring firm: {firm_name}")
    if city:
        context_parts.append(f"Location: {city}")
    if practice_areas:
        context_parts.append(f"Practice area: {practice_areas}")
    if meta.get("grad_year_min") and meta.get("grad_year_max"):
        yrs_min = CURRENT_YEAR - meta["grad_year_max"]
        yrs_max = CURRENT_YEAR - meta["grad_year_min"]
        context_parts.append(f"Experience level: {yrs_min}-{yrs_max} years")
    if jd_text:
        context_parts.append(f"Job description excerpt:\n{jd_text[:1500]}")

    context = "\n".join(context_parts)

    system_prompt = """You are a legal recruiter drafting an outreach email to attorneys about a job opportunity.

Rules:
- The email MUST be anonymous — do NOT name the hiring firm. Use phrases like "a prestigious Am Law firm", "a leading international firm", "a top-tier firm", etc.
- Use merge fields for personalization: {first_name} for the recipient's first name, {firm} for their current firm, {specialties} for their practice areas
- Keep it brief — 4-6 sentences max for the body
- Pique the recipient's interest without revealing too much
- Mention the practice area, general location, and experience level
- Sound professional but warm, not robotic
- Include a call-to-action to schedule a confidential conversation
- End with signature placeholders: {sender_name}, {sender_title}, {sender_phone}, {sender_email}

Return ONLY valid JSON (no markdown fences):
{
  "subject": "the email subject line",
  "body": "the full email body with merge fields and newlines"
}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": context}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        return jsonify({"ok": True, "subject": result.get("subject", ""), "body": result.get("body", "")})
    except Exception as e:
        print(f"[Email draft error] {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/email/draft-personalized", methods=["POST"])
def api_email_draft_personalized():
    """Use AI to draft a deeply personalized recruiting email for a single attorney."""
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "API key not configured"}), 500

    data = request.get_json()
    attorney = data.get("attorney", {})
    jd_text = data.get("jd", "")
    firm_name = data.get("firm_name", "")
    meta = data.get("meta", {})

    # Enrich bio on-demand if not present (dropped from main DF to save memory)
    if not attorney.get("attorneyBio") and attorney.get("id"):
        attorney["attorneyBio"] = get_attorney_full_bio(attorney["id"])

    # Build rich attorney profile
    name = attorney.get("name") or f"{attorney.get('first_name', '')} {attorney.get('last_name', '')}".strip()
    profile_fields = {
        "Name": name,
        "Current Firm": attorney.get("current_firm", ""),
        "Title": attorney.get("title", ""),
        "Class Year": attorney.get("graduation_year", ""),
        "Law School": attorney.get("law_school", ""),
        "Undergraduate": attorney.get("undergraduate", ""),
        "LLM": attorney.get("llm_school", ""),
        "LLM Specialty": attorney.get("llm_specialty", ""),
        "Bar Admissions": attorney.get("bar_admission", ""),
        "Specialties": attorney.get("specialties", ""),
        "Practice Areas": attorney.get("practice_areas", ""),
        "Prior Firms": attorney.get("prior_firms", ""),
        "Clerkships": attorney.get("clerkships", ""),
        "Accolades": attorney.get("raw_acknowledgements", ""),
        "Location": attorney.get("location", ""),
    }
    profile_lines = [f"  {k}: {v}" for k, v in profile_fields.items() if v and str(v).strip()]
    bio = str(attorney.get("attorneyBio", "")).strip()
    if bio:
        profile_lines.append(f"  Full Bio: {bio}")
    attorney_profile = "\n".join(profile_lines)

    # Build job context
    city = meta.get("city", "")
    practice_areas = meta.get("practice_areas", [])
    if isinstance(practice_areas, list):
        practice_areas = ", ".join(practice_areas)

    context_parts = [f"ATTORNEY PROFILE:\n{attorney_profile}"]
    if firm_name:
        context_parts.append(f"Hiring firm (CONFIDENTIAL — do NOT mention by name): {firm_name}")
    if city:
        context_parts.append(f"Location: {city}")
    if practice_areas:
        context_parts.append(f"Practice area: {practice_areas}")
    if meta.get("grad_year_min") and meta.get("grad_year_max"):
        yrs_min = CURRENT_YEAR - meta["grad_year_max"]
        yrs_max = CURRENT_YEAR - meta["grad_year_min"]
        context_parts.append(f"Experience level: {yrs_min}-{yrs_max} years")
    if jd_text:
        context_parts.append(f"Job description excerpt:\n{jd_text[:1500]}")

    context = "\n\n".join(context_parts)

    system_prompt = """You are a legal recruiter drafting a highly personalized outreach email to a specific attorney about a job opportunity.

You have their full professional profile. Use it to write an email that demonstrates genuine familiarity with their career.

Rules:
- Reference SPECIFIC details from the attorney's background — their firm, practice focus, law school, clerkships, prior firms, accolades, or career trajectory
- For example: "Given your work in structured finance at Kirkland..." or "Your clerkship with Judge Smith and subsequent focus on..."
- Use the attorney's actual first name directly — do NOT use merge fields like {first_name}
- The email MUST be anonymous about the HIRING firm — do NOT name it. Use phrases like "a prestigious Am Law firm", "a leading international firm", etc.
- Write a substantive body of 6-10 sentences that shows you've studied their background
- Sound professional, warm, and genuinely interested in this specific attorney
- Include a call-to-action to schedule a confidential conversation
- End with signature placeholders: {sender_name}, {sender_title}, {sender_phone}, {sender_email}

Return ONLY valid JSON (no markdown fences):
{
  "subject": "the email subject line",
  "body": "the full email body with newlines"
}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=900,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": context}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        return jsonify({"ok": True, "subject": result.get("subject", ""), "body": result.get("body", "")})
    except Exception as e:
        print(f"[Personalized email draft error] {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/email/settings", methods=["GET"])
def get_email_settings():
    settings = _load_email_settings()
    settings["has_password"] = bool(_email_password.get("password"))
    return jsonify(settings)


@app.route("/api/email/settings", methods=["POST"])
def save_email_settings():
    data = request.get_json()
    password = data.pop("password", None)
    if password:
        _email_password["password"] = password
    settings = _load_email_settings()
    settings.update(data)
    _save_email_settings(settings)
    settings["has_password"] = bool(_email_password.get("password"))
    return jsonify({"ok": True, "settings": settings})


@app.route("/api/email/test", methods=["POST"])
def test_email():
    settings = _load_email_settings()
    data = request.get_json()
    password = data.get("password")
    if password:
        _email_password["password"] = password
    to_addr = settings.get("email", "")
    if not to_addr:
        return jsonify({"ok": False, "error": "No email configured"}), 400
    ok, err = _send_single_email(
        to_addr, "JAIDE Test Email",
        "This is a test email from JAIDE. Your SMTP settings are working correctly.",
        settings,
    )
    return jsonify({"ok": ok, "error": err})


@app.route("/api/email/send", methods=["POST"])
def send_emails():
    data = request.get_json()
    recipients = data.get("recipients", [])
    subject_template = data.get("subject", "")
    body_template = data.get("body", "")
    cc = data.get("cc", "")
    bcc = data.get("bcc", "")
    settings = _load_email_settings()

    batch_id = str(uuid.uuid4()) if len(recipients) > 1 else ""
    email_type = "bulk" if len(recipients) > 1 else "individual"
    sent_by = session.get("user_name", "Admin")

    results = []
    for i, recip in enumerate(recipients):
        to_addr = recip.get("email", "")
        candidate_name = recip.get("name", "Unknown")
        if not to_addr:
            results.append({"name": candidate_name, "status": "skipped", "error": "No email address"})
            continue
        subject = _resolve_merge(subject_template, recip, settings)
        body = _resolve_merge(body_template, recip, settings)
        ok, err = _send_single_email(to_addr, subject, body, settings)
        status = "sent" if ok else "failed"
        _log_email(to_addr, candidate_name, subject, status, err or "",
                   body=body,
                   attorney_id=str(recip.get("id") or recip.get("attorney_id") or ""),
                   attorney_source=recip.get("attorney_source", "fp"),
                   job_id=data.get("job_id"),
                   job_title=data.get("job_title", ""),
                   batch_id=batch_id,
                   sent_by=sent_by,
                   email_type=email_type)
        results.append({"name": candidate_name, "status": status, "error": err})
        if i < len(recipients) - 1:
            time.sleep(1)

    return jsonify({"results": results})


@app.route("/api/email/log", methods=["GET"])
def get_email_log():
    status_filter = request.args.get("status", "")
    q = request.args.get("q", "")
    entries = ats_db.get_email_log(status_filter=status_filter, q=q)
    stats = ats_db.get_email_stats()
    return jsonify({"entries": entries, "stats": stats})


@app.route("/api/email/history/<attorney_id>", methods=["GET"])
def get_email_history(attorney_id):
    """Return email history for a specific attorney (for profile card)."""
    recipient_email = request.args.get("email", "")
    entries = ats_db.get_email_history_by_attorney(attorney_id, recipient_email=recipient_email)
    return jsonify({"entries": entries})


@app.route("/api/email/counts", methods=["GET"])
def get_email_counts():
    """Return email send/open counts grouped by attorney_id (for kanban badges)."""
    return jsonify(ats_db.get_email_counts_for_pipeline())


@app.route("/api/email/webhook", methods=["POST"])
def email_webhook():
    """
    Stub endpoint for future Nylas webhook integration.

    TODO: Nylas will POST events here when emails are opened, clicked, or replied to.
    Expected payload format (Nylas v3 webhooks):
    {
        "type": "message.opened" | "message.link_clicked" | "thread.replied" | "message.bounced",
        "data": {
            "message_id": "...",   # maps to nylas_message_id in email_log
            "thread_id": "...",    # maps to nylas_thread_id in email_log
            "timestamp": 1234567890
        }
    }

    When connected, this endpoint should:
    - message.opened    → UPDATE email_log SET opened_at=?, opened_count=opened_count+1
                          WHERE nylas_message_id=?
    - message.link_clicked → UPDATE email_log SET clicked_at=?, clicked_count=clicked_count+1
                             WHERE nylas_message_id=?
    - thread.replied    → UPDATE email_log SET replied_at=? WHERE nylas_thread_id=?
    - message.bounced   → UPDATE email_log SET bounced_at=? WHERE nylas_message_id=?

    Also TODO: Verify Nylas webhook signature from X-Nylas-Signature header.
    """
    # TODO: implement Nylas webhook processing
    return jsonify({"ok": True, "message": "Webhook received (Nylas integration pending)"}), 200


@app.route("/api/email/hub", methods=["GET"])
def api_email_hub_list():
    """Email Hub: return grouped email sends with optional filters."""
    q = request.args.get("q", "")
    job_id = request.args.get("job_id", "")
    days = request.args.get("days", "")
    status = request.args.get("status", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 25))
    try:
        job_id_int = int(job_id) if job_id else None
    except (ValueError, TypeError):
        job_id_int = None
    emails, total, stats = ats_db.get_email_hub_list(
        q=q, job_id=job_id_int, days=int(days) if days else None,
        status_filter=status, page=page, per_page=per_page
    )
    return jsonify({"emails": emails, "total": total, "stats": stats})


@app.route("/api/email/hub/<group_id>", methods=["GET"])
def api_email_hub_detail(group_id):
    """Email Hub detail: return all recipients for a batch or single email."""
    entries = ats_db.get_email_hub_detail(group_id)
    return jsonify({"entries": entries})


# ---------------------------------------------------------------------------
# ATS — Applicant Tracking System API
# ---------------------------------------------------------------------------

ats_db.init_db()
ats_db.init_users()

# ---- Employers ----

@app.route("/api/employers", methods=["GET"])
def api_list_employers():
    search = request.args.get("search", "")
    return jsonify({"employers": ats_db.list_employers(search)})


@app.route("/api/employers", methods=["POST"])
def api_create_employer():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    eid = ats_db.create_employer(
        name=name,
        website=data.get("website", ""),
        city=data.get("city", ""),
        state=data.get("state", ""),
        notes=data.get("notes", ""),
    )
    return jsonify({"ok": True, "id": eid})


@app.route("/api/employers/<int:eid>", methods=["GET"])
def api_get_employer(eid):
    emp = ats_db.get_employer(eid)
    if not emp:
        return jsonify({"error": "Not found"}), 404
    jobs = ats_db.list_jobs(employer_id=eid)
    return jsonify({"employer": emp, "jobs": jobs})


@app.route("/api/employers/<int:eid>", methods=["PUT"])
def api_update_employer(eid):
    data = request.get_json()
    ats_db.update_employer(eid, **data)
    return jsonify({"ok": True})


@app.route("/api/employers/<int:eid>", methods=["DELETE"])
def api_delete_employer(eid):
    ats_db.delete_employer(eid)
    return jsonify({"ok": True})


# ---- Jobs ----

@app.route("/api/jobs", methods=["GET"])
def api_list_jobs():
    status = request.args.get("status")
    employer_id = request.args.get("employer_id", type=int)
    practice_area = request.args.get("practice_area")
    search = request.args.get("search", "")
    return jsonify({"jobs": ats_db.list_jobs(status, employer_id, practice_area, search)})


@app.route("/api/jobs", methods=["POST"])
def api_create_job():
    data = request.get_json()
    employer_id = data.get("employer_id")
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if not employer_id:
        return jsonify({"error": "Employer is required"}), 400
    jid = ats_db.create_job(
        employer_id=employer_id,
        title=title,
        description=data.get("description", ""),
        location=data.get("location", ""),
        practice_area=data.get("practice_area", ""),
        specialty=data.get("specialty", ""),
        graduation_year_min=data.get("graduation_year_min"),
        graduation_year_max=data.get("graduation_year_max"),
        salary_min=data.get("salary_min"),
        salary_max=data.get("salary_max"),
        bar_required=data.get("bar_required", ""),
        status=data.get("status", "Active"),
    )
    return jsonify({"ok": True, "id": jid})


@app.route("/api/jobs/<int:jid>", methods=["GET"])
def api_get_job(jid):
    job = ats_db.get_job(jid)
    if not job:
        return jsonify({"error": "Not found"}), 404
    pipeline = ats_db.get_pipeline_for_job(jid)
    return jsonify({"job": job, "pipeline": pipeline})


@app.route("/api/jobs/<int:jid>", methods=["PUT"])
def api_update_job(jid):
    data = request.get_json()
    ats_db.update_job(jid, **data)
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:jid>", methods=["DELETE"])
def api_delete_job(jid):
    ats_db.delete_job(jid)
    return jsonify({"ok": True})


# ---- Pipeline ----

@app.route("/api/pipeline", methods=["GET"])
def api_get_pipeline():
    job_id = request.args.get("job_id", type=int)
    employer_id = request.args.get("employer_id", type=int)
    stage = request.args.get("stage")
    search = request.args.get("search", "")
    entries = ats_db.get_pipeline_all(job_id, employer_id, stage, search)
    return jsonify({"pipeline": entries, "stages": ats_db.PIPELINE_STAGES, "stage_colors": ats_db.STAGE_COLORS})


@app.route("/api/pipeline", methods=["POST"])
def api_add_to_pipeline():
    data = request.get_json()
    job_id = data.get("job_id")
    candidates = data.get("candidates", [])
    stage = data.get("stage", "Identified")
    notes = data.get("notes", "")
    placement_fee = data.get("placement_fee", 0)
    try:
        placement_fee = float(placement_fee or 0)
    except (ValueError, TypeError):
        placement_fee = 0
    if not job_id:
        return jsonify({"error": "Job is required"}), 400
    if not candidates:
        return jsonify({"error": "No candidates provided"}), 400

    results = []
    for c in candidates:
        attorney_id = c.get("attorney_id") or c.get("id", "")
        if not attorney_id:
            continue
        attorney_source = c.get("attorney_source") or c.get("source") or "fp"
        if attorney_source not in ("fp", "custom"):
            attorney_source = "fp"
        res = ats_db.add_to_pipeline(
            job_id=job_id,
            attorney_id=str(attorney_id),
            attorney_name=c.get("name", ""),
            attorney_firm=c.get("current_firm") or c.get("firm", ""),
            attorney_email=c.get("email", ""),
            stage=stage,
            notes=notes,
            placement_fee=placement_fee,
            attorney_source=attorney_source,
        )
        results.append({**res, "attorney_id": str(attorney_id), "name": c.get("name", "")})
    return jsonify({"ok": True, "results": results})


@app.route("/api/pipeline/<int:pid>/move", methods=["POST"])
def api_move_pipeline(pid):
    data = request.get_json()
    new_stage = data.get("stage", "")
    note = data.get("note", "")
    if not new_stage or new_stage not in ats_db.PIPELINE_STAGES:
        return jsonify({"error": "Invalid stage"}), 400
    ok = ats_db.move_pipeline_stage(pid, new_stage, note)
    if not ok:
        return jsonify({"error": "Pipeline entry not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/pipeline/<int:pid>/fee", methods=["POST"])
def api_update_pipeline_fee(pid):
    data = request.get_json()
    try:
        fee = float(data.get("placement_fee", 0))
    except (ValueError, TypeError):
        fee = 0
    ats_db.update_pipeline_fee(pid, fee)
    return jsonify({"ok": True})


@app.route("/api/pipeline/<int:pid>/notes", methods=["POST"])
def api_update_pipeline_notes(pid):
    data = request.get_json()
    ats_db.update_pipeline_notes(pid, data.get("notes", ""))
    return jsonify({"ok": True})


@app.route("/api/pipeline/<int:pid>", methods=["DELETE"])
def api_remove_from_pipeline(pid):
    ats_db.remove_from_pipeline(pid)
    return jsonify({"ok": True})


@app.route("/api/pipeline/check", methods=["POST"])
def api_check_pipeline_status():
    """Check if given attorney IDs are already in any pipeline."""
    data = request.get_json()
    attorney_ids = data.get("attorney_ids", [])
    status_map = ats_db.get_pipeline_status_for_attorneys(attorney_ids)
    return jsonify({"status": status_map})


# ---- Activity Log ----

@app.route("/api/activity", methods=["GET"])
def api_activity_log():
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    entries, total = ats_db.get_activity_log(limit, offset)
    return jsonify({"activities": entries, "total": total})


# ---- Pipeline Stats ----

@app.route("/api/pipeline/stats", methods=["GET"])
def api_pipeline_stats():
    job_id = request.args.get("job_id", type=int)
    stats = ats_db.get_pipeline_stats(job_id)
    result = {"stats": stats}
    if job_id:
        job = ats_db.get_job(job_id)
        result["job"] = job
    return jsonify(result)


# ===========================================================================
# Custom Records — Attorneys, Jobs, Firms
# ===========================================================================

# ---------------------------------------------------------------------------
# Custom Attorneys
# ---------------------------------------------------------------------------

@app.route("/api/custom/attorneys", methods=["POST"])
def api_create_custom_attorney():
    data = request.get_json(force=True)
    if not data.get("first_name") or not data.get("last_name"):
        return jsonify({"error": "first_name and last_name are required"}), 400
    new_id = ats_db.create_custom_attorney(data)
    attorney = ats_db.get_custom_attorney(new_id)
    return jsonify({"ok": True, "id": new_id, "attorney": attorney})


@app.route("/api/custom/attorneys", methods=["GET"])
def api_list_custom_attorneys():
    search = request.args.get("search", "")
    practice_area = request.args.get("practice_area", "")
    location = request.args.get("location", "")
    grad_year_min = request.args.get("grad_year_min", type=int)
    grad_year_max = request.args.get("grad_year_max", type=int)
    attorneys = ats_db.list_custom_attorneys(
        search=search,
        practice_area=practice_area,
        location=location,
        grad_year_min=grad_year_min,
        grad_year_max=grad_year_max,
    )
    return jsonify({"attorneys": attorneys, "total": len(attorneys)})


@app.route("/api/custom/attorneys/<int:atty_id>", methods=["GET"])
def api_get_custom_attorney(atty_id):
    attorney = ats_db.get_custom_attorney(atty_id)
    if not attorney:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"attorney": attorney})


@app.route("/api/custom/attorneys/<int:atty_id>", methods=["PUT"])
def api_update_custom_attorney(atty_id):
    data = request.get_json(force=True)
    ok = ats_db.update_custom_attorney(atty_id, data)
    if not ok:
        return jsonify({"error": "No valid fields to update"}), 400
    attorney = ats_db.get_custom_attorney(atty_id)
    return jsonify({"ok": True, "attorney": attorney})


@app.route("/api/custom/attorneys/<int:atty_id>", methods=["DELETE"])
def api_delete_custom_attorney(atty_id):
    ats_db.delete_custom_attorney(atty_id)
    return jsonify({"ok": True})


@app.route("/api/custom/attorneys/<int:atty_id>/resume", methods=["POST"])
def api_upload_resume(atty_id):
    if "resume" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["resume"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    resume_dir = os.path.join(os.path.dirname(__file__), "data", "resumes")
    os.makedirs(resume_dir, exist_ok=True)
    path = os.path.join(resume_dir, f"custom_{atty_id}.pdf")
    f.save(path)
    ats_db.update_custom_attorney(atty_id, {"resume_path": path})
    return jsonify({"ok": True, "resume_path": path})


# ---------------------------------------------------------------------------
# Custom Jobs
# ---------------------------------------------------------------------------

@app.route("/api/custom/jobs", methods=["POST"])
def api_create_custom_job():
    data = request.get_json(force=True)
    if not data.get("firm_name") or not data.get("job_title"):
        return jsonify({"error": "firm_name and job_title are required"}), 400
    new_id = ats_db.create_custom_job(data)
    job = ats_db.get_custom_job(new_id)
    return jsonify({"ok": True, "id": new_id, "job": job})


@app.route("/api/custom/jobs", methods=["GET"])
def api_list_custom_jobs():
    search = request.args.get("search", "")
    status = request.args.get("status")
    practice_area = request.args.get("practice_area")
    jobs = ats_db.list_custom_jobs(search=search, status=status, practice_area=practice_area)
    return jsonify({"jobs": jobs, "total": len(jobs)})


@app.route("/api/custom/jobs/<int:job_id>", methods=["GET"])
def api_get_custom_job(job_id):
    job = ats_db.get_custom_job(job_id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"job": job})


@app.route("/api/custom/jobs/<int:job_id>", methods=["PUT"])
def api_update_custom_job(job_id):
    data = request.get_json(force=True)
    ok = ats_db.update_custom_job(job_id, data)
    if not ok:
        return jsonify({"error": "No valid fields to update"}), 400
    job = ats_db.get_custom_job(job_id)
    return jsonify({"ok": True, "job": job})


@app.route("/api/custom/jobs/<int:job_id>", methods=["DELETE"])
def api_delete_custom_job(job_id):
    ats_db.delete_custom_job(job_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Custom Firms
# ---------------------------------------------------------------------------

@app.route("/api/custom/firms", methods=["POST"])
def api_create_custom_firm():
    data = request.get_json(force=True)
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400
    new_id = ats_db.create_custom_firm(data)
    firm = ats_db.get_custom_firm(new_id)
    return jsonify({"ok": True, "id": new_id, "firm": firm})


@app.route("/api/custom/firms", methods=["GET"])
def api_list_custom_firms():
    search = request.args.get("search", "")
    firms = ats_db.list_custom_firms(search=search)
    return jsonify({"firms": firms, "total": len(firms)})


@app.route("/api/custom/firms/<int:firm_id>", methods=["GET"])
def api_get_custom_firm(firm_id):
    firm = ats_db.get_custom_firm(firm_id)
    if not firm:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"firm": firm})


@app.route("/api/custom/firms/<int:firm_id>", methods=["PUT"])
def api_update_custom_firm(firm_id):
    data = request.get_json(force=True)
    ok = ats_db.update_custom_firm(firm_id, data)
    if not ok:
        return jsonify({"error": "No valid fields to update"}), 400
    firm = ats_db.get_custom_firm(firm_id)
    return jsonify({"ok": True, "firm": firm})


@app.route("/api/custom/firms/<int:firm_id>", methods=["DELETE"])
def api_delete_custom_firm(firm_id):
    ats_db.delete_custom_firm(firm_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Record Tags & Notes (any record_type, record_source, record_id)
# ---------------------------------------------------------------------------

@app.route("/api/records/<record_type>/<record_source>/<record_id>/tags", methods=["GET"])
def api_get_record_tags(record_type, record_source, record_id):
    tags = ats_db.get_record_tags(record_type, record_source, record_id)
    return jsonify({"tags": tags})


@app.route("/api/records/<record_type>/<record_source>/<record_id>/tags", methods=["POST"])
def api_add_record_tag(record_type, record_source, record_id):
    data = request.get_json(force=True)
    tag = (data.get("tag") or "").strip()
    if not tag:
        return jsonify({"error": "tag is required"}), 400
    ats_db.add_record_tag(record_type, record_source, record_id, tag)
    tags = ats_db.get_record_tags(record_type, record_source, record_id)
    return jsonify({"ok": True, "tags": tags})


@app.route("/api/records/<record_type>/<record_source>/<record_id>/tags/<int:tag_id>", methods=["DELETE"])
def api_remove_record_tag(record_type, record_source, record_id, tag_id):
    ats_db.remove_record_tag(tag_id)
    return jsonify({"ok": True})


@app.route("/api/records/<record_type>/<record_source>/<record_id>/notes", methods=["GET"])
def api_get_record_notes(record_type, record_source, record_id):
    notes = ats_db.get_record_notes(record_type, record_source, record_id)
    return jsonify({"notes": notes})


@app.route("/api/records/<record_type>/<record_source>/<record_id>/notes", methods=["POST"])
def api_add_record_note(record_type, record_source, record_id):
    data = request.get_json(force=True)
    note_text = (data.get("note_text") or "").strip()
    if not note_text:
        return jsonify({"error": "note_text is required"}), 400
    note_id = ats_db.add_record_note(record_type, record_source, record_id, note_text)
    notes = ats_db.get_record_notes(record_type, record_source, record_id)
    return jsonify({"ok": True, "note_id": note_id, "notes": notes})


@app.route("/api/records/<record_type>/<record_source>/<record_id>/notes/<int:note_id>", methods=["DELETE"])
def api_remove_record_note(record_type, record_source, record_id, note_id):
    ats_db.remove_record_note(note_id)
    return jsonify({"ok": True})


# ---- Attorney search for pipeline add ----

@app.route("/api/attorneys/search", methods=["GET"])
def api_search_attorneys():
    """Search attorneys by name for adding to pipeline."""
    q = request.args.get("q", "").strip().lower()
    if not q or len(q) < 2:
        return jsonify({"results": []})
    # Search in the loaded DataFrame
    mask = (
        ATTORNEYS_DF["first_name"].str.lower().str.contains(q, na=False) |
        ATTORNEYS_DF["last_name"].str.lower().str.contains(q, na=False) |
        (ATTORNEYS_DF["first_name"].str.lower() + " " + ATTORNEYS_DF["last_name"].str.lower()).str.contains(q, na=False)
    )
    matches = ATTORNEYS_DF[mask].head(20)
    results = []
    for _, row in matches.iterrows():
        results.append({
            "id": row.get("id", ""),
            "name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
            "firm": row.get("firm_name", ""),
            "graduation_year": row.get("graduationYear", ""),
            "law_school": row.get("lawSchool", ""),
            "email": row.get("email", ""),
            "location": row.get("location", ""),
            "specialty": row.get("specialty", ""),
        })
    return jsonify({"results": results})


# ---- Single attorney lookup ----

@app.route("/api/attorneys/<attorney_id>", methods=["GET"])
def api_get_attorney(attorney_id):
    """Return full profile for a single attorney by ID."""
    if ATTORNEYS_DF.empty:
        return jsonify({"error": "No attorney data"}), 404
    match = ATTORNEYS_DF[ATTORNEYS_DF["id"].astype(str) == str(attorney_id)]
    if match.empty:
        return jsonify({"error": "Attorney not found"}), 404
    att_dict = match.iloc[0].to_dict()
    att_dict["attorneyBio"] = get_attorney_full_bio(att_dict.get("id", ""))
    return jsonify({"attorney": _serialize_candidate(att_dict)})


@app.route("/api/attorneys/<attorney_id>/full-profile", methods=["GET"])
def api_attorney_full_profile(attorney_id):
    """Return enriched attorney profile including pipeline entries and email history."""
    if ATTORNEYS_DF.empty:
        return jsonify({"error": "No attorney data"}), 404
    match = ATTORNEYS_DF[ATTORNEYS_DF["id"].astype(str) == str(attorney_id)]
    if match.empty:
        return jsonify({"error": "Attorney not found"}), 404
    att_dict = match.iloc[0].to_dict()
    att_dict["attorneyBio"] = get_attorney_full_bio(att_dict.get("id", ""))
    attorney = _serialize_candidate(att_dict)
    pipeline_entries = ats_db.get_attorney_pipeline_entries(attorney_id, attorney_source="fp")
    email_history = ats_db.get_email_history_by_attorney(attorney_id)
    employment = ats_db.get_attorney_employment(attorney_id)
    return jsonify({
        "attorney": attorney,
        "pipeline": pipeline_entries,
        "emails": email_history,
        "employment": employment,
    })


@app.route("/api/attorneys/<attorney_id>/employment", methods=["GET"])
def api_attorney_employment(attorney_id):
    """Return employment history for an attorney (stub — empty until API connected)."""
    return jsonify({"employment": ats_db.get_attorney_employment(attorney_id)})


# ---------------------------------------------------------------------------
# Job Search API
# ---------------------------------------------------------------------------

JOB_SEARCH_SYSTEM = """You are a search query parser for legal job listings. Given a natural language query, extract structured search parameters.

Return ONLY valid JSON (no markdown fences):
{
  "keywords": ["keyword1", "keyword2"],
  "practice_areas": ["Corporate", "Litigation"],
  "specialties": ["M&A", "Fund Formation"],
  "locations": ["New York", "Boston"],
  "min_years": null,
  "max_years": null,
  "firm_names": ["Kirkland"],
  "status": "Open",
  "summary": "Brief summary of the search"
}

Rules:
- Extract as many relevant parameters as possible from the query
- keywords should be substantive legal terms found in the query
- practice_areas should use standard legal terminology (Corporate, Litigation, Real Estate, Banking, Tax, IP, Labor, ERISA, Antitrust, Environmental, Energy, Healthcare, Private Equity, Venture Capital, Fund Formation, Bankruptcy, Restructuring)
- specialties are more specific sub-areas (M&A, Lending, Securitization, etc.)
- locations should be city names
- min_years/max_years are experience requirements (integers or null)
- firm_names are specific law firm names mentioned
- status is "Open" unless user specifically asks for closed/all jobs (use null for all)
- summary is a 1-sentence description of what's being searched for
- Respond with valid JSON only"""


def _serialize_job(row):
    """Serialize a jobs DataFrame row to a dict."""
    return {
        "id": str(row.get("FP ID", "")),
        "firm_name": row.get("Firm Name", ""),
        "job_title": row.get("Job Title", ""),
        "job_location": row.get("Job Location", ""),
        "job_description": row.get("Job Description", ""),
        "practice_areas": row.get("Practice Areas", ""),
        "specialty": row.get("Specialty", ""),
        "min_years": row.get("MinYrs", ""),
        "max_years": row.get("MaxYrs", ""),
        "status": row.get("Status", ""),
        "closed_date": row.get("Closed Date", ""),
    }


def _parse_job_query_with_claude(query):
    """Use Claude to parse a natural language job search query into structured params."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            temperature=0,
            system=JOB_SEARCH_SYSTEM,
            messages=[{"role": "user", "content": query}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except Exception as e:
        print(f"[Job search parse error] {e}")
        return None


def _keyword_parse_job_query(query):
    """Fallback: extract search params from query using keyword matching."""
    q = query.lower()

    pa_map = {
        "corporate": "Corporate", "m&a": "M&A", "mergers": "M&A",
        "litigation": "Litigation", "real estate": "Real Estate",
        "banking": "Banking", "finance": "Finance", "tax": "Tax",
        "ip": "IP", "intellectual property": "IP", "patent": "IP",
        "labor": "Labor", "employment": "Labor",
        "erisa": "ERISA", "benefits": "ERISA",
        "antitrust": "Antitrust", "environmental": "Environmental",
        "energy": "Energy", "healthcare": "Healthcare",
        "private equity": "Private Equity", "venture capital": "Venture Capital",
        "fund formation": "Fund Formation", "bankruptcy": "Bankruptcy",
        "restructuring": "Restructuring",
    }
    practice_areas = []
    for kw, pa in pa_map.items():
        if kw in q and pa not in practice_areas:
            practice_areas.append(pa)

    cities = [
        "new york", "boston", "chicago", "los angeles", "san francisco",
        "washington", "houston", "dallas", "austin", "seattle", "miami",
        "atlanta", "denver", "philadelphia", "charlotte", "minneapolis",
    ]
    locations = [c.title() for c in cities if c in q]

    min_years = max_years = None
    m = re.search(r"(\d+)\s*[-\u2013to]+\s*(\d+)\s*years?", q)
    if m:
        min_years, max_years = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d+)\+?\s*years?", q)
        if m:
            min_years = int(m.group(1))

    # Extract firm names (look for known patterns)
    firm_names = []
    llp_match = re.findall(r"([\w &,.']+(?:LLP|LLC|PC|L\.L\.P\.|P\.C\.))", query, re.IGNORECASE)
    firm_names.extend([f.strip() for f in llp_match])

    stop = {
        "a", "an", "the", "in", "at", "for", "of", "and", "or", "with",
        "looking", "find", "search", "job", "jobs", "position", "positions",
        "role", "roles", "seeking", "need", "want", "attorney", "lawyer",
        "associate", "partner", "counsel", "level", "senior", "junior",
        "mid", "open", "all", "any", "show", "me", "list",
    }
    keywords = [w for w in q.split() if w not in stop and len(w) > 2]

    return {
        "keywords": keywords,
        "practice_areas": practice_areas,
        "specialties": [],
        "locations": locations,
        "min_years": min_years,
        "max_years": max_years,
        "firm_names": firm_names,
        "status": "Open",
        "summary": f"Searching for: {query}",
    }


def _search_jobs(params):
    """Search JOBS_DF using structured params. Returns list of serialized jobs."""
    if JOBS_DF.empty:
        return []

    df = JOBS_DF.copy()

    # Status filter
    status = params.get("status")
    if status:
        df = df[df["Status"].str.lower() == status.lower()]

    # Firm filter
    firm_names = params.get("firm_names", [])
    if firm_names:
        mask = pd.Series(False, index=df.index)
        for fn in firm_names:
            mask |= df["Firm Name"].str.lower().str.contains(
                fn.lower(), regex=False, na=False)
        df = df[mask]

    # Location filter
    locations = params.get("locations", [])
    if locations:
        mask = pd.Series(False, index=df.index)
        for loc in locations:
            mask |= df["Job Location"].str.lower().str.contains(
                loc.lower(), regex=False, na=False)
        df = df[mask]

    # Practice area + specialty filter
    practice_areas = params.get("practice_areas", [])
    specialties = params.get("specialties", [])
    all_areas = practice_areas + specialties
    if all_areas:
        mask = pd.Series(False, index=df.index)
        for pa in all_areas:
            mask |= df["Practice Areas"].str.lower().str.contains(
                pa.lower(), regex=False, na=False)
            mask |= df["Specialty"].str.lower().str.contains(
                pa.lower(), regex=False, na=False)
        df = df[mask]

    # Experience filter
    min_yrs = params.get("min_years")
    max_yrs = params.get("max_years")
    if min_yrs is not None or max_yrs is not None:
        df["_min"] = pd.to_numeric(df["MinYrs"], errors="coerce")
        df["_max"] = pd.to_numeric(df["MaxYrs"], errors="coerce")
        if min_yrs is not None:
            yrs_mask = (df["_max"].isna()) | (df["_max"] >= min_yrs)
            df = df[yrs_mask]
        if max_yrs is not None:
            yrs_mask = (df["_min"].isna()) | (df["_min"] <= max_yrs)
            df = df[yrs_mask]
        df = df.drop(columns=["_min", "_max"], errors="ignore")

    # Score by keyword relevance
    keywords = params.get("keywords", [])
    all_terms = keywords + [pa.lower() for pa in all_areas]

    if all_terms:
        combined = (
            df.get("Job Title", pd.Series("", index=df.index)).fillna("") + " " +
            df.get("Job Description", pd.Series("", index=df.index)).fillna("") + " " +
            df.get("Practice Areas", pd.Series("", index=df.index)).fillna("") + " " +
            df.get("Specialty", pd.Series("", index=df.index)).fillna("")
        ).str.lower()

        scores = pd.Series(0, index=df.index)
        for term in all_terms:
            scores += combined.str.contains(
                term.lower(), regex=False, na=False).astype(int)

        df["_score"] = scores
        if keywords:
            df = df[df["_score"] > 0]
        df = df.sort_values("_score", ascending=False)
        df = df.drop(columns=["_score"], errors="ignore")

    MAX_JOB_RESULTS = 50
    df = df.head(MAX_JOB_RESULTS)

    return [_serialize_job(row) for _, row in df.iterrows()]


def _serialize_custom_job(cj):
    """Normalize a custom job dict to the same shape as _serialize_job."""
    return {
        "id": f"custom_{cj['id']}",
        "firm_name": cj.get("firm_name", ""),
        "job_title": cj.get("job_title", ""),
        "job_location": cj.get("location", ""),
        "job_description": cj.get("job_description", ""),
        "practice_areas": cj.get("practice_areas", ""),
        "specialty": cj.get("specialty", ""),
        "min_years": cj.get("min_years", ""),
        "max_years": cj.get("max_years", ""),
        "status": cj.get("status", "Open"),
        "closed_date": "",
        "source": "custom",
        "contact_name": cj.get("contact_name", ""),
        "contact_email": cj.get("contact_email", ""),
        "confidential": bool(cj.get("confidential", 0)),
        "salary_min": cj.get("salary_min"),
        "salary_max": cj.get("salary_max"),
    }


@app.route("/api/jobsearch", methods=["POST"])
def job_search():
    data = request.get_json()
    query = data.get("query", "").strip()
    use_ai = data.get("use_ai", True)
    source_filter = data.get("source", "all")

    if not query:
        return jsonify({"error": "Please describe what you're looking for."}), 400

    if JOBS_DF.empty and source_filter != "custom":
        # Still allow custom-only search
        pass

    # Parse query
    params = None
    ai_used = False
    if use_ai and ANTHROPIC_API_KEY and not JOBS_DF.empty:
        params = _parse_job_query_with_claude(query)
        if params:
            ai_used = True
    if not params:
        params = _keyword_parse_job_query(query)

    # Search FP jobs
    jobs = _search_jobs(params) if source_filter != "custom" else []
    for j in jobs:
        j.setdefault("source", "fp")

    # Merge custom jobs
    if source_filter != "fp":
        custom_search = query
        custom_pa = params.get("practice_areas", [])
        cj_list = ats_db.list_custom_jobs(
            search=custom_search,
            practice_area=custom_pa[0] if custom_pa else None,
        )
        for cj in cj_list:
            jobs.append(_serialize_custom_job(cj))

    summary = params.get("summary", f"Showing results for: {query}")

    # Build chat response
    if jobs:
        chat = f"I found **{len(jobs)}** job{'s' if len(jobs) != 1 else ''} matching your search"
        if params.get("practice_areas"):
            chat += f" in **{', '.join(params['practice_areas'])}**"
        if params.get("locations"):
            chat += f" located in **{', '.join(params['locations'])}**"
        chat += "."

        # Summarize top firms
        firms = {}
        for j in jobs[:20]:
            fn = j["firm_name"]
            if fn not in firms:
                firms[fn] = 0
            firms[fn] += 1
        top_firms = sorted(firms.items(), key=lambda x: -x[1])[:5]
        if top_firms:
            firm_list = ", ".join(f"**{f}** ({c})" for f, c in top_firms)
            chat += f"\n\nTop firms: {firm_list}"

        if params.get("min_years") or params.get("max_years"):
            yr_min = params.get("min_years", "")
            yr_max = params.get("max_years", "")
            if yr_min and yr_max:
                chat += f"\n\nExperience range: **{yr_min}-{yr_max} years**"
            elif yr_min:
                chat += f"\n\nMinimum experience: **{yr_min}+ years**"
    else:
        chat = ("No jobs found matching your criteria. Try broadening your search "
                "— for example, remove location or experience requirements.")

    return jsonify({
        "query": query,
        "summary": summary,
        "chat_response": chat,
        "jobs": jobs,
        "total": len(jobs),
        "total_jobs": len(JOBS_DF),
        "ai_used": ai_used,
        "params": {
            "practice_areas": params.get("practice_areas", []),
            "locations": params.get("locations", []),
            "min_years": params.get("min_years"),
            "max_years": params.get("max_years"),
        },
    })


@app.route("/api/jobsearch/add-to-ats", methods=["POST"])
def job_add_to_ats():
    """Add a CSV job to the ATS (creates employer + job record)."""
    data = request.get_json()
    job_data = data.get("job")
    if not job_data:
        return jsonify({"error": "No job data provided"}), 400

    firm_name = job_data.get("firm_name", "").strip()
    if not firm_name:
        return jsonify({"error": "Firm name required"}), 400

    # Find or create employer
    employers = ats_db.list_employers(firm_name)
    employer_id = None
    for e in employers:
        if e["name"].lower() == firm_name.lower():
            employer_id = e["id"]
            break
    if not employer_id:
        employer_id = ats_db.create_employer(name=firm_name)

    # Parse location for first city
    loc = job_data.get("job_location", "")

    job_id = ats_db.create_job(
        employer_id=employer_id,
        title=job_data.get("job_title", ""),
        description=job_data.get("job_description", ""),
        location=loc,
        practice_area=job_data.get("practice_areas", ""),
        specialty=job_data.get("specialty", ""),
        graduation_year_min=None,
        graduation_year_max=None,
        salary_min=None,
        salary_max=None,
        bar_required="",
        status="Active",
    )

    return jsonify({
        "ok": True,
        "employer_id": employer_id,
        "job_id": job_id,
        "firm_name": firm_name,
    })


# ---------------------------------------------------------------------------
# Firms API (from firms.csv + CRM data in SQLite)
# ---------------------------------------------------------------------------

PRACTICE_AREA_COLUMNS = [
    "Antitrust", "Banking", "Bankruptcy", "Corporate", "Data Privacy", "ERISA",
    "Energy", "Entertainment", "Environmental", "FDA", "Government", "Health Care",
    "Insurance", "Intellectual Property", "International Trade", "Labor & Employment",
    "Litigation", "Media", "Real Estate", "Tax", "Telecommunications",
    "Transportation", "Trusts & Estates",
]


def _get_active_firm_names():
    """Return a set of firm names (lowered) that have pipeline activity.
    Checks pipeline.attorney_firm and employer names (via pipeline -> jobs -> employers).
    """
    active = set()
    try:
        conn = ats_db.get_db()
        # Direct attorney_firm values from pipeline
        rows = conn.execute(
            "SELECT DISTINCT attorney_firm FROM pipeline WHERE attorney_firm IS NOT NULL AND attorney_firm != ''"
        ).fetchall()
        for r in rows:
            active.add(r["attorney_firm"].strip().lower())
        # Employer names via pipeline -> jobs -> employers
        rows2 = conn.execute(
            """SELECT DISTINCT e.name FROM pipeline p
               JOIN jobs j ON p.job_id = j.id
               JOIN employers e ON j.employer_id = e.id
               WHERE e.name IS NOT NULL AND e.name != ''"""
        ).fetchall()
        for r in rows2:
            active.add(r["name"].strip().lower())
        conn.close()
    except Exception as e:
        print(f"[_get_active_firm_names] {e}")
    return active


def _firm_to_dict(row):
    """Convert a FIRMS_DF row to a JSON-friendly dict."""
    d = {
        "fp_id": str(row.get("FP ID", "")),
        "name": row.get("Name", ""),
        "website": row.get("Website", ""),
        "partners": row.get("Partners", ""),
        "counsel": row.get("Counsel", ""),
        "associates": row.get("Associates", ""),
        "offices": row.get("Firm Office Locations", ""),
        "total_attorneys": row.get("Total Attorneys", ""),
        "ppp": row.get("PPP", ""),
        "top1": row.get("Practice Area Top 1", ""),
        "top2": row.get("Practice Area Top 2", ""),
        "top3": row.get("Practice Area Top 3", ""),
    }
    # Practice area breakdown
    areas = {}
    for col in PRACTICE_AREA_COLUMNS:
        val = row.get(col, "")
        try:
            n = int(val) if val else 0
        except ValueError:
            n = 0
        if n > 0:
            areas[col] = n
    d["practice_areas"] = areas
    return d


@app.route("/api/firms")
def api_firms():
    if FIRMS_DF.empty:
        return jsonify({"firms": [], "total": 0})
    q = request.args.get("search", "").strip().lower()
    source_filter = request.args.get("source", "all")
    df = FIRMS_DF.copy()
    if q:
        mask = df["Name"].str.lower().str.contains(q, na=False)
        df = df[mask]
    active_names = _get_active_firm_names()
    all_statuses = ats_db.list_all_firm_statuses()
    firms = []
    if source_filter != "custom":
        for _, row in df.iterrows():
            d = _firm_to_dict(row)
            d["has_activity"] = d["name"].strip().lower() in active_names
            # Top matches count from cache (0 if not yet computed)
            resolved = _resolve_dna_firm_name(d["name"])
            cached = _top_candidates_cache.get(resolved, []) if resolved else []
            d["top_matches"] = sum(1 for c in cached if c["match_score"] >= 60)
            d["source"] = "fp"
            st = all_statuses.get(d["name"].strip().lower())
            d["client_status"] = st["client_status"] if st else "Reference Only"
            d["pinned"] = bool(st.get("pinned")) if st else False
            d["priority"] = st["priority"] if st else "Normal"
            firms.append(d)
    if source_filter != "fp":
        custom_firms_list = ats_db.list_custom_firms(search=q)
        for cf in custom_firms_list:
            cf["has_activity"] = False
            cf["top_matches"] = 0
            cf["offices"] = cf.get("office_locations", "")
            cf["ppp_display"] = f"${cf['ppp']:,}" if cf.get("ppp") else ""
            st = all_statuses.get((cf.get("name") or "").strip().lower())
            cf["client_status"] = st["client_status"] if st else "Reference Only"
            cf["pinned"] = bool(st.get("pinned")) if st else False
            cf["priority"] = st["priority"] if st else "Normal"
            firms.append(cf)
    # Sort: pinned Active Clients first, then active pipeline, then alphabetical
    STATUS_ORDER = {"Active Client": 0, "Prospect": 1, "Past Client": 2, "Reference Only": 3}
    firms.sort(key=lambda f: (
        not f.get("pinned", False),
        STATUS_ORDER.get(f.get("client_status", "Reference Only"), 9),
        not f.get("has_activity", False),
        f["name"].lower()
    ))
    return jsonify({"firms": firms, "total": len(firms)})


@app.route("/api/firms/search", methods=["POST"])
def api_firms_search():
    """AI-powered firm search. Uses Claude to parse natural language query."""
    data = request.get_json(force=True)
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Query is required"}), 400
    if FIRMS_DF.empty:
        return jsonify({"firms": [], "total": 0})
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "AI search not configured (no API key)"}), 500

    system = """You are a firm search assistant. Given a natural language query about law firms, extract structured search parameters.
Return ONLY valid JSON (no markdown fences):
{
  "practice_areas": ["Corporate", "Litigation"],
  "locations": ["New York", "Chicago"],
  "min_attorneys": null,
  "max_attorneys": null,
  "has_submissions": false,
  "firm_names": []
}
Rules:
- practice_areas should match these columns when possible: """ + ", ".join(PRACTICE_AREA_COLUMNS) + """
- locations are city names or state names
- min_attorneys/max_attorneys are integers or null
- has_submissions means the firm has pipeline activity
- firm_names is a list of specific firm names mentioned
- All fields are optional; use null or empty for unspecified"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        params = json.loads(text)
    except Exception as e:
        print(f"[Firm AI search error] {e}")
        return jsonify({"error": "AI parsing failed"}), 500

    active_names = _get_active_firm_names()
    df = FIRMS_DF.copy()

    # Filter by firm names
    firm_names = params.get("firm_names") or []
    if firm_names:
        pattern = "|".join(re.escape(n) for n in firm_names)
        df = df[df["Name"].str.contains(pattern, case=False, na=False)]

    # Filter by locations
    locations = params.get("locations") or []
    if locations:
        loc_pattern = "|".join(re.escape(l) for l in locations)
        df = df[df["Firm Office Locations"].str.contains(loc_pattern, case=False, na=False)]

    # Filter by attorney count
    min_atty = params.get("min_attorneys")
    max_atty = params.get("max_attorneys")
    if min_atty is not None or max_atty is not None:
        nums = pd.to_numeric(df["Total Attorneys"].str.replace(",", ""), errors="coerce")
        if min_atty is not None:
            df = df[nums >= min_atty]
            nums = nums[df.index]
        if max_atty is not None:
            df = df[nums <= max_atty]

    # Filter by practice areas
    practice_areas = params.get("practice_areas") or []
    if practice_areas:
        for pa in practice_areas:
            if pa in df.columns:
                vals = pd.to_numeric(df[pa], errors="coerce").fillna(0)
                df = df[vals > 0]

    # Filter by has_submissions
    if params.get("has_submissions"):
        df = df[df["Name"].str.lower().str.strip().isin(active_names)]

    firms = []
    for _, row in df.iterrows():
        d = _firm_to_dict(row)
        d["has_activity"] = d["name"].strip().lower() in active_names
        d["source"] = "fp"
        firms.append(d)

    # Merge custom firms
    custom_query = " ".join(firm_names + locations + practice_areas) if (firm_names or locations or practice_areas) else ""
    custom_firms_list = ats_db.list_custom_firms(search=custom_query)
    for cf in custom_firms_list:
        cf["has_activity"] = False
        cf["top_matches"] = 0
        # Normalize shape to match FP firms
        cf["offices"] = cf.get("office_locations", "")
        cf["ppp_display"] = f"${cf['ppp']:,}" if cf.get("ppp") else ""
        firms.append(cf)

    firms.sort(key=lambda f: (f.get("source", "fp") != "custom", not f["has_activity"], f["name"].lower()))
    return jsonify({"firms": firms, "total": len(firms)})


@app.route("/api/firms/<firm_id>/jobs")
def api_firm_jobs(firm_id):
    """Get jobs from JOBS_DF where Firm Name matches this firm."""
    if FIRMS_DF.empty:
        return jsonify({"error": "No firms data"}), 404
    match = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
    if match.empty:
        return jsonify({"error": "Firm not found"}), 404
    firm_name = match.iloc[0].get("Name", "")
    jobs = []
    if not JOBS_DF.empty and firm_name:
        mask = JOBS_DF["Firm Name"].str.lower() == firm_name.lower()
        for _, row in JOBS_DF[mask].iterrows():
            jobs.append(_serialize_job(row))
    return jsonify({"jobs": jobs})


@app.route("/api/firms/<firm_id>/pipeline")
def api_firm_pipeline(firm_id):
    """Get pipeline candidates where attorney_firm matches or employer.name matches."""
    if FIRMS_DF.empty:
        return jsonify({"error": "No firms data"}), 404
    match = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
    if match.empty:
        return jsonify({"error": "Firm not found"}), 404
    firm_name = match.iloc[0].get("Name", "")
    candidates = []
    try:
        conn = ats_db.get_db()
        rows = conn.execute(
            """SELECT DISTINCT p.*, j.title as job_title, e.name as employer_name
               FROM pipeline p
               JOIN jobs j ON p.job_id = j.id
               LEFT JOIN employers e ON j.employer_id = e.id
               WHERE LOWER(p.attorney_firm) = LOWER(?)
                  OR LOWER(e.name) = LOWER(?)
               ORDER BY p.updated_at DESC""",
            (firm_name, firm_name),
        ).fetchall()
        conn.close()
        candidates = [dict(r) for r in rows]
    except Exception as e:
        print(f"[Firm pipeline error] {e}")
    return jsonify({"candidates": candidates})


@app.route("/api/firms/my-clients")
def api_firms_my_clients():
    """Return Active Client + Prospect firms enriched with job/pipeline/task data."""
    my_firms = ats_db.get_my_client_firms()
    enriched = []
    for fs in my_firms:
        firm_name = fs.get("firm_name", "")
        fp_id = fs.get("firm_fp_id", "")
        # Resolve firm data from FIRMS_DF
        firm_data = {}
        if fp_id and not FIRMS_DF.empty:
            m = FIRMS_DF[FIRMS_DF["FP ID"] == str(fp_id)]
            if not m.empty:
                firm_data = _firm_to_dict(m.iloc[0])
        elif firm_name and not FIRMS_DF.empty:
            m2 = FIRMS_DF[FIRMS_DF["Name"].str.lower() == firm_name.lower()]
            if not m2.empty:
                firm_data = _firm_to_dict(m2.iloc[0])
                if not fp_id:
                    fp_id = firm_data.get("fp_id", "")
        job_count = 0
        pipeline_count = 0
        interviewing_count = 0
        next_task_title = None
        next_task_due = None
        try:
            conn = ats_db.get_db()
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM jobs j
                   JOIN employers e ON j.employer_id = e.id
                   WHERE LOWER(e.name) = LOWER(?) AND LOWER(j.status) = 'active'""",
                (firm_name,)
            ).fetchone()
            if row:
                job_count = row["cnt"]
            row2 = conn.execute(
                """SELECT COUNT(*) as cnt FROM pipeline p
                   JOIN jobs j ON p.job_id = j.id
                   JOIN employers e ON j.employer_id = e.id
                   WHERE LOWER(e.name) = LOWER(?)""",
                (firm_name,)
            ).fetchone()
            if row2:
                pipeline_count = row2["cnt"]
            row3 = conn.execute(
                """SELECT COUNT(*) as cnt FROM pipeline p
                   JOIN jobs j ON p.job_id = j.id
                   JOIN employers e ON j.employer_id = e.id
                   WHERE LOWER(e.name) = LOWER(?) AND LOWER(p.stage) LIKE '%interview%'""",
                (firm_name,)
            ).fetchone()
            if row3:
                interviewing_count = row3["cnt"]
            nt = conn.execute(
                """SELECT title, due_date FROM tasks
                   WHERE LOWER(firm_name) = LOWER(?) AND status != 'Completed'
                   ORDER BY due_date ASC LIMIT 1""",
                (firm_name,)
            ).fetchone()
            if nt:
                next_task_title = nt["title"]
                next_task_due = nt["due_date"]
            conn.close()
        except Exception as e:
            print(f"[my-clients enrich] {e}")
        entry = {**fs}
        entry["total_attorneys"] = firm_data.get("total_attorneys", "")
        entry["ppp"] = firm_data.get("ppp", "")
        entry["top1"] = firm_data.get("top1", "")
        entry["top2"] = firm_data.get("top2", "")
        entry["top3"] = firm_data.get("top3", "")
        entry["fp_id"] = fp_id or firm_data.get("fp_id", "")
        entry["active_jobs"] = job_count
        entry["pipeline_count"] = pipeline_count
        entry["interviewing_count"] = interviewing_count
        entry["next_task_title"] = next_task_title
        entry["next_task_due"] = next_task_due
        enriched.append(entry)
    return jsonify({"firms": enriched})


@app.route("/api/firms/recently-viewed")
def api_firms_recently_viewed():
    """Return recently viewed firms."""
    firms = ats_db.get_recently_viewed(limit=8)
    return jsonify({"firms": firms})


@app.route("/api/firms/need-followup")
def api_firms_need_followup():
    """Return Active Client firms with no activity in 7+ days."""
    try:
        conn = ats_db.get_db()
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        rows = conn.execute(
            """SELECT firm_name, firm_fp_id, last_contact_date, updated_at
               FROM firm_status
               WHERE client_status = 'Active Client'
               AND (last_contact_date IS NULL OR last_contact_date < ? OR last_contact_date = '')
               AND (updated_at IS NULL OR updated_at < ?)
               ORDER BY last_contact_date ASC""",
            (cutoff[:10], cutoff)
        ).fetchall()
        conn.close()
        return jsonify({"firms": [dict(r) for r in rows], "count": len(rows)})
    except Exception as e:
        return jsonify({"firms": [], "count": 0, "error": str(e)})


@app.route("/api/firms/<firm_id>/status", methods=["PUT"])
def api_firm_update_status(firm_id):
    """Update client_status, priority, owner, notes, next_follow_up for a firm."""
    data = request.get_json(force=True)
    firm_name = (data.get("firm_name") or "").strip()
    if not firm_name and not FIRMS_DF.empty:
        m = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
        if not m.empty:
            firm_name = str(m.iloc[0].get("Name", ""))
    if not firm_name:
        return jsonify({"error": "firm_name required"}), 400
    ats_db.upsert_firm_status(
        firm_name=firm_name,
        firm_fp_id=firm_id if firm_id not in ("", "undefined") else None,
        client_status=data.get("client_status"),
        owner=data.get("owner"),
        priority=data.get("priority"),
        last_contact_date=data.get("last_contact_date"),
        next_follow_up=data.get("next_follow_up"),
        notes=data.get("notes"),
        pinned=data.get("pinned"),
    )
    return jsonify({"ok": True})


@app.route("/api/firms/<firm_id>/pin", methods=["PUT"])
def api_firm_pin(firm_id):
    """Toggle pin state for a firm."""
    data = request.get_json(force=True)
    firm_name = (data.get("firm_name") or "").strip()
    if not firm_name and not FIRMS_DF.empty:
        m = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
        if not m.empty:
            firm_name = str(m.iloc[0].get("Name", ""))
    if not firm_name:
        return jsonify({"error": "firm_name required"}), 400
    ats_db.upsert_firm_status(
        firm_name=firm_name,
        firm_fp_id=firm_id if firm_id not in ("", "undefined") else None,
        pinned=data.get("pinned", True)
    )
    return jsonify({"ok": True})


@app.route("/api/firms/<firm_id>/mark-active", methods=["POST"])
def api_firm_mark_active(firm_id):
    """Quick-mark a firm as Active Client."""
    data = request.get_json(force=True)
    firm_name = (data.get("firm_name") or "").strip()
    if not firm_name and not FIRMS_DF.empty:
        m = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
        if not m.empty:
            firm_name = str(m.iloc[0].get("Name", ""))
    if not firm_name:
        return jsonify({"error": "firm_name required"}), 400
    ats_db.upsert_firm_status(
        firm_name=firm_name,
        firm_fp_id=firm_id if firm_id not in ("", "undefined") else None,
        client_status="Active Client"
    )
    return jsonify({"ok": True})


@app.route("/api/firms/<firm_id>/relationship-timeline")
def api_firm_relationship_timeline(firm_id):
    """Return CRM relationship timeline for a firm (notes, tasks, jobs, pipeline events)."""
    firm_name = ""
    if not FIRMS_DF.empty:
        m = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
        if not m.empty:
            firm_name = str(m.iloc[0].get("Name", ""))
    events = []
    try:
        conn = ats_db.get_db()
        # Notes
        for r in conn.execute(
            "SELECT note_text as text, created_at FROM firm_notes WHERE firm_id = ? ORDER BY created_at DESC LIMIT 50",
            (firm_id,)
        ).fetchall():
            events.append({"type": "note", "text": r["text"], "date": r["created_at"], "icon": "📝"})
        # Tasks
        for r in conn.execute(
            """SELECT title, due_date, status FROM tasks
               WHERE LOWER(firm_name) = LOWER(?) OR firm_fp_id = ?
               ORDER BY due_date DESC LIMIT 30""",
            (firm_name, str(firm_id))
        ).fetchall():
            events.append({"type": "task", "text": r["title"], "date": r["due_date"], "status": r["status"], "icon": "✓"})
        # Jobs (created for this firm via employers)
        for r in conn.execute(
            """SELECT j.title, j.created_at, j.status FROM jobs j
               JOIN employers e ON j.employer_id = e.id
               WHERE LOWER(e.name) = LOWER(?)
               ORDER BY j.created_at DESC LIMIT 20""",
            (firm_name,)
        ).fetchall():
            events.append({"type": "job", "text": f"Job opened: {r['title']}", "date": r["created_at"], "status": r["status"], "icon": "💼"})
        # Pipeline additions
        for r in conn.execute(
            """SELECT p.attorney_name, p.stage, p.created_at, j.title as job_title FROM pipeline p
               JOIN jobs j ON p.job_id = j.id
               JOIN employers e ON j.employer_id = e.id
               WHERE LOWER(e.name) = LOWER(?)
               ORDER BY p.created_at DESC LIMIT 30""",
            (firm_name,)
        ).fetchall():
            events.append({"type": "pipeline", "text": f"{r['attorney_name']} added to pipeline ({r['stage']}) for {r['job_title']}", "date": r["created_at"], "icon": "👤"})
        # Status changes (from firm_status updated_at)
        st = ats_db.get_firm_status_by_fp_id(firm_id) or ats_db.get_firm_status(firm_name)
        if st and st.get("updated_at"):
            events.append({"type": "status", "text": f"Status: {st.get('client_status', 'Unknown')}", "date": st["updated_at"], "icon": "🏢"})
        conn.close()
    except Exception as e:
        print(f"[relationship timeline] {e}")
    events.sort(key=lambda e: e.get("date") or "", reverse=True)
    return jsonify({"events": events[:100]})


@app.route("/api/firms/<firm_id>")
def api_firm_detail(firm_id):
    if FIRMS_DF.empty:
        return jsonify({"error": "No firms data"}), 404
    match = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
    if match.empty:
        return jsonify({"error": "Firm not found"}), 404
    row = match.iloc[0]
    firm = _firm_to_dict(row)
    firm["notes"] = ats_db.get_firm_notes(firm_id)
    firm["contacts"] = ats_db.get_firm_contacts(firm_id)
    # Include CRM status fields
    st = ats_db.get_firm_status_by_fp_id(firm_id) or ats_db.get_firm_status(firm.get("name", ""))
    if st:
        firm["client_status"] = st.get("client_status", "Reference Only")
        firm["priority"] = st.get("priority", "Normal")
        firm["owner"] = st.get("owner", "")
        firm["last_contact_date"] = st.get("last_contact_date", "")
        firm["next_follow_up"] = st.get("next_follow_up", "")
        firm["crm_notes"] = st.get("notes", "")
        firm["pinned"] = bool(st.get("pinned", 0))
    else:
        firm["client_status"] = "Reference Only"
        firm["priority"] = "Normal"
        firm["owner"] = ""
        firm["last_contact_date"] = ""
        firm["next_follow_up"] = ""
        firm["crm_notes"] = ""
        firm["pinned"] = False
    # Track view
    try:
        ats_db.track_firm_view(firm.get("name", ""), firm_id)
    except Exception:
        pass
    return jsonify({"firm": firm})


@app.route("/api/firms/<firm_id>/top-candidates")
def api_firm_top_candidates(firm_id):
    """Return top 50 candidates matched against a firm's Hiring DNA."""
    if FIRMS_DF.empty:
        return jsonify({"error": "No firms data"}), 404
    match = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
    if match.empty:
        return jsonify({"error": "Firm not found"}), 404
    firm_name = match.iloc[0].get("Name", "")
    resolved = _resolve_dna_firm_name(firm_name)
    if not resolved:
        return jsonify({"candidates": [], "dna": None,
                        "message": "No hiring history data available for this firm."})
    dna = HIRING_DNA.get(resolved, {})
    candidates = get_top_candidates(firm_name)
    # Count candidates with score >= 60 for badge
    strong_matches = sum(1 for c in candidates if c["match_score"] >= 60)
    return jsonify(_sanitize_for_json({
        "candidates": candidates,
        "dna": {
            "firm_name": dna.get("firm_name", ""),
            "total_hires": dna.get("total_hires", 0),
            "feeder_schools": dna.get("feeder_schools", [])[:5],
            "feeder_firms": dna.get("feeder_firms", [])[:5],
            "practice_areas": dna.get("practice_areas", [])[:5],
            "class_year_range": dna.get("class_year_range", {}),
        },
        "strong_matches": strong_matches,
    }))


@app.route("/api/firms/<firm_id>/top-candidates/refresh", methods=["POST"])
def api_firm_refresh_candidates(firm_id):
    """Clear cache and re-compute top candidates for a firm."""
    if FIRMS_DF.empty:
        return jsonify({"error": "No firms data"}), 404
    match = FIRMS_DF[FIRMS_DF["FP ID"] == str(firm_id)]
    if match.empty:
        return jsonify({"error": "Firm not found"}), 404
    firm_name = match.iloc[0].get("Name", "")
    resolved = _resolve_dna_firm_name(firm_name)
    if resolved and resolved in _top_candidates_cache:
        del _top_candidates_cache[resolved]
    candidates = get_top_candidates(firm_name) if resolved else []
    return jsonify({"ok": True, "count": len(candidates)})


@app.route("/api/firms/<firm_id>/notes", methods=["POST"])
def api_firm_add_note(firm_id):
    data = request.get_json(force=True)
    note = data.get("note", "").strip()
    if not note:
        return jsonify({"error": "Note is required"}), 400
    ats_db.add_firm_note(firm_id, note)
    return jsonify({"ok": True})


@app.route("/api/firms/<firm_id>/notes/<int:note_id>", methods=["DELETE"])
def api_firm_delete_note(firm_id, note_id):
    ats_db.delete_firm_note(note_id)
    return jsonify({"ok": True})


@app.route("/api/firms/<firm_id>/contacts", methods=["POST"])
def api_firm_add_contact(firm_id):
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    ats_db.add_firm_contact(
        firm_id,
        name,
        title=data.get("title", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
    )
    return jsonify({"ok": True})


@app.route("/api/firms/<firm_id>/contacts/<int:contact_id>", methods=["DELETE"])
def api_firm_delete_contact(firm_id, contact_id):
    ats_db.delete_firm_contact(contact_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Find Similar Attorneys
# ---------------------------------------------------------------------------

SIMILAR_SYSTEM_PROMPT = """You are an expert legal recruiting analyst specializing in finding similar attorney profiles. You are given a source attorney's detailed profile and a pool of potential similar candidates.

IMPORTANT: The candidate pool has already been filtered to attorneys at a similar career stage (title level), class year range, and geographic market. Focus your ranking on practice substance, firm tier, and credentials rather than career-stage differences.

Your job is to find the most similar attorneys based on deep contextual analysis. Similarity should be evaluated HEAVILY on these factors (in priority order):

1. **Practice substance and bio context (50% weight)**: Do they actually do the same KIND of work? Read the bios carefully. Two "Corporate" attorneys could be completely different — one does M&A deals, the other does fund formation. Look at the actual substance of their practice, the types of clients they serve, the specific deals/matters they handle. This is the most important factor.

2. **Firm tier and pedigree (25% weight)**: Are they at a similar caliber firm? Group firms into tiers:
   - Elite/Vault 10 (e.g., Cravath, Wachtell, Skadden, Sullivan & Cromwell)
   - V50/Top AmLaw (e.g., Kirkland, Latham, Goodwin, Ropes & Gray)
   - AmLaw 100 / Top 200
   - Mid-size / Regional
   - Small / Boutique
   An associate at Kirkland is more similar to an associate at Latham than to one at a 20-person boutique, even if the practice area is identical.

3. **Class year and seniority (10% weight)**: Fine-grained differences within the candidate pool's class year window. A 2021 graduate is slightly more similar to a 2022 graduate than to a 2018 graduate.

4. **Educational pedigree and credentials (15% weight)**: Similar law school tier (T14 vs. T50 vs. regional), clerkships, LLM, notable accolades. These signal similar candidate "market positioning."

Secondary factors (tiebreakers):
- Same bar admissions
- Similar prior experience / lateral history
- Language skills or diversity background if distinctive

Return your results as JSON:

{
  "source_summary": "One sentence describing the source attorney's key profile characteristics that you're matching against.",
  "similar_attorneys": [
    {
      "attorney_id": "the attorney's id from the data",
      "similarity_rank": 1,
      "similarity_score": 92,
      "reason": "One clear, specific sentence explaining WHY this attorney is similar. Reference concrete details from both attorneys' profiles."
    }
  ]
}

Rules:
- Return up to 25 similar attorneys, ranked by similarity
- The similarity_score should be 0-100 where 100 is essentially the same profile
- Every "reason" must be specific and mention actual details from both attorneys' profiles
- Do NOT include attorneys who are only superficially similar (same practice area but completely different substance)
- If two attorneys have near-identical bios (same firm, same practice group, same school tier, same class year), they should score 90+
- An attorney at a completely different firm tier doing similar work might score 60-75
- An attorney at a similar firm tier doing adjacent but different work might score 50-65
- Always respond with valid JSON only. No markdown, no explanation outside the JSON."""


def _get_firm_tier(row):
    """Derive firm tier label from flags."""
    if str(row.get("vault_10", "")).upper() == "TRUE":
        return "Vault 10"
    if str(row.get("vault_50", "")).upper() == "TRUE":
        return "Vault 50"
    if str(row.get("top_200", "")).upper() == "TRUE":
        return "Top 200"
    return ""


def _build_source_block(row):
    """Build detailed profile text for the source attorney (full bio)."""
    fields = {
        "Name": f"{row.get('first_name', '')} {row.get('last_name', '')}",
        "Firm": row.get("firm_name", ""),
        "Title": row.get("title", ""),
        "Class Year": row.get("graduationYear", ""),
        "Firm Tier": _get_firm_tier(row),
        "Law School": row.get("lawSchool", ""),
        "Undergraduate": row.get("undergraduate", ""),
        "LLM": row.get("llm_school", ""),
        "LLM Specialty": row.get("llm_specialty", ""),
        "Bar Admissions": row.get("barAdmissions", ""),
        "Practice Areas": row.get("practice_areas", ""),
        "Specialty": row.get("specialty", ""),
        "Keywords": row.get("added_keywords", ""),
        "NLP Specialties": row.get("nlp_specialties", ""),
        "Location": row.get("location", ""),
        "Prior Experience": row.get("prior_experience", ""),
        "Clerkships": row.get("clerkships", ""),
        "Accolades": row.get("raw_acknowledgements", ""),
    }
    lines = [f"  {k}: {v}" for k, v in fields.items() if v and str(v).strip()]
    bio = str(row.get("attorneyBio", "")).strip()
    if not bio:
        bio = get_attorney_full_bio(row.get("id", ""))
    if bio:
        lines.append(f"  Full Bio: {bio}")
    return "\n".join(lines)


def _build_pool_block(row):
    """Build compact profile text for a pool candidate (summary instead of full bio)."""
    fields = {
        "ID": str(row.get("id", "")),
        "Name": f"{row.get('first_name', '')} {row.get('last_name', '')}",
        "Firm": row.get("firm_name", ""),
        "Title": row.get("title", ""),
        "Class Year": row.get("graduationYear", ""),
        "Firm Tier": _get_firm_tier(row),
        "Law School": row.get("lawSchool", ""),
        "Undergraduate": row.get("undergraduate", ""),
        "LLM": row.get("llm_school", ""),
        "Bar Admissions": row.get("barAdmissions", ""),
        "Practice Areas": row.get("practice_areas", ""),
        "Specialty": row.get("specialty", ""),
        "NLP Specialties": row.get("nlp_specialties", ""),
        "Location": row.get("location", ""),
        "Prior Experience": row.get("prior_experience", ""),
        "Clerkships": row.get("clerkships", ""),
        "Accolades": row.get("raw_acknowledgements", ""),
    }
    lines = [f"  {k}: {v}" for k, v in fields.items() if v and str(v).strip()]
    summary = str(row.get("summary", "")).strip()
    bio = str(row.get("attorneyBio", "")).strip()
    # Use summary if available, else truncate bio
    if summary:
        lines.append(f"  Summary: {summary[:500]}")
    elif bio:
        lines.append(f"  Summary: {bio[:500]}")
    return "\n".join(lines)


_TITLE_BUCKETS = {
    "partner": ["partner", "managing partner", "office managing partner",
                "shareholder", "member", "principal", "director",
                "chair", "co-chair", "vice chair", "head", "co-head",
                "practice leader", "co-leader"],
    "counsel": ["counsel", "senior counsel", "special counsel", "of counsel"],
    "associate": ["associate", "senior associate", "managing associate",
                  "senior managing associate", "staff attorney", "attorney",
                  "senior attorney", "project attorney", "discovery attorney",
                  "foreign associate", "international associate",
                  "career associate", "practice group associate"],
}


def _get_title_bucket(title):
    """Map an attorney title to a seniority bucket: partner, counsel, associate, or '' (unknown)."""
    t = str(title).strip().lower()
    if not t:
        return ""
    # Check in order: partner first (since "managing partner" contains "partner"),
    # then counsel, then associate
    for bucket in ("partner", "counsel", "associate"):
        if t in _TITLE_BUCKETS[bucket]:
            return bucket
    return ""


def _prefilter_similar(source_row, min_criteria=1, relaxed=False, skip_location=False):
    """Pre-filter attorneys that share characteristics with the source.
    Uses two-phase filtering: hard filters first (title, class year, location),
    then soft contextual filters (practice area, specialty, school, keywords).
    Returns a DataFrame of matching candidates.
    """
    df = ATTORNEYS_DF
    source_id = str(source_row.get("id", ""))

    # Exclude source attorney; use summary as content proxy (bio loaded on-demand)
    summary_col = df.get("summary", pd.Series("", index=df.index)).fillna("")
    has_content = summary_col.str.strip().str.len() > 0
    not_self = df["id"].astype(str) != source_id
    hard_mask = has_content & not_self

    # --- Phase 1: Hard filters (must-match) ---

    # 1. Title level
    src_bucket = _get_title_bucket(source_row.get("title", ""))
    if src_bucket:
        title_col = df.get("title", pd.Series("", index=df.index)).fillna("")
        candidate_buckets = title_col.apply(_get_title_bucket)
        hard_mask = hard_mask & (candidate_buckets == src_bucket)

    # 2. Class year — window depends on seniority level
    #    Associates: ±1 year (tight, same cohort)
    #    Counsel/Partner: ±3 years (broader, seniority is less year-specific)
    #    Unknown bucket: ±2 years (moderate default)
    #    Relaxed mode (adaptive fallback): adds +2 to each range
    if src_bucket == "associate":
        year_range = 1
    elif src_bucket in ("counsel", "partner"):
        year_range = 3
    else:
        year_range = 2
    if relaxed:
        year_range += 2

    src_year_str = str(source_row.get("graduationYear", "")).strip()
    src_year = None
    if src_year_str.isdigit():
        src_year = int(src_year_str)
        year_col = pd.to_numeric(df.get("graduationYear", pd.Series("", index=df.index)), errors="coerce")
        hard_mask = hard_mask & (year_col >= src_year - year_range) & (year_col <= src_year + year_range)

    # 3. Location (city-level)
    if not skip_location:
        src_location = str(source_row.get("location", "")).strip()
        if src_location:
            # Extract primary city (before first comma)
            src_city = src_location.split(",")[0].strip().lower()
            if src_city:
                loc_col = df.get("location", pd.Series("", index=df.index)).fillna("").str.lower()
                hard_mask = hard_mask & loc_col.str.contains(re.escape(src_city), na=False)

    hard_pool = df[hard_mask]

    # --- Phase 2: Soft contextual filters (applied within hard-filtered pool) ---
    soft_criteria = []

    # 1. Same practice_areas
    src_pa = str(source_row.get("practice_areas", "")).strip().lower()
    if src_pa:
        pa_col = hard_pool.get("practice_areas", pd.Series("", index=hard_pool.index)).fillna("").str.strip().str.lower()
        soft_criteria.append(pa_col == src_pa)

    # 2. Overlapping specialty keywords
    src_spec = str(source_row.get("specialty", "")).lower()
    src_spec_words = {w.strip() for w in re.split(r"[,;/]+", src_spec) if w.strip() and len(w.strip()) > 2}
    if src_spec_words:
        spec_col = hard_pool.get("specialty", pd.Series("", index=hard_pool.index)).fillna("").str.lower()
        spec_mask = pd.Series(False, index=hard_pool.index)
        for word in src_spec_words:
            spec_mask = spec_mask | spec_col.str.contains(re.escape(word), na=False)
        soft_criteria.append(spec_mask)

    # 3. Same law school
    src_school = str(source_row.get("lawSchool", "")).strip().lower()
    if src_school:
        school_col = hard_pool.get("lawSchool", pd.Series("", index=hard_pool.index)).fillna("").str.strip().str.lower()
        soft_criteria.append(school_col == src_school)

    # 4. Overlapping added_keywords or nlp_specialties
    src_kw = str(source_row.get("added_keywords", "")).lower() + " " + str(source_row.get("nlp_specialties", "")).lower()
    src_kw_words = {w.strip() for w in re.split(r"[,;/]+", src_kw) if w.strip() and len(w.strip()) > 2}
    if src_kw_words:
        kw_col = (
            hard_pool.get("added_keywords", pd.Series("", index=hard_pool.index)).fillna("").str.lower() + " " +
            hard_pool.get("nlp_specialties", pd.Series("", index=hard_pool.index)).fillna("").str.lower()
        )
        kw_mask = pd.Series(False, index=hard_pool.index)
        for word in list(src_kw_words)[:10]:
            kw_mask = kw_mask | kw_col.str.contains(re.escape(word), na=False)
        soft_criteria.append(kw_mask)

    if not soft_criteria:
        return hard_pool.head(300)

    # Count how many soft criteria each row satisfies
    combined = pd.DataFrame({f"c{i}": c for i, c in enumerate(soft_criteria)})
    match_count = combined.sum(axis=1)

    result = hard_pool[match_count >= min_criteria]

    # --- Adaptive pool sizing ---
    if len(result) > 300:
        # Tighten: require more soft criteria matches
        tighter = hard_pool[match_count >= 2]
        result = tighter.head(300) if len(tighter) > 0 else result.head(300)
    elif len(result) < 20 and not relaxed:
        # Relax: widen class year window, drop location, retry
        result = _prefilter_similar(source_row, min_criteria=1, relaxed=True, skip_location=True)

    return result


@app.route("/api/attorneys/similar", methods=["POST"])
def api_find_similar():
    """Find attorneys similar to a given attorney."""
    start_time = time.time()
    data = request.get_json(force=True)
    attorney_id = str(data.get("attorney_id", ""))

    if not attorney_id:
        return jsonify({"error": "attorney_id is required"}), 400
    if ATTORNEYS_DF.empty:
        return jsonify({"error": "No attorney data loaded"}), 500
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "AI not configured (no API key)"}), 500

    # Find the source attorney
    match = ATTORNEYS_DF[ATTORNEYS_DF["id"].astype(str) == attorney_id]
    if match.empty:
        return jsonify({"error": "Attorney not found"}), 404
    source_row = match.iloc[0]

    # Pre-filter with hard filters (title, class year, location) + soft criteria
    # Adaptive pool sizing is handled inside _prefilter_similar
    pool = _prefilter_similar(source_row, min_criteria=1)

    if pool.empty:
        return jsonify({
            "source": _serialize_candidate(source_row.to_dict()),
            "source_summary": "No similar attorneys could be found.",
            "similar": [],
            "pool_size": 0,
            "elapsed_seconds": round(time.time() - start_time, 1),
        })

    # Build Claude prompt
    source_block = _build_source_block(source_row)
    pool_blocks = []
    for _, row in pool.iterrows():
        pool_blocks.append(_build_pool_block(row))

    # Limit to keep within token budget
    pool_text = "\n---\n".join(pool_blocks[:250])

    user_prompt = f"""SOURCE ATTORNEY:
{source_block}

CANDIDATE POOL ({len(pool_blocks[:250])} attorneys):
{pool_text}

Find the top 25 most similar attorneys from the candidate pool. Return JSON only."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            temperature=0,
            system=SIMILAR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        result = _repair_truncated_json(text)
    except Exception as e:
        print(f"[Find Similar error] {e}")
        traceback.print_exc()
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500

    # Enrich similar attorneys with full profile data
    source_summary = result.get("source_summary", "")
    similar_raw = result.get("similar_attorneys", [])
    enriched = []

    for s in similar_raw:
        aid = str(s.get("attorney_id", ""))
        amatch = ATTORNEYS_DF[ATTORNEYS_DF["id"].astype(str) == aid]
        if amatch.empty:
            continue
        arow = amatch.iloc[0]
        candidate = _serialize_candidate(arow.to_dict())
        candidate["similarity_rank"] = s.get("similarity_rank", 0)
        candidate["similarity_score"] = s.get("similarity_score", 0)
        candidate["similarity_reason"] = s.get("reason", "")
        enriched.append(candidate)

    # Also check pipeline status for all returned attorneys
    pipeline_ids = [str(c["id"]) for c in enriched if c.get("id")]
    pipeline_status = {}
    if pipeline_ids:
        try:
            pipeline_status = ats_db.get_pipeline_status_for_attorneys(pipeline_ids)
        except Exception:
            pass

    for c in enriched:
        c["in_pipeline"] = pipeline_status.get(str(c["id"]), False)

    elapsed = round(time.time() - start_time, 1)

    return jsonify({
        "source": _serialize_candidate(source_row.to_dict()),
        "source_summary": source_summary,
        "similar": enriched,
        "pool_size": len(pool),
        "elapsed_seconds": elapsed,
    })


# ---------------------------------------------------------------------------
# Candidate Comparison Tool
# ---------------------------------------------------------------------------
COMPARE_SYSTEM_PROMPT = """You are an expert legal recruiting analyst. Compare the provided attorney candidates side-by-side and return a structured JSON analysis.

Return ONLY valid JSON (no markdown fences, no extra text):

{
  "executive_summary": "2-3 paragraph analysis comparing the candidates overall, naming each candidate explicitly.",
  "ranked_candidates": [
    {
      "rank": 1,
      "name": "Full Name",
      "overall_score": 88,
      "headline": "One-line differentiator, e.g. 'Best pedigree, deepest M&A bench'",
      "strengths": ["Strength 1", "Strength 2", "Strength 3"],
      "concerns": ["Concern 1", "Concern 2"],
      "dimension_scores": {
        "practice": 90,
        "pedigree": 85,
        "compensation": 75,
        "culture": 80,
        "client_book": 70
      }
    }
  ],
  "head_to_head": [
    {
      "dimension": "Practice Fit",
      "winner": "Full Name",
      "analysis": "One sentence explaining why."
    }
  ],
  "recommendation": "1-2 paragraph concrete recommendation for which candidate to prioritize and why.",
  "client_ready_summary": "Professional 2-3 paragraph summary suitable for sharing with a hiring client. Do not use internal jargon."
}

Only include dimensions in dimension_scores that were listed in the priorities. Score each 0-100."""


@app.route("/api/compare", methods=["POST"])
def api_compare():
    data = request.get_json() or {}
    candidates = data.get("candidates", [])
    job_id = data.get("job_id")
    priorities = data.get("priorities") or ["compensation", "practice", "culture", "pedigree"]
    custom_note = data.get("custom_note", "")

    if len(candidates) < 2:
        return jsonify({"error": "At least 2 candidates required"}), 400

    # Optionally fetch job details
    job_context = ""
    if job_id:
        try:
            job = ats_db.get_job(int(job_id))
            if job:
                job_context = f"\n\nJOB CONTEXT:\nTitle: {job.get('title', '')}\nEmployer: {job.get('employer_name', '')}\nPractice Area: {job.get('practice_area', '')}\nLocation: {job.get('location', '')}\nDescription: {(job.get('description', '') or '')[:600]}"
        except Exception:
            pass

    # Build candidate profiles
    cand_text = ""
    for i, c in enumerate(candidates, 1):
        cand_text += f"\n--- CANDIDATE {i}: {c.get('name', 'Unknown')} ---\n"
        cand_text += f"Current Firm: {c.get('current_firm', '')}\n"
        cand_text += f"Title: {c.get('title', '')}\n"
        cand_text += f"Law School: {c.get('law_school', '')} ({c.get('graduation_year', '')})\n"
        cand_text += f"Bar Admission: {c.get('bar_admission', '')}\n"
        cand_text += f"Practice Areas: {c.get('practice_areas', '')}\n"
        cand_text += f"Specialties: {c.get('specialties', '')}\n"
        cand_text += f"Location: {c.get('location', '')}\n"
        cand_text += f"Prior Firms: {c.get('prior_firms', '')}\n"
        cand_text += f"Tier: {c.get('tier', '')}\n"
        cand_text += f"Match Score: {c.get('match_score', '')}\n"
        cand_text += f"Boomerang: {c.get('is_boomerang', False)}\n"
        if c.get("qualifications_summary"):
            cand_text += f"Qualifications: {c['qualifications_summary'][:500]}\n"

    priorities_text = ", ".join(p.replace("_", " ").title() for p in priorities)
    note_text = f"\n\nRECRUITER NOTE: {custom_note}" if custom_note else ""

    user_message = (
        f"Compare the following {len(candidates)} attorney candidates.{job_context}\n\n"
        f"COMPARISON PRIORITIES (weight these dimensions most heavily): {priorities_text}\n"
        f"{note_text}\n\n"
        f"CANDIDATES:{cand_text}\n\n"
        f"Return your analysis as JSON per the system instructions."
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            temperature=0,
            system=COMPARE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = _repair_truncated_json(raw) if "raw" in dir() else {}
        if not result:
            return jsonify({"error": "AI response could not be parsed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(result)


@app.route("/api/compare/pdf", methods=["POST"])
def api_compare_pdf():
    data = request.get_json() or {}
    candidates = data.get("candidates", [])
    job_context = data.get("job_context", "")
    comparison_data = data.get("comparison_data") or {}

    PRIMARY = HexColor("#0059FF")
    DARK = HexColor("#151515")
    LIGHT_BLUE = HexColor("#E0F1FF")
    GRAY = HexColor("#696969")
    LIGHT_GRAY = HexColor("#F6F6F6")
    GREEN = HexColor("#22c55e")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch, bottomMargin=0.75*inch,
    )
    styles = getSampleStyleSheet()

    def S(name, **kwargs):
        base = styles["Normal"]
        defaults = {"fontName": "Helvetica"}
        defaults.update(kwargs)
        return ParagraphStyle(name, parent=base, **defaults)

    s_title   = S("Title",   fontSize=20, textColor=PRIMARY, spaceAfter=4, fontName="Helvetica-Bold")
    s_sub     = S("Sub",     fontSize=11, textColor=GRAY, spaceAfter=16)
    s_h2      = S("H2",      fontSize=13, textColor=DARK, spaceBefore=14, spaceAfter=8, fontName="Helvetica-Bold")
    s_body    = S("Body",    fontSize=10, textColor=DARK, spaceAfter=6, leading=14)
    s_label   = S("Label",   fontSize=9,  textColor=GRAY, spaceAfter=2)
    s_bold    = S("Bold",    fontSize=10, textColor=DARK, fontName="Helvetica-Bold")
    s_client  = S("Client",  fontSize=10, textColor=DARK, leading=15, spaceAfter=6)

    story = []
    today = datetime.now().strftime("%B %d, %Y")
    names = ", ".join(c.get("name", "") for c in candidates)

    story.append(Paragraph("JAIDE ATS — Candidate Comparison", s_title))
    story.append(Paragraph(f"{today}" + (f" &nbsp;·&nbsp; {job_context}" if job_context else ""), s_sub))
    story.append(HRFlowable(width="100%", thickness=1, color=PRIMARY))
    story.append(Spacer(1, 16))

    # Quick Compare table
    story.append(Paragraph("Quick Compare", s_h2))
    headers = ["Field"] + [c.get("name", f"Candidate {i+1}") for i, c in enumerate(candidates)]
    fields = [
        ("Current Firm",   lambda c: c.get("current_firm", "—") or "—"),
        ("Title",          lambda c: c.get("title", "—") or "—"),
        ("Law School",     lambda c: c.get("law_school", "—") or "—"),
        ("Class Year",     lambda c: str(c.get("graduation_year", "—") or "—")),
        ("Bar Admission",  lambda c: c.get("bar_admission", "—") or "—"),
        ("Practice Areas", lambda c: (c.get("practice_areas", "") or "—")[:60]),
        ("Location",       lambda c: c.get("location", "—") or "—"),
        ("Tier",           lambda c: c.get("tier", "—") or "—"),
        ("Match Score",    lambda c: str(c.get("match_score", "—") or "—")),
    ]
    tdata = [headers]
    for label, fn in fields:
        tdata.append([label] + [fn(c) for c in candidates])

    col_w = (doc.width - 1.3*inch) / max(1, len(candidates))
    col_widths = [1.3*inch] + [col_w] * len(candidates)
    t = Table(tdata, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  PRIMARY),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  white),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("BACKGROUND",   (0, 1), (0, -1),  LIGHT_GRAY),
        ("FONTNAME",     (0, 1), (0, -1),  "Helvetica-Bold"),
        ("TEXTCOLOR",    (0, 1), (0, -1),  GRAY),
        ("ROWBACKGROUNDS", (1, 1), (-1, -1), [white, HexColor("#FAFAFA")]),
        ("GRID",         (0, 0), (-1, -1), 0.5, HexColor("#EDEDED")),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING",  (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    # AI sections
    if comparison_data:
        if comparison_data.get("executive_summary"):
            story.append(Paragraph("Executive Summary", s_h2))
            story.append(Paragraph(comparison_data["executive_summary"], s_body))
            story.append(Spacer(1, 8))

        if comparison_data.get("ranked_candidates"):
            story.append(Paragraph("Candidate Rankings", s_h2))
            medals = ["1st", "2nd", "3rd", "4th"]
            for i, r in enumerate(comparison_data["ranked_candidates"]):
                medal = medals[i] if i < len(medals) else f"#{r.get('rank', i+1)}"
                story.append(Paragraph(
                    f"<b>{medal} — {r.get('name', '')} &nbsp; (Score: {r.get('overall_score', '')})</b>",
                    s_bold
                ))
                if r.get("headline"):
                    story.append(Paragraph(r["headline"], s_label))
                if r.get("strengths"):
                    story.append(Paragraph("<b>Strengths:</b> " + " · ".join(r["strengths"]), s_body))
                if r.get("concerns"):
                    story.append(Paragraph("<b>Considerations:</b> " + " · ".join(r["concerns"]), s_body))
                story.append(Spacer(1, 6))

        if comparison_data.get("recommendation"):
            story.append(Paragraph("Recommendation", s_h2))
            story.append(Paragraph(comparison_data["recommendation"], s_body))
            story.append(Spacer(1, 8))

        if comparison_data.get("client_ready_summary"):
            story.append(PageBreak())
            story.append(Paragraph("Client-Ready Summary", s_h2))
            story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_BLUE))
            story.append(Spacer(1, 8))
            story.append(Paragraph(comparison_data["client_ready_summary"], s_client))

    doc.build(story)
    buf.seek(0)
    safe_names = re.sub(r"[^\w\s-]", "", names)[:40].strip().replace(" ", "-")
    filename = f"jaide-compare-{safe_names or 'candidates'}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


import threading

def _precompute_top_candidates():
    """Background: pre-compute top candidates for all firms with hiring DNA."""
    count = 0
    for firm_name in list(HIRING_DNA.keys()):
        get_top_candidates(firm_name)
        count += 1
    print(f"[Background] Pre-computed top candidates for {count} firms.")

@app.route("/debug", methods=["GET", "POST"])
def debug_page():
    import sqlite3 as _sq
    db_path = ats_db.DB_PATH

    def conn():
        c = _sq.connect(db_path)
        c.row_factory = _sq.Row
        return c

    def rows_to_html(rows, empty_msg="(no rows)"):
        if not rows:
            return f"<p><b>{empty_msg}</b></p>"
        cols = rows[0].keys()
        th = "".join(f"<th>{c}</th>" for c in cols)
        body = ""
        for r in rows:
            body += "<tr>" + "".join(f"<td>{r[c]}</td>" for c in cols) + "</tr>"
        return f"<table border=1 cellpadding=4 style='border-collapse:collapse;font-size:12px'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"

    html = ["<html><body><pre style='font-family:monospace'>"]
    html.append("<h1>JAIDE ATS — Pipeline Debug Page</h1>")
    html.append(f"<p>DB path: {db_path}</p>")
    html.append(f"<p>DB exists: {os.path.exists(db_path)}</p>")

    # ── SECTION 1: DATABASE TABLES ────────────────────────────────────────
    html.append("<hr><h2>SECTION 1: DATABASE TABLES</h2>")
    with conn() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    html.append(f"<p>Tables found: {tables}</p>")
    for tbl in tables:
        with conn() as c:
            schema = c.execute(f"PRAGMA table_info({tbl})").fetchall()
            count = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        cols = ", ".join(f"{r['name']} {r['type']}" for r in schema)
        html.append(f"<p><b>{tbl}</b> — {count} rows<br>Columns: {cols}</p>")

    # ── SECTION 2: PIPELINE TABLE RAW DUMP ───────────────────────────────
    html.append("<hr><h2>SECTION 2: PIPELINE TABLE — RAW DUMP</h2>")
    with conn() as c:
        rows = c.execute("SELECT * FROM pipeline").fetchall()
    if not rows:
        html.append("<p><b style='color:red'>PIPELINE TABLE IS EMPTY — the Add to Pipeline action is not saving data</b></p>")
    else:
        html.append(f"<p>{len(rows)} rows found.</p>")
        html.append(rows_to_html(rows))

    # ── SECTION 3: JOBS TABLE RAW DUMP ───────────────────────────────────
    html.append("<hr><h2>SECTION 3: JOBS TABLE — RAW DUMP</h2>")
    with conn() as c:
        rows = c.execute("SELECT * FROM jobs").fetchall()
    if not rows:
        html.append("<p><b style='color:red'>JOBS TABLE IS EMPTY — no jobs exist to assign candidates to</b></p>")
    else:
        html.append(f"<p>{len(rows)} rows found.</p>")
        html.append(rows_to_html(rows))

    # ── SECTION 4: EMPLOYERS TABLE RAW DUMP ──────────────────────────────
    html.append("<hr><h2>SECTION 4: EMPLOYERS TABLE — RAW DUMP</h2>")
    with conn() as c:
        rows = c.execute("SELECT * FROM employers").fetchall()
    html.append(f"<p>{len(rows)} rows found.</p>")
    html.append(rows_to_html(rows, "(employers table empty)"))

    # ── SECTION 5: WHAT THE DASHBOARD API RETURNS ────────────────────────
    html.append("<hr><h2>SECTION 5: WHAT THE DASHBOARD API RETURNS</h2>")
    api_url = "/api/pipeline (internal call — no filters)"
    html.append(f"<p>Calling: <code>{api_url}</code></p>")
    pipeline_data = ats_db.get_pipeline_all()
    html.append(f"<p>Response pipeline count: <b>{len(pipeline_data)}</b></p>")
    if not pipeline_data:
        html.append("<p><b style='color:red'>THE API IS RETURNING EMPTY DATA — the problem is in the backend query (likely a JOIN that drops rows)</b></p>")
    else:
        html.append("<p><b style='color:green'>THE API HAS DATA — the problem is in the frontend rendering</b></p>")
        import json as _json
        html.append(f"<pre style='background:#f5f5f5;padding:8px;max-height:300px;overflow:auto'>{_json.dumps(pipeline_data[:3], indent=2, default=str)} ...</pre>")

    # ── SECTION 6: THE ACTUAL SQL QUERY ──────────────────────────────────
    html.append("<hr><h2>SECTION 6: THE ACTUAL SQL QUERY</h2>")
    full_sql = """SELECT p.*, j.title as job_title, e.name as employer_name
               FROM pipeline p
               JOIN jobs j ON p.job_id = j.id
               LEFT JOIN employers e ON j.employer_id = e.id
               WHERE 1=1
               ORDER BY p.updated_at DESC"""
    html.append(f"<p>SQL used by <code>get_pipeline_all()</code>:</p><pre style='background:#f0f0f0;padding:8px'>{full_sql}</pre>")

    html.append("<h3>6a: SELECT * FROM pipeline (no JOIN)</h3>")
    with conn() as c:
        rows = c.execute("SELECT * FROM pipeline").fetchall()
    html.append(f"<p>{len(rows)} rows</p>")
    html.append(rows_to_html(rows, "pipeline is empty"))

    html.append("<h3>6b: SELECT * FROM jobs WHERE id IN (SELECT job_id FROM pipeline)</h3>")
    with conn() as c:
        rows = c.execute("SELECT * FROM jobs WHERE id IN (SELECT job_id FROM pipeline)").fetchall()
    html.append(f"<p>{len(rows)} matching job rows</p>")
    html.append(rows_to_html(rows, "(no matching jobs — this is the JOIN break point)"))

    html.append("<h3>6c: Full JOIN query (same as API)</h3>")
    with conn() as c:
        rows = c.execute(full_sql).fetchall()
    html.append(f"<p>{len(rows)} rows after JOIN</p>")
    html.append(rows_to_html(rows, "(no rows returned by JOIN)"))

    # ── SECTION 7: ID COMPARISON ──────────────────────────────────────────
    html.append("<hr><h2>SECTION 7: ID COMPARISON</h2>")
    with conn() as c:
        pipeline_job_ids = [r[0] for r in c.execute("SELECT DISTINCT job_id FROM pipeline").fetchall()]
        jobs_ids = [r[0] for r in c.execute("SELECT id FROM jobs").fetchall()]
    html.append(f"<p>pipeline.job_id values: {pipeline_job_ids}</p>")
    html.append(f"<p>jobs.id values: {jobs_ids}</p>")
    missing = [jid for jid in pipeline_job_ids if jid not in jobs_ids]
    if missing:
        html.append(f"<p><b style='color:red'>ID MISMATCH FOUND — pipeline references job_id {missing} but jobs table has no matching id</b></p>")
    elif not pipeline_job_ids:
        html.append("<p><b style='color:orange'>pipeline table is empty — no job_id values to check</b></p>")
    else:
        html.append("<p><b style='color:green'>All pipeline.job_id values exist in jobs.id — JOIN should work</b></p>")

    # ── SECTION 8: TEST INSERT ─────────────────────────────────────────────
    html.append("<hr><h2>SECTION 8: TEST INSERT</h2>")
    inserted_msg = ""
    if request.method == "POST" and request.form.get("action") == "insert_test":
        with conn() as c:
            job_row = c.execute("SELECT id FROM jobs LIMIT 1").fetchone()
            if job_row:
                test_job_id = job_row[0]
                c.execute("""INSERT INTO pipeline (job_id, attorney_id, attorney_name, attorney_firm,
                             attorney_email, stage, added_by, notes, placement_fee, added_at, updated_at)
                             VALUES (?, 'TEST-001', 'Test Candidate Debug', 'Test Firm Debug',
                             'test@debug.com', 'Identified', 'Debug', '', 0, datetime('now'), datetime('now'))""",
                          (test_job_id,))
                c.commit()
                inserted_msg = f"<p><b style='color:green'>TEST ROW INSERTED with job_id={test_job_id}. Reload this page to see it in Section 2.</b></p>"
            else:
                inserted_msg = "<p><b style='color:red'>Cannot insert test row — jobs table is empty. Add a job first.</b></p>"

    html.append(inserted_msg)
    html.append("""<form method="POST">
        <input type="hidden" name="action" value="insert_test">
        <button type="submit" style="font-size:14px;padding:8px 16px;cursor:pointer">Insert Test Candidate</button>
        <span style="margin-left:12px;color:#666">Inserts a row with attorney_id=TEST-001 into pipeline using the first job in jobs table</span>
    </form>""")

    html.append("</pre></body></html>")
    return "".join(html)


# ---------------------------------------------------------------------------
# Worklists API
# ---------------------------------------------------------------------------

@app.route("/api/worklists", methods=["GET"])
def api_list_worklists():
    search = request.args.get("search", "")
    return jsonify(ats_db.list_worklists(search=search))


@app.route("/api/worklists", methods=["POST"])
def api_create_worklist():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    wid = ats_db.create_worklist(
        name=name,
        description=data.get("description", ""),
        color=data.get("color", "#0059FF"),
        created_by=session.get("user_name", "Admin"),
    )
    return jsonify({"ok": True, "id": wid, "worklist": ats_db.get_worklist(wid)}), 201


@app.route("/api/worklists/<int:worklist_id>", methods=["GET"])
def api_get_worklist(worklist_id):
    wl = ats_db.get_worklist(worklist_id)
    if not wl:
        return jsonify({"error": "not found"}), 404
    return jsonify(wl)


@app.route("/api/worklists/<int:worklist_id>", methods=["PUT"])
def api_update_worklist(worklist_id):
    data = request.get_json() or {}
    ats_db.update_worklist(worklist_id, data)
    return jsonify({"ok": True, "worklist": ats_db.get_worklist(worklist_id)})


@app.route("/api/worklists/<int:worklist_id>", methods=["DELETE"])
def api_delete_worklist(worklist_id):
    ats_db.delete_worklist(worklist_id)
    return jsonify({"ok": True})


@app.route("/api/worklists/<int:worklist_id>/members", methods=["POST"])
def api_add_worklist_member(worklist_id):
    data = request.get_json() or {}
    attorney_id = str(data.get("attorney_id", "")).strip()
    if not attorney_id:
        return jsonify({"error": "attorney_id required"}), 400
    ok = ats_db.add_worklist_member(
        worklist_id=worklist_id,
        attorney_id=attorney_id,
        attorney_source=data.get("attorney_source", "fp"),
        attorney_name=data.get("attorney_name", ""),
        attorney_firm=data.get("attorney_firm", ""),
        attorney_email=data.get("attorney_email", ""),
        notes=data.get("notes", ""),
        added_by=session.get("user_name", "Admin"),
    )
    return jsonify({"ok": ok})


@app.route("/api/worklists/<int:worklist_id>/members/<attorney_id>", methods=["DELETE"])
def api_remove_worklist_member(worklist_id, attorney_id):
    source = request.args.get("source", "fp")
    ats_db.remove_worklist_member(worklist_id, attorney_id, source)
    return jsonify({"ok": True})


@app.route("/api/worklists/<int:worklist_id>/members/<attorney_id>", methods=["PUT"])
def api_update_worklist_member(worklist_id, attorney_id):
    data = request.get_json() or {}
    source = data.get("attorney_source", request.args.get("source", "fp"))
    ats_db.update_worklist_member_notes(worklist_id, attorney_id, source, data.get("notes", ""))
    return jsonify({"ok": True})


@app.route("/api/attorneys/<attorney_id>/worklists", methods=["GET"])
def api_get_attorney_worklists(attorney_id):
    source = request.args.get("source", "fp")
    return jsonify(ats_db.get_worklists_for_attorney(attorney_id, source))


# ---------------------------------------------------------------------------
# Tasks API
# ---------------------------------------------------------------------------

@app.route("/api/tasks", methods=["GET"])
def api_list_tasks():
    status = request.args.get("status")
    priority = request.args.get("priority")
    due_date = request.args.get("due_date")
    attorney_id = request.args.get("attorney_id")
    attorney_source = request.args.get("attorney_source")
    job_id = request.args.get("job_id", type=int)
    overdue_only = request.args.get("overdue") == "1"
    tasks = ats_db.list_tasks(
        status=status,
        priority=priority,
        due_date=due_date,
        attorney_id=attorney_id,
        attorney_source=attorney_source,
        job_id=job_id,
        overdue_only=overdue_only,
    )
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def api_create_task():
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    data["created_by"] = session.get("user_name", "Admin")
    task_id = ats_db.create_task(data)
    return jsonify({"ok": True, "id": task_id, "task": ats_db.get_task(task_id)}), 201


@app.route("/api/tasks/<int:task_id>", methods=["GET"])
def api_get_task(task_id):
    task = ats_db.get_task(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify(task)


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update_task(task_id):
    data = request.get_json() or {}
    ats_db.update_task(task_id, data)
    return jsonify({"ok": True, "task": ats_db.get_task(task_id)})


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id):
    ats_db.delete_task(task_id)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>/complete", methods=["PUT"])
def api_complete_task(task_id):
    ats_db.complete_task(task_id)
    return jsonify({"ok": True, "task": ats_db.get_task(task_id)})


# ---------------------------------------------------------------------------
# Dashboard data API
# ---------------------------------------------------------------------------

@app.route("/api/dashboard/stats", methods=["GET"])
def api_dashboard_stats():
    return jsonify(ats_db.get_dashboard_stats())


@app.route("/api/dashboard/action-items", methods=["GET"])
def api_dashboard_action_items():
    return jsonify(ats_db.get_action_items())


@app.route("/api/dashboard/candidates", methods=["GET"])
def api_dashboard_candidates():
    return jsonify({"candidates": ats_db.get_dashboard_candidates()})


@app.route("/api/dashboard/jobs", methods=["GET"])
def api_dashboard_jobs():
    return jsonify({"jobs": ats_db.get_dashboard_jobs()})


# ---------------------------------------------------------------------------
# Quick-search autocomplete endpoints (for task modal fields)
# ---------------------------------------------------------------------------

@app.route("/api/search/attorneys", methods=["GET"])
def api_quicksearch_attorneys():
    """Return up to 10 attorneys matching ?q= (name search across FP + custom)."""
    q = (request.args.get("q") or "").strip().lower()
    if not q or len(q) < 2:
        return jsonify([])
    results = []
    # Search FP attorneys DataFrame
    if ATTORNEYS_DF is not None:
        import pandas as pd
        df = ATTORNEYS_DF.copy()
        name_col = (
            df.get("first_name", pd.Series("", index=df.index)).fillna("") + " " +
            df.get("last_name", pd.Series("", index=df.index)).fillna("")
        ).str.lower()
        mask = name_col.str.contains(q, regex=False)
        for _, row in df[mask].head(8).iterrows():
            name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
            firm = str(row.get("firm_name", "") or "")
            gy = row.get("graduationYear", "")
            gy_str = str(int(gy)) if gy and str(gy).replace(".0","").isdigit() else ""
            results.append({
                "id": str(row.get("id", "")),
                "source": "fp",
                "name": name,
                "firm": firm,
                "graduation_year": gy_str,
                "practice_areas": str(row.get("practice_areas", "") or ""),
                "label": name + (" — " + firm if firm else "") + (" (Class of " + gy_str + ")" if gy_str else ""),
            })
    # Search custom attorneys
    custom = ats_db.list_custom_attorneys(search=q)
    for ca in custom[:5]:
        name = f"{ca.get('first_name', '')} {ca.get('last_name', '')}".strip()
        results.append({
            "id": "custom_" + str(ca["id"]),
            "source": "custom",
            "name": name,
            "firm": ca.get("current_firm", "") or "",
            "graduation_year": str(ca.get("graduation_year", "") or ""),
            "label": name + (" — " + ca["current_firm"] if ca.get("current_firm") else "") +
                     (" (Class of " + str(ca["graduation_year"]) + ")" if ca.get("graduation_year") else ""),
        })
    return jsonify(results[:10])


@app.route("/api/search/firms", methods=["GET"])
def api_quicksearch_firms():
    """Return up to 10 firms matching ?q= (FP + custom)."""
    q = (request.args.get("q") or "").strip().lower()
    if not q or len(q) < 2:
        return jsonify([])
    results = []
    # FP firms DataFrame
    if FIRMS_DF is not None:
        mask = FIRMS_DF["Name"].fillna("").str.lower().str.contains(q, regex=False)
        for _, row in FIRMS_DF[mask].head(8).iterrows():
            name = str(row.get("Name", "") or "")
            total = row.get("Total Attorneys", "")
            total_str = str(total).replace(".0", "") if total and str(total) not in ("", "nan") else ""
            ppp_v = row.get("PPP", "")
            ppp_s = ""
            if ppp_v and str(ppp_v) not in ("", "nan", "None"):
                try:
                    ppp_num = float(str(ppp_v).replace(",", ""))
                    ppp_s = f"${ppp_num/1_000_000:.1f}M" if ppp_num >= 1_000_000 else f"${int(ppp_num):,}"
                except Exception:
                    ppp_s = str(ppp_v)
            meta_str = ""
            if total_str and ppp_s:
                meta_str = f"{total_str} attorneys · {ppp_s} PPP"
            elif total_str:
                meta_str = f"{total_str} attorneys"
            results.append({
                "fp_id": str(row.get("FP ID", "")),
                "source": "fp",
                "name": name,
                "total_attorneys": total_str,
                "meta": meta_str,
                "label": name + (" — " + total_str + " attorneys" if total_str else ""),
            })
    # Custom firms
    custom = ats_db.list_custom_firms(search=q)
    for cf in custom[:4]:
        name = cf.get("name", "")
        total = cf.get("total_attorneys", "")
        results.append({
            "fp_id": None,
            "custom_id": cf["id"],
            "source": "custom",
            "name": name,
            "total_attorneys": str(total) if total else "",
            "label": name + (" — " + str(total) + " attorneys" if total else ""),
        })
    return jsonify(results[:10])


@app.route("/api/search/jobs", methods=["GET"])
def api_quicksearch_jobs():
    """Return up to 10 active jobs matching ?q= (ATS + custom)."""
    q = (request.args.get("q") or "").strip().lower()
    if not q or len(q) < 2:
        return jsonify([])
    results = []
    # ATS jobs (SQLite)
    import sqlite3
    conn = ats_db.get_db()
    rows = conn.execute(
        """SELECT j.id, j.title, j.location, e.name as firm_name
           FROM jobs j LEFT JOIN employers e ON j.employer_id = e.id
           WHERE j.status = 'Active'
             AND (LOWER(j.title) LIKE ? OR LOWER(COALESCE(e.name,'')) LIKE ?)
           LIMIT 8""",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    conn.close()
    for r in rows:
        label = r["title"]
        if r["firm_name"]:
            label += " — " + r["firm_name"]
        if r["location"]:
            label += " (" + r["location"] + ")"
        results.append({
            "id": r["id"],
            "source": "ats",
            "title": r["title"],
            "firm": r["firm_name"] or "",
            "location": r["location"] or "",
            "label": label,
        })
    # Custom jobs
    custom = ats_db.list_custom_jobs(search=q, status="Open")
    for cj in custom[:4]:
        label = cj.get("job_title", "")
        if cj.get("firm_name"):
            label += " — " + cj["firm_name"]
        if cj.get("location"):
            label += " (" + cj["location"] + ")"
        results.append({
            "id": "custom_" + str(cj["id"]),
            "source": "custom",
            "title": cj.get("job_title", ""),
            "firm": cj.get("firm_name", "") or "",
            "location": cj.get("location", "") or "",
            "label": label,
        })
    return jsonify(results[:10])


# ---------------------------------------------------------------------------
# Firm Pitch API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/firm-pitch/options", methods=["GET"])
def firm_pitch_options():
    """Return offices and practice groups for a firm."""
    firm_name = (request.args.get("firm_name") or "").strip()
    if not firm_name:
        return jsonify({"offices": [], "practice_groups": []})

    offices = []
    practice_groups = []

    if FIRMS_DF is not None and not FIRMS_DF.empty:
        mask = FIRMS_DF["Name"].fillna("").str.lower() == firm_name.lower()
        if not mask.any():
            mask = FIRMS_DF["Name"].fillna("").str.lower().str.contains(
                firm_name.lower(), regex=False)
        matches = FIRMS_DF[mask]
        if not matches.empty:
            row = matches.iloc[0]
            offices_raw = str(row.get("Firm Office Locations", "") or "")
            offices = [o.strip() for o in offices_raw.split(";") if o.strip()]
            for col in _FP_PRACTICE_COLS:
                if str(row.get(col, "")).upper() in ("TRUE", "1", "YES"):
                    practice_groups.append(col)

    return jsonify({"offices": offices, "practice_groups": practice_groups})


@app.route("/api/firm-pitch/generate", methods=["POST"])
def generate_firm_pitch():
    """Generate a firm pitch PDF document."""
    try:
        body = request.get_json(force=True) or {}
        firm_name = (body.get("firm_name") or "").strip()
        firm_fp_id = body.get("firm_fp_id")
        attorney_id = body.get("attorney_id")
        office = (body.get("office") or "").strip() or None
        practice_group = (body.get("practice_group") or "").strip() or None
        custom_prompt = (body.get("custom_prompt") or "").strip()
        tone = (body.get("tone") or "professional").strip()
        anonymize = bool(body.get("anonymize_candidate", False))
        recruiter_info = {
            "name": body.get("recruiter_name", ""),
            "title": body.get("recruiter_title", ""),
            "contact": body.get("recruiter_contact", ""),
        }

        # Resolve firm name from fp_id if name not provided
        if not firm_name and firm_fp_id and FIRMS_DF is not None:
            mask = FIRMS_DF["FP ID"].astype(str) == str(firm_fp_id)
            if mask.any():
                firm_name = str(FIRMS_DF[mask].iloc[0]["Name"])

        if not firm_name:
            return jsonify({"error": "firm_name is required"}), 400

        # Compute all data
        pitch_data = _compute_firm_pitch_data(firm_name, office, practice_group, attorney_id)
        matched_firm = pitch_data.get("matched_firm", firm_name)

        # Build charts
        cand = pitch_data.get("candidate") or {}
        cand_school = cand.get("law_school", "")
        cand_firm_str = cand.get("current_firm", "")

        charts = {
            "hiring_trend": _gen_fp_hiring_trend_chart(
                pitch_data.get("hires_by_year", {}), matched_firm),
            "net_growth": _gen_fp_net_growth_chart(
                pitch_data.get("net_growth", {}), matched_firm),
            "exit_breakdown": _gen_fp_exit_breakdown_chart(
                pitch_data.get("dest_breakdown", {}), matched_firm),
            "inhouse_destinations": _gen_fp_inhouse_destinations_chart(
                pitch_data.get("inhouse_destinations", []), matched_firm),
            "team_seniority": _gen_fp_team_seniority_chart(
                pitch_data.get("team_by_title", {}),
                f"Team Composition — {matched_firm[:25]}"),
            "feeder_schools": _generate_feeder_bar_chart(
                pitch_data.get("feeder_schools", []), cand_school,
                f"Top Feeder Schools — {matched_firm[:22]}"),
            "feeder_firms": _generate_feeder_bar_chart(
                pitch_data.get("feeder_firms", []), cand_firm_str,
                f"Top Feeder Firms — {matched_firm[:22]}"),
        }
        pitch_data["_charts"] = charts

        # Generate narratives via Claude
        narratives = _generate_firm_pitch_narratives(pitch_data, custom_prompt, tone, anonymize)

        # Assemble PDF
        pdf_buf = _assemble_firm_pitch_pdf(narratives, pitch_data, recruiter_info, anonymize)

        safe_name = re.sub(r"[^\w\s-]", "", matched_firm).strip().replace(" ", "_")[:40]
        return send_file(
            pdf_buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"Firm_Pitch_{safe_name}.pdf",
        )
    except Exception as e:
        print(f"[Firm pitch generate error] {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _run_firm_status_migration():
    """Auto-detect Active Client firms from jobs/pipeline data on startup."""
    try:
        conn = ats_db.get_db()
        firms_with_jobs = set()
        for r in conn.execute(
            "SELECT DISTINCT e.name FROM jobs j JOIN employers e ON j.employer_id = e.id WHERE e.name != ''"
        ).fetchall():
            firms_with_jobs.add(r["name"])
        firms_with_pipeline = set()
        for r in conn.execute(
            """SELECT DISTINCT e.name FROM pipeline p
               JOIN jobs j ON p.job_id = j.id
               JOIN employers e ON j.employer_id = e.id
               WHERE e.name != ''"""
        ).fetchall():
            firms_with_pipeline.add(r["name"])
        conn.close()
        ats_db.migrate_firm_statuses_from_activity(firms_with_jobs, firms_with_pipeline)
        print(f"[Firm migration] Auto-detected {len(firms_with_jobs | firms_with_pipeline)} active client firms.")
    except Exception as e:
        print(f"[Firm migration error] {e}")


# ===========================================================================
# Admin — Feature Catalog
# ===========================================================================

@app.route("/admin")
def admin_catalog():
    """Internal feature catalog — requires login."""
    if not session.get("user_id"):
        return redirect("/")
    from datetime import date
    today = date.today().strftime("%B %d, %Y")
    return render_template("admin.html", today=today, user_name=session.get("user_name", "Admin"))


if __name__ == "__main__":
    print(f"Loaded {len(ATTORNEYS_DF)} attorneys, {len(HIRING_DF)} hiring records, {len(JOBS_DF)} jobs, {len(FIRMS_DF)} firms.")
    print(f"Hiring DNA computed for {len(HIRING_DNA)} firms. Pre-computing top candidates in background...")
    _run_firm_status_migration()
    threading.Thread(target=_precompute_top_candidates, daemon=True).start()
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
