import io
import itertools
import json
import os
import random
import re
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import qrcode
from flask import Flask, jsonify, make_response, redirect, render_template, request, url_for
from openai import OpenAI
from PIL import Image
from wordcloud import STOPWORDS, WordCloud

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

DB_PATH = os.getenv("DB_PATH", "survey.db")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5001")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

ANALYSIS_EXECUTOR = ThreadPoolExecutor(max_workers=20)

MODULES = ("letter_k", "steve", "taxi")
MODULE_ARMS = {
    "letter_k": ("n", "ing"),
    "steve": (None,),
    "taxi": ("probability", "frequentist"),
}
STEVE_OCCUPATIONS = ("Farmer", "Salesman", "Airline Pilot", "Librarian", "Physician")
STEVE_RANKS = (1, 2, 3, 4, 5)

# All 6 permutations of the three modules, used by /survey/all to chain the
# questions in a uniformly-balanced random order per respondent.
MODULE_PERMUTATIONS = [list(p) for p in itertools.permutations(MODULES)]
COOKIE_MODULE_ORDER = "module_order"
COOKIE_MAX_AGE = 60 * 60 * 6

# ---------- Classification prompts ----------

PROMPT_LETTER_K = """
You are a strict classifier for classroom survey responses about word-frequency intuitions.

Context: The respondent estimated what percentage of 7-letter English words fit one of
two patterns (between-subject, only one arm seen):
  arm "n"   -> pattern "_ _ _ _ _ n _"  (n as the 6th of 7 letters)
  arm "ing" -> pattern "_ _ _ _ i n g"  (7-letter words ending in "ing")
Note: every "____ing" word is also a "_____n_" word, so logically the "ing" estimate
must be lower than the "n" estimate. Tversky-Kahneman found the opposite, driven by
availability: "ing" words are easier to recall.

Classify their reasoning into one of:
1) availability_heuristic - Mentally retrieved/recalled words and counted what came to mind
   (e.g., "I thought of words like running, eating, sitting"). Working from examples that
   came to mind, with little structural reasoning.
2) systematic_estimation - Used systematic / structural knowledge: letter frequency, position
   frequency, total English vocabulary size, dictionary knowledge, set-inclusion logic
   (e.g., notes that "ing" must be a subset of "n6"). Inference from general structure
   rather than recalled examples.
3) pure_guess - Explicitly says "guess", "no idea", "random", or extremely brief / uncertain.
4) other - Doesn't fit any category.

Return JSON only:
{{
  "label": "availability_heuristic | systematic_estimation | pure_guess | other",
  "confidence": 0.0-1.0,
  "rationale": "short explanation in <= 20 words"
}}

Arm: {arm}  (n = "_____n_", ing = "____ing")
Their numeric guess: {numeric}%
Their reasoning: {text}
""".strip()

PROMPT_STEVE = """
You are a strict classifier for classroom survey responses to the "Steve" problem
(Tversky and Kahneman, representativeness heuristic).

Context: Respondent read a description of Steve as shy, withdrawn, helpful, meek, tidy,
needing order and structure, with a passion for detail. They ranked all five occupations
(Farmer, Salesman, Airline Pilot, Librarian, Physician) from most likely (rank 1) to
least likely (rank 5). They then explained their reasoning.

Classify their reasoning into one of:
1) representativeness - Reasoning is dominated by matching Steve's personality description
   to a stereotype of the occupation ("sounds like a librarian", "fits the personality",
   "introverted matches"). Type-matching, ignoring base rates.
2) base_rate - Mentions or relies on how common each occupation is in the real world
   ("there are far more farmers than librarians", "population", "more salesmen exist").
3) mixed - Explicitly uses BOTH stereotype matching AND base rate reasoning.
4) other - Unclear, evasive, no real reasoning, or doesn't fit.

Return JSON only:
{{
  "label": "representativeness | base_rate | mixed | other",
  "confidence": 0.0-1.0,
  "rationale": "short explanation in <= 20 words"
}}

Their ranking (1 = most likely, 5 = least likely):
  1. {choice_1}
  2. {choice_2}
  3. {choice_3}
  4. {choice_4}
  5. {choice_5}
Their reasoning: {text}
""".strip()

PROMPT_TAXI = """
You are a strict classifier for classroom survey responses to the Tversky-Kahneman
taxi cab problem.

Context: 75% of cabs are Blue, 25% Green (or equivalent frequentist phrasing). A witness
identified a hit-and-run cab as Green. Witness accuracy is 80% (confuses colors 20% of the
time). The Bayesian posterior probability that the cab really is Green is ~57%.
Respondent saw ONE of two framings (probability narrative vs frequentist counts) and
gave a numeric probability plus a written explanation.

Classify their reasoning into one of:
1) witness_accuracy_anchor - Reasoning anchored on witness accuracy (around 80%) with
   little or no weight on the base rate. ("Witness was right 80% of the time, so 80%.")
2) bayesian - Combines base rate AND witness accuracy in a Bayesian way (or attempts to),
   mentions both pieces of evidence, computes a posterior, or arrives near ~57%.
3) base_rate_anchor - Reasoning anchored heavily on base rate of Green cabs (around 25%
   or lower), giving little weight to witness identification.
4) mixed_or_other - Mixed, unclear, or doesn't fit any of the above cleanly.

Return JSON only:
{{
  "label": "witness_accuracy_anchor | bayesian | base_rate_anchor | mixed_or_other",
  "confidence": 0.0-1.0,
  "rationale": "short explanation in <= 20 words"
}}

Arm: {arm}  (probability or frequentist framing)
Their numeric guess: {numeric}%
Their reasoning: {text}
""".strip()

MODULE_PROMPTS = {
    "letter_k": PROMPT_LETTER_K,
    "steve": PROMPT_STEVE,
    "taxi": PROMPT_TAXI,
}

MODULE_LABELS = {
    "letter_k": ("availability_heuristic", "systematic_estimation", "pure_guess", "other"),
    "steve": ("representativeness", "base_rate", "mixed", "other"),
    "taxi": ("witness_accuracy_anchor", "bayesian", "base_rate_anchor", "mixed_or_other"),
}

# ---------- DB ----------

def db_conn():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                respondent_id TEXT NOT NULL,
                module TEXT NOT NULL CHECK (module IN ('letter_k', 'steve', 'taxi')),
                arm TEXT,
                numeric_value REAL,
                choice_1 TEXT,
                choice_2 TEXT,
                choice_3 TEXT,
                choice_4 TEXT,
                choice_5 TEXT,
                text_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                label TEXT,
                label_confidence REAL,
                label_rationale TEXT,
                label_source TEXT,
                UNIQUE(respondent_id, module)
            )
            """
        )
        # Migration: older databases pre-date the rank columns (choice_3..5)
        # and the module_order column (recorded for the /survey/all chained flow).
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(responses)").fetchall()}
        for col in ("choice_3", "choice_4", "choice_5", "module_order"):
            if col not in existing:
                conn.execute(f"ALTER TABLE responses ADD COLUMN {col} TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_module ON responses(module)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_module_arm ON responses(module, arm)")
        conn.commit()


init_db()


# ---------- Helpers ----------

def get_public_base_url():
    configured = os.getenv("PUBLIC_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    return request.host_url.rstrip("/")


def get_or_set_respondent():
    rid = request.cookies.get("respondent_id")
    if not rid:
        rid = str(uuid.uuid4())
    return rid


def assign_arm_balanced(module):
    arms = MODULE_ARMS[module]
    if arms == (None,):
        return None
    try:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT arm, COUNT(*) AS c FROM responses WHERE module = ? GROUP BY arm",
                (module,),
            ).fetchall()
        counts = {a: 0 for a in arms}
        for row in rows:
            if row["arm"] in counts:
                counts[row["arm"]] = row["c"]
        min_c = min(counts.values())
        candidates = [a for a, c in counts.items() if c == min_c]
        return random.choice(candidates)
    except Exception:
        return random.choice(arms)


def get_arm_from_cookie_or_assign(module):
    arms = MODULE_ARMS[module]
    if arms == (None,):
        return None
    cookie_key = f"arm_{module}"
    v = request.cookies.get(cookie_key)
    if v in arms:
        return v
    return assign_arm_balanced(module)


def has_submitted(respondent_id, module):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM responses WHERE respondent_id = ? AND module = ? LIMIT 1",
            (respondent_id, module),
        ).fetchone()
    return row is not None


def assign_module_order_balanced():
    """Pick the permutation of MODULES with the fewest distinct respondents
    assigned so far (random among ties)."""
    try:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT module_order, COUNT(DISTINCT respondent_id) AS c "
                "FROM responses WHERE module_order IS NOT NULL "
                "GROUP BY module_order"
            ).fetchall()
        counts = {",".join(p): 0 for p in MODULE_PERMUTATIONS}
        for r in rows:
            key = r["module_order"]
            if key in counts:
                counts[key] = r["c"]
        min_c = min(counts.values())
        candidates = [k.split(",") for k, c in counts.items() if c == min_c]
        return random.choice(candidates)
    except Exception:
        return random.choice(MODULE_PERMUTATIONS)


def get_or_assign_module_order():
    """Read the module_order cookie if valid, otherwise pick a balanced one."""
    cookie = request.cookies.get(COOKIE_MODULE_ORDER, "")
    parsed = [m for m in cookie.split(",") if m in MODULES]
    if len(parsed) == len(MODULES) and set(parsed) == set(MODULES):
        return parsed
    return assign_module_order_balanced()


def next_module_in_sequence(respondent_id, just_submitted=None):
    """If the respondent is in a /survey/all chain, return the next module they
    have not yet submitted. Returns None if not in a chain or all done."""
    cookie = request.cookies.get(COOKIE_MODULE_ORDER, "")
    order = [m for m in cookie.split(",") if m in MODULES]
    if len(order) != len(MODULES) or set(order) != set(MODULES):
        return None
    for m in order:
        if m == just_submitted:
            continue
        if not has_submitted(respondent_id, m):
            return m
    return None


# ---------- LLM classification ----------

def heuristic_label(module, text):
    t = (text or "").lower()
    if module == "letter_k":
        avail = ["think of words", "came to mind", "remembered", "examples like",
                 "words like", "i thought of", "running", "eating", "sitting",
                 "ending in ing", "ends with ing"]
        syst = ["frequency", "alphabet", "26 letters", "position", "subset",
                "must be lower", "logically", "total words", "dictionary",
                "set of all", "all ing words"]
        a = sum(1 for w in avail if w in t)
        s = sum(1 for w in syst if w in t)
        if a > s and a >= 1:
            label = "availability_heuristic"
        elif s > a and s >= 1:
            label = "systematic_estimation"
        elif "guess" in t or "no idea" in t or "random" in t:
            label = "pure_guess"
        else:
            label = "other"
    elif module == "steve":
        rep = ["personality", "fits", "stereotype", "shy", "introvert", "quiet",
               "sounds like", "matches", "description"]
        bse = ["base rate", "more common", "more farmers", "population", "how many",
               "frequency", "rare occupation", "common occupation"]
        r = sum(1 for w in rep if w in t)
        b = sum(1 for w in bse if w in t)
        if r > 0 and b > 0:
            label = "mixed"
        elif r > b:
            label = "representativeness"
        elif b > r:
            label = "base_rate"
        else:
            label = "other"
    elif module == "taxi":
        if "bayes" in t or ("base rate" in t and ("witness" in t or "accuracy" in t)):
            label = "bayesian"
        elif "80" in t and "witness" in t:
            label = "witness_accuracy_anchor"
        elif "25" in t or "15" in t or "base rate" in t:
            label = "base_rate_anchor"
        else:
            label = "mixed_or_other"
    else:
        label = "other"
    return {"label": label, "confidence": 0.5, "rationale": "Keyword fallback", "source": "heuristic"}


def classify_with_openai(module, arm, numeric, choices, text):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return heuristic_label(module, text)

    prompt = MODULE_PROMPTS[module].format(
        arm=arm or "",
        numeric=numeric if numeric is not None else "",
        choice_1=(choices[0] if len(choices) > 0 else None) or "",
        choice_2=(choices[1] if len(choices) > 1 else None) or "",
        choice_3=(choices[2] if len(choices) > 2 else None) or "",
        choice_4=(choices[3] if len(choices) > 3 else None) or "",
        choice_5=(choices[4] if len(choices) > 4 else None) or "",
        text=(text or "").strip(),
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": "You return strict JSON only, no markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        raw = response.output_text.strip()
    except Exception:
        return heuristic_label(module, text)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not m:
            return heuristic_label(module, text)
        try:
            payload = json.loads(m.group(0))
        except json.JSONDecodeError:
            return heuristic_label(module, text)

    valid = set(MODULE_LABELS[module])
    label = payload.get("label", "other")
    if label not in valid:
        label = list(valid)[-1]  # fallback to last (typically "other" / "mixed_or_other")
    confidence = float(payload.get("confidence", 0.5))
    rationale = str(payload.get("rationale", "")).strip()[:200]
    return {
        "label": label,
        "confidence": max(0.0, min(1.0, confidence)),
        "rationale": rationale,
        "source": "openai",
    }


def analyze_and_store(response_id, module, arm, numeric, choices, text):
    result = classify_with_openai(module, arm, numeric, choices, text)
    try:
        with db_conn() as conn:
            conn.execute(
                """
                UPDATE responses
                SET label = ?, label_confidence = ?, label_rationale = ?, label_source = ?
                WHERE id = ?
                """,
                (result["label"], result["confidence"], result["rationale"],
                 result["source"], response_id),
            )
            conn.commit()
    except Exception:
        pass


# ---------- Stats ----------

def fetch_stats():
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, respondent_id, module, arm, numeric_value,
                   choice_1, choice_2, choice_3, choice_4, choice_5,
                   text_value, created_at, label
            FROM responses
            ORDER BY id DESC
            """
        ).fetchall()

    per_module = {m: [] for m in MODULES}
    for r in rows:
        per_module[r["module"]].append(dict(r))

    # ---- letter_k (now: "Example" question with arms n and ing) ----
    letter_k_arms = MODULE_ARMS["letter_k"]  # ("n", "ing")
    k_stats = {
        "total": len(per_module["letter_k"]),
        "by_arm": {a: [] for a in letter_k_arms},
        "label_counts_by_arm": {
            a: {lbl: 0 for lbl in MODULE_LABELS["letter_k"]} for a in letter_k_arms
        },
        "label_unclassified_by_arm": {a: 0 for a in letter_k_arms},
        "latest": [],
    }
    for r in per_module["letter_k"]:
        arm = r["arm"]
        if arm in letter_k_arms:
            if r["numeric_value"] is not None:
                k_stats["by_arm"][arm].append(r["numeric_value"])
            if r["label"] in MODULE_LABELS["letter_k"]:
                k_stats["label_counts_by_arm"][arm][r["label"]] += 1
            else:
                k_stats["label_unclassified_by_arm"][arm] += 1
        k_stats["latest"].append({
            "arm": r["arm"],
            "numeric": r["numeric_value"],
            "text": r["text_value"],
            "label": r["label"] or "unclassified",
            "created_at": r["created_at"],
        })

    # ---- steve (now: full 1-5 ranking) ----
    # rank_counts[rank_index 0..4][occupation] = number of respondents who placed
    # that occupation at that rank.
    steve_stats = {
        "total": 0,  # counts only respondents with a complete ranking
        "rank_counts": [{o: 0 for o in STEVE_OCCUPATIONS} for _ in range(5)],
        "label_counts": {lbl: 0 for lbl in MODULE_LABELS["steve"]},
        "label_unclassified": 0,
        "latest": [],
    }
    for r in per_module["steve"]:
        ranking = [r["choice_1"], r["choice_2"], r["choice_3"], r["choice_4"], r["choice_5"]]
        complete = (
            all(c in STEVE_OCCUPATIONS for c in ranking)
            and len(set(ranking)) == len(STEVE_OCCUPATIONS)
        )
        if complete:
            steve_stats["total"] += 1
            for i, occ in enumerate(ranking):
                steve_stats["rank_counts"][i][occ] += 1
            if r["label"] in MODULE_LABELS["steve"]:
                steve_stats["label_counts"][r["label"]] += 1
            else:
                steve_stats["label_unclassified"] += 1
        steve_stats["latest"].append({
            "ranking": ranking,
            "text": r["text_value"],
            "label": r["label"] or "unclassified",
            "created_at": r["created_at"],
        })

    # ---- taxi ----
    taxi_stats = {
        "total": len(per_module["taxi"]),
        "by_arm": {"probability": [], "frequentist": []},
        "label_counts_by_arm": {
            "probability": {lbl: 0 for lbl in MODULE_LABELS["taxi"]},
            "frequentist": {lbl: 0 for lbl in MODULE_LABELS["taxi"]},
        },
        "label_unclassified_by_arm": {"probability": 0, "frequentist": 0},
        "latest": [],
    }
    for r in per_module["taxi"]:
        arm = r["arm"]
        if arm in ("probability", "frequentist"):
            if r["numeric_value"] is not None:
                taxi_stats["by_arm"][arm].append(r["numeric_value"])
            if r["label"] in MODULE_LABELS["taxi"]:
                taxi_stats["label_counts_by_arm"][arm][r["label"]] += 1
            else:
                taxi_stats["label_unclassified_by_arm"][arm] += 1
        taxi_stats["latest"].append({
            "arm": r["arm"],
            "numeric": r["numeric_value"],
            "text": r["text_value"],
            "label": r["label"] or "unclassified",
            "created_at": r["created_at"],
        })

    return {
        "letter_k": k_stats,
        "steve": steve_stats,
        "taxi": taxi_stats,
    }


# ---------- Routes: student ----------

@app.route("/")
def index():
    return redirect(url_for("teacher"))


def _render_module(module, template_name):
    rid = get_or_set_respondent()
    if has_submitted(rid, module):
        return _finish_or_chain(rid, module)
    arm = get_arm_from_cookie_or_assign(module)
    context = {"arm": arm, "module": module}
    if module == "steve":
        context["occupations"] = STEVE_OCCUPATIONS
    response = make_response(render_template(template_name, **context))
    response.set_cookie("respondent_id", rid, max_age=COOKIE_MAX_AGE)
    if arm is not None:
        response.set_cookie(f"arm_{module}", arm, max_age=COOKIE_MAX_AGE)
    return response


@app.route("/survey/all")
def survey_all():
    """Entry point for the combined random-order survey. Assigns a balanced
    permutation of the three modules (or reuses the one from the cookie), sets
    the respondent cookie, and redirects to the first un-submitted module."""
    rid = get_or_set_respondent()
    order = get_or_assign_module_order()
    target = None
    for m in order:
        if not has_submitted(rid, m):
            target = m
            break

    if target is None:
        response = make_response(render_template("thanks.html", module=None, all_done=True))
    else:
        response = make_response(redirect(url_for(f"survey_{target}")))
    response.set_cookie("respondent_id", rid, max_age=COOKIE_MAX_AGE)
    response.set_cookie(COOKIE_MODULE_ORDER, ",".join(order), max_age=COOKIE_MAX_AGE)
    return response


@app.route("/survey/letter_k")
def survey_letter_k():
    return _render_module("letter_k", "survey_letter_k.html")


@app.route("/survey/steve")
def survey_steve():
    return _render_module("steve", "survey_steve.html")


@app.route("/survey/taxi")
def survey_taxi():
    return _render_module("taxi", "survey_taxi.html")


@app.route("/sample/<module>")
def sample_module(module):
    """Teacher preview.
    Without ?arm= and for multi-arm modules: renders a side-by-side view of both arms
      (each in an iframe). For single-arm modules (Steve): renders the survey directly.
    With ?arm=<arm>: renders just that arm (used as iframe content). No cookies set,
      form is disabled, nothing is recorded."""
    if module not in MODULES:
        return "Invalid module", 400
    arms_for_module = MODULE_ARMS[module]
    requested_arm = request.args.get("arm")

    # Multi-arm side-by-side view (only when no ?arm= and module has multiple arms)
    if requested_arm is None and arms_for_module != (None,):
        return render_template("sample_view.html", module=module, arms=list(arms_for_module))

    # Single-arm view (iframe content or single-arm module)
    if arms_for_module == (None,):
        arm = None
    elif requested_arm in arms_for_module:
        arm = requested_arm
    else:
        arm = arms_for_module[0]
    template = f"survey_{module}.html"
    context = {"arm": arm, "module": module, "preview": True}
    if module == "steve":
        context["occupations"] = STEVE_OCCUPATIONS
    return render_template(template, **context)


def _submit_module(module, arm, numeric_value, choices, text):
    """choices: tuple/list of up to 5 entries (pad with None)."""
    padded = list(choices) + [None] * (5 - len(choices))
    rid = get_or_set_respondent()
    order_cookie = request.cookies.get(COOKIE_MODULE_ORDER) or None
    if has_submitted(rid, module):
        return _finish_or_chain(rid, module)
    created_at = datetime.now(timezone.utc).isoformat()
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO responses
            (respondent_id, module, arm, numeric_value,
             choice_1, choice_2, choice_3, choice_4, choice_5,
             text_value, created_at, module_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rid, module, arm, numeric_value,
             padded[0], padded[1], padded[2], padded[3], padded[4],
             text, created_at, order_cookie),
        )
        new_id = cur.lastrowid
        conn.commit()
    ANALYSIS_EXECUTOR.submit(
        analyze_and_store, new_id, module, arm, numeric_value, padded, text
    )
    return _finish_or_chain(rid, module)


def _finish_or_chain(rid, just_submitted):
    """If the respondent is mid-sequence, redirect to the next module.
    Otherwise show thanks."""
    nxt = next_module_in_sequence(rid, just_submitted=just_submitted)
    if nxt:
        return redirect(url_for(f"survey_{nxt}"))
    in_chain = bool(request.cookies.get(COOKIE_MODULE_ORDER))
    return render_template(
        "thanks.html",
        module=just_submitted,
        all_done=in_chain,
    )


@app.post("/submit/letter_k")
def submit_letter_k():
    arm = request.cookies.get("arm_letter_k")
    if arm not in MODULE_ARMS["letter_k"]:
        arm = assign_arm_balanced("letter_k")
    try:
        pct = float(request.form.get("numeric") or "")
    except ValueError:
        return "Invalid percentage", 400
    if pct < 0 or pct > 100:
        return "Percentage must be 0 to 100", 400
    text = (request.form.get("text") or "").strip()
    if not text:
        return "Reasoning required", 400
    return _submit_module("letter_k", arm, pct, (), text)


@app.post("/submit/steve")
def submit_steve():
    ranking = [request.form.get(f"choice_{i}") for i in range(1, 6)]
    if any(c not in STEVE_OCCUPATIONS for c in ranking):
        return "Invalid occupation choices", 400
    if len(set(ranking)) != len(STEVE_OCCUPATIONS):
        return "Each occupation must be ranked exactly once", 400
    text = (request.form.get("text") or "").strip()
    if not text:
        return "Reasoning required", 400
    return _submit_module("steve", None, None, ranking, text)


@app.post("/submit/taxi")
def submit_taxi():
    arm = request.cookies.get("arm_taxi")
    if arm not in MODULE_ARMS["taxi"]:
        arm = assign_arm_balanced("taxi")
    try:
        pct = float(request.form.get("numeric") or "")
    except ValueError:
        return "Invalid percentage", 400
    if pct < 0 or pct > 100:
        return "Percentage must be 0 to 100", 400
    text = (request.form.get("text") or "").strip()
    if not text:
        return "Reasoning required", 400
    return _submit_module("taxi", arm, pct, (), text)


# ---------- Routes: teacher ----------

@app.route("/teacher")
def teacher():
    return render_template("teacher.html", public_base_url=get_public_base_url())


@app.route("/api/stats")
def api_stats():
    return jsonify(fetch_stats())


@app.route("/api/prompts")
def api_prompts():
    return jsonify({m: MODULE_PROMPTS[m] for m in MODULES})


@app.route("/api/qr/<module>")
def api_qr(module):
    if module == "all":
        url = f"{get_public_base_url()}/survey/all"
    elif module in MODULES:
        url = f"{get_public_base_url()}/survey/{module}"
    else:
        return "Invalid module", 400
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "image/png"
    return resp


def _wordcloud_png(texts):
    text = " ".join(t for t in texts if t).strip()
    if not text:
        empty = Image.new("RGB", (900, 360), "white")
        buf = io.BytesIO()
        empty.save(buf, format="PNG")
        buf.seek(0)
        return buf.getvalue()

    base_stopwords = set(STOPWORDS)
    base_stopwords.update({
        "would", "could", "also", "because", "really", "think", "thought",
        "people", "person", "thing", "things", "one", "two",
        "maybe", "probably", "guess", "just",
        "letter", "word", "words", "pattern", "form",
        "cab", "cabs", "taxi", "witness", "color", "colour", "green", "blue",
        "occupation", "steve", "librarian", "farmer", "salesman", "pilot", "physician",
    })

    palette = ["#0a113f", "#007f78", "#00a6a6", "#00a651", "#6e2436"]

    def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        return random.choice(palette)

    wc = WordCloud(
        width=900,
        height=360,
        background_color="white",
        stopwords=base_stopwords,
        max_words=120,
        collocations=False,
        prefer_horizontal=0.9,
        color_func=color_func,
        random_state=42,
    ).generate(text)

    img = wc.to_image()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


@app.route("/api/wordcloud_image/<module>/<arm>")
def api_wordcloud_image(module, arm):
    if module not in MODULES:
        return "Invalid module", 400
    arms_for_module = MODULE_ARMS[module]
    if arm == "all" and arms_for_module == (None,):
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT text_value FROM responses WHERE module = ? ORDER BY id DESC LIMIT 1000",
                (module,),
            ).fetchall()
    elif arm in arms_for_module:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT text_value FROM responses WHERE module = ? AND arm = ? ORDER BY id DESC LIMIT 1000",
                (module, arm),
            ).fetchall()
    else:
        return "Invalid arm for this module", 400

    png = _wordcloud_png([r["text_value"] for r in rows])
    resp = make_response(png)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "no-store"
    return resp


_PENDING_COLS = (
    "id, module, arm, numeric_value, "
    "choice_1, choice_2, choice_3, choice_4, choice_5, text_value"
)


def _row_choices(r):
    return [r["choice_1"], r["choice_2"], r["choice_3"], r["choice_4"], r["choice_5"]]


@app.post("/api/analyze_pending")
def api_analyze_pending():
    """Manual fallback: re-fire analysis for any rows that are still unlabeled."""
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT {_PENDING_COLS} FROM responses WHERE label IS NULL"
        ).fetchall()
    for r in rows:
        ANALYSIS_EXECUTOR.submit(
            analyze_and_store,
            r["id"], r["module"], r["arm"], r["numeric_value"],
            _row_choices(r), r["text_value"],
        )
    return jsonify({"ok": True, "queued": len(rows)})


@app.post("/api/analyze_pending/<module>")
def api_analyze_pending_module(module):
    """Same as /api/analyze_pending but scoped to a single module."""
    if module not in MODULES:
        return "Invalid module", 400
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT {_PENDING_COLS} FROM responses WHERE label IS NULL AND module = ?",
            (module,),
        ).fetchall()
    for r in rows:
        ANALYSIS_EXECUTOR.submit(
            analyze_and_store,
            r["id"], r["module"], r["arm"], r["numeric_value"],
            _row_choices(r), r["text_value"],
        )
    return jsonify({"ok": True, "queued": len(rows), "module": module})


@app.post("/api/reset")
def api_reset():
    with db_conn() as conn:
        conn.execute("DELETE FROM responses")
        conn.commit()
    return jsonify({"ok": True})


@app.post("/api/reset_module/<module>")
def api_reset_module(module):
    if module not in MODULES:
        return "Invalid module", 400
    with db_conn() as conn:
        conn.execute("DELETE FROM responses WHERE module = ?", (module,))
        conn.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=True)
