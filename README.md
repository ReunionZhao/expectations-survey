# Probabilistic Judgement - Classroom Survey

Three independent, between-subject classroom probes (Tversky / Kahneman style):

| Module     | Arms                              | What students do                                 |
|------------|-----------------------------------|--------------------------------------------------|
| Letter K   | `first` / `third`                 | Estimate % of English words with K at that slot. Explain reasoning. |
| Steve      | (single)                          | Pick most + second most likely occupation from 5. Explain reasoning. |
| Taxi Cab   | `probability` / `frequentist`     | Estimate posterior P(Green) given witness. Explain reasoning. |

Each module is independent: separate URL, separate QR code, separate cookie. The teacher dashboard shows all three on one page.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set OPENAI_API_KEY, PUBLIC_BASE_URL, OPENAI_MODEL
export $(grep -v '^#' .env | xargs)
python app.py
```

Default port: **5001** (configurable via `PORT` env var). The original Gamble project uses 5000, so both can run side by side.

## URLs

| Role                | URL                                       |
|---------------------|-------------------------------------------|
| Teacher dashboard   | `http://localhost:5001/teacher`           |
| Student: Letter K   | `http://localhost:5001/survey/letter_k`   |
| Student: Steve      | `http://localhost:5001/survey/steve`      |
| Student: Taxi Cab   | `http://localhost:5001/survey/taxi`       |

Teacher dashboard auto-polls `/api/stats` every 3 seconds. Each student submission triggers background LLM classification (no manual button needed); the label typically appears within a few seconds on the next poll. A manual "Re-analyze unlabeled" button is provided as a fallback in case the LLM call failed.

## Random assignment

- `letter_k` and `taxi` use the "least-populated arm gets the new student" rule (with a random tie-breaker), so the two arms stay roughly balanced live.
- Arm assignment is set via cookie (`arm_letter_k`, `arm_taxi`) the first time the student loads the page and persists for 6 hours.
- A cookie `respondent_id` prevents a single student from submitting the same module twice. The same student can do all three modules (different module = different row).

## Visualizations per module

**Letter K**
- Per-arm response counts
- Separate histograms (5%-wide bins) of numeric guesses for each arm
- Separate LLM-label bar charts for each arm
- Separate word clouds for each arm
- Collapsible latest-responses table

**Steve**
- Bar chart of "most likely" occupation
- Bar chart of "second most likely" occupation
- 5x5 heatmap of first -> second flow
- LLM-label bar chart
- Word cloud
- Collapsible latest-responses table

**Taxi Cab**
- Per-arm response counts
- Separate histograms of numeric guesses for each arm
- Separate LLM-label bar charts for each arm
- Separate word clouds for each arm
- Collapsible latest-responses table

## LLM classification

Each module has its own classification prompt and label set (see `app.py` constants `PROMPT_LETTER_K`, `PROMPT_STEVE`, `PROMPT_TAXI`). Prompts are also exposed via `GET /api/prompts` and visible in the teacher dashboard ("View prompts" button).

Label sets:

| Module     | Labels                                                                                     |
|------------|--------------------------------------------------------------------------------------------|
| Letter K   | availability_heuristic / systematic_estimation / pure_guess / other                        |
| Steve      | representativeness / base_rate / mixed / other                                             |
| Taxi Cab   | witness_accuracy_anchor / bayesian / base_rate_anchor / mixed_or_other                     |

If `OPENAI_API_KEY` is unset OR the OpenAI call fails OR returns invalid JSON, the system falls back to a heuristic keyword classifier that yields the same label vocabulary.

## Reference answers for class discussion

- **Letter K** (true frequencies depend on which corpus you use):
  - K as first letter: roughly under 1% of common English words
  - K as third letter: roughly 1-3% of words (still uncommon)
- **Steve**:
  - The "rational" answer weights base rates: there are far more Farmers and Salesmen in any real population than Librarians or Airline Pilots, so unconditionally those should dominate. The classic finding: most people pick Librarian via personality match (representativeness).
- **Taxi Cab** (using base rate 25% Green, witness accuracy 80%):
  - Bayesian posterior P(Green | witness says Green) = (0.8 x 0.25) / (0.8 x 0.25 + 0.2 x 0.75) = 0.20 / 0.35 ~ **57%**
  - Common heuristic anchors: 80% (witness accuracy) or 25% (base rate).

## Deploy

Same pattern as the Gamble template - Render web service:

- Build: `pip install -r requirements.txt`
- Start: `gunicorn -w 2 -k gthread --threads 4 -b 0.0.0.0:$PORT app:app`
- Env vars: `OPENAI_API_KEY`, `OPENAI_MODEL`, `FLASK_SECRET_KEY`, `DB_PATH=/var/data/survey.db`, `PUBLIC_BASE_URL=https://your-app.onrender.com`
- Attach a persistent disk mounted at `/var/data`

## Reset

- Top-of-page "Reset all data" button wipes all three modules.
- Each module section has its own "Reset module" button (per-QR-code panel).

## Files

```
app.py                                  # Flask app, routes, classification logic
templates/survey_letter_k.html          # Letter K student page
templates/survey_steve.html             # Steve student page (with same-pick guard)
templates/survey_taxi.html              # Taxi Cab student page
templates/teacher.html                  # Dashboard layout (3 sections)
templates/thanks.html                   # Post-submit confirmation
static/style.css
static/dashboard.js                     # All Chart.js charts + auto-polling
```
