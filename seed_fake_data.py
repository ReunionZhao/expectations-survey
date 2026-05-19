"""
Seed the database with 20 fake responses per module.
Distributions are designed to reproduce the classic Tversky / Kahneman effects:
  Example: arm "ing" (____ing) is over-estimated thanks to availability, while
           arm "n" (_____n_) — which strictly contains "ing" — is under-estimated.
  Steve:   most students rank Librarian #1 (representativeness, base rate ignored).
  Taxi:    probability framing anchors near 80 percent (witness accuracy),
           frequentist framing more diffuse, closer to the Bayesian 57 percent.

Usage:
  python seed_fake_data.py
"""
import os
import sys
import time
import uuid

import requests

BASE = os.getenv("SEED_BASE", "https://expectations-survey.onrender.com")

LETTER_K_N = [
    (5, "Hard to come up with 7-letter words with n as the sixth letter. Felt rare."),
    (5, "Couldn't think of many obvious examples. Maybe 5 percent."),
    (6, "Tried a few candidates. Few came to mind so my estimate is low."),
    (8, "Words ending in -n- _ are not what jumps to mind. Probably uncommon."),
    (8, "Mostly drew a blank. Guessing on the low end."),
    (10, "Did not retrieve many quickly. Settled around 10 percent."),
    (10, "Estimated based on how few I could enumerate."),
    (12, "A bit higher because n is a common letter overall, but position is restrictive."),
    (14, "Tough constraint. Picked a middling number."),
    (15, "Pulled a few like 'meaning' would count if i shift letters, so maybe modest."),
]

LETTER_K_ING = [
    (12, "Lots of '-ing' words came to mind: running, eating, sitting. Felt common."),
    (15, "There are tons of present participles. 15 percent feels right."),
    (18, "Loads of verbs in -ing form. Probably high."),
    (20, "Recalled many examples easily, so I estimated 20 percent."),
    (22, "Examples kept coming: walking, jumping, talking, painting."),
    (25, "Felt like a quarter of 7-letter words end in ing."),
    (25, "So many ing words pop into my head."),
    (28, "Strongly skewed by ease of recall. High estimate."),
    (30, "Recalled dozens. Picked something on the higher end."),
    (32, "Verb-ing seems incredibly common in English. Went high."),
]

# Each row: a 5-tuple of (rank1, rank2, rank3, rank4, rank5) + reasoning text.
STEVE_DATA = [
    (("Librarian", "Physician", "Airline Pilot", "Salesman", "Farmer"),
     "Librarian first - shy, orderly, detail-oriented. Physician second because of meticulousness."),
    (("Librarian", "Physician", "Farmer", "Salesman", "Airline Pilot"),
     "The personality matches the librarian stereotype almost perfectly."),
    (("Librarian", "Physician", "Airline Pilot", "Farmer", "Salesman"),
     "Sounds quiet, like someone who works in books. Pilot last? actually third for detail."),
    (("Librarian", "Physician", "Airline Pilot", "Salesman", "Farmer"),
     "Tidy and orderly = librarian. Then physician for the precision."),
    (("Librarian", "Physician", "Airline Pilot", "Farmer", "Salesman"),
     "Meek and detail oriented strongly suggests librarian."),
    (("Librarian", "Airline Pilot", "Physician", "Farmer", "Salesman"),
     "His personality fits the librarian image; pilots are also detail-oriented."),
    (("Librarian", "Physician", "Airline Pilot", "Salesman", "Farmer"),
     "Shy and structured points to librarian over the others."),
    (("Librarian", "Physician", "Airline Pilot", "Farmer", "Salesman"),
     "All those traits scream librarian to me."),
    (("Librarian", "Physician", "Airline Pilot", "Farmer", "Salesman"),
     "Picked librarian because of the order and detail orientation."),
    (("Librarian", "Physician", "Airline Pilot", "Salesman", "Farmer"),
     "He fits the librarian stereotype too well."),
    (("Librarian", "Physician", "Farmer", "Salesman", "Airline Pilot"),
     "Withdrawn personality says librarian."),
    (("Librarian", "Airline Pilot", "Physician", "Salesman", "Farmer"),
     "Steve seems methodical, likely a librarian."),
    (("Librarian", "Physician", "Airline Pilot", "Salesman", "Farmer"),
     "Loves order and structure, classic librarian."),
    (("Farmer", "Salesman", "Librarian", "Physician", "Airline Pilot"),
     "There are way more farmers than librarians in any population, so I ranked by base rate."),
    (("Farmer", "Salesman", "Physician", "Librarian", "Airline Pilot"),
     "Statistically, more farmers than librarians, even if personality fits librarian."),
    (("Farmer", "Salesman", "Physician", "Librarian", "Airline Pilot"),
     "Base rate matters: farmer is the most common occupation."),
    (("Physician", "Librarian", "Airline Pilot", "Farmer", "Salesman"),
     "He could be a meticulous doctor. Detail oriented fits a physician."),
    (("Physician", "Librarian", "Airline Pilot", "Salesman", "Farmer"),
     "Maybe a careful pathologist or researcher type doctor."),
    (("Salesman", "Farmer", "Librarian", "Physician", "Airline Pilot"),
     "I considered the base rates. More salesmen than librarians."),
    (("Airline Pilot", "Physician", "Librarian", "Salesman", "Farmer"),
     "Pilots are very detail oriented and orderly. Could fit."),
]

TAXI_PROBABILITY = [
    (30, "The base rate of green cabs is only 25 percent. I weighted that in."),
    (50, "Started at 50 50 then nudged up slightly because the witness saw green."),
    (60, "The witness is 80 percent reliable, but green cabs are rare."),
    (70, "Mostly trust the witness but accounted a bit for base rates."),
    (75, "Witness accuracy is high, so I lean toward green."),
    (80, "The witness identifies green correctly 80 percent of the time, so 80 percent."),
    (80, "Witness was right 80 percent of the time so that is my answer."),
    (80, "Eighty percent based on the testimony reliability."),
    (85, "Eighty percent witness accuracy plus the green identification, slightly higher."),
    (50, "Tried to balance the witness reliability against base rates."),
]

TAXI_FREQUENTIST = [
    (40, "Counted: out of 20 green plus 15 blue identified as green, 20 of 35 are actually green."),
    (50, "Used the explicit numbers to estimate around half."),
    (55, "Computed using the counts. About 55 percent green."),
    (57, "Twenty out of 35 cabs identified as green are actually green."),
    (57, "Applied Bayes with the counts. 20 divided by 35 is around 57 percent."),
    (60, "Roughly 60 percent based on the breakdown of counts."),
    (65, "Roughly 65 percent given the numbers."),
    (70, "Witness saw green and most green cabs are spotted correctly."),
    (25, "Stuck close to the base rate of 25 percent green."),
    (30, "Base rate is low so my answer stays low even with the witness."),
]


def post(path, cookies, data):
    r = requests.post(f"{BASE}{path}", cookies=cookies, data=data, timeout=15)
    if r.status_code != 200:
        print(f"  FAIL {path}: {r.status_code} {r.text[:200]}")
        return False
    return True


def fresh_cookies(extra=None):
    cookies = {"respondent_id": str(uuid.uuid4())}
    if extra:
        cookies.update(extra)
    return cookies


def seed_letter_k():
    print(f"Seeding letter_k ({len(LETTER_K_N)} n + {len(LETTER_K_ING)} ing)...")
    ok = 0
    for num, text in LETTER_K_N:
        if post("/submit/letter_k", fresh_cookies({"arm_letter_k": "n"}),
                {"numeric": num, "text": text}):
            ok += 1
    for num, text in LETTER_K_ING:
        if post("/submit/letter_k", fresh_cookies({"arm_letter_k": "ing"}),
                {"numeric": num, "text": text}):
            ok += 1
    print(f"  letter_k: {ok}/{len(LETTER_K_N) + len(LETTER_K_ING)} submitted")


def seed_steve():
    print(f"Seeding steve ({len(STEVE_DATA)})...")
    ok = 0
    for ranking, text in STEVE_DATA:
        payload = {f"choice_{i+1}": occ for i, occ in enumerate(ranking)}
        payload["text"] = text
        if post("/submit/steve", fresh_cookies(), payload):
            ok += 1
    print(f"  steve: {ok}/{len(STEVE_DATA)} submitted")


def seed_taxi():
    print(f"Seeding taxi ({len(TAXI_PROBABILITY)} probability + {len(TAXI_FREQUENTIST)} frequentist)...")
    ok = 0
    for num, text in TAXI_PROBABILITY:
        if post("/submit/taxi", fresh_cookies({"arm_taxi": "probability"}),
                {"numeric": num, "text": text}):
            ok += 1
    for num, text in TAXI_FREQUENTIST:
        if post("/submit/taxi", fresh_cookies({"arm_taxi": "frequentist"}),
                {"numeric": num, "text": text}):
            ok += 1
    print(f"  taxi: {ok}/{len(TAXI_PROBABILITY) + len(TAXI_FREQUENTIST)} submitted")


def main():
    print(f"Target: {BASE}")
    try:
        r = requests.get(f"{BASE}/api/stats", timeout=3)
        r.raise_for_status()
    except Exception as e:
        print(f"Server not reachable at {BASE}: {e}", file=sys.stderr)
        sys.exit(1)

    seed_letter_k()
    seed_steve()
    seed_taxi()
    time.sleep(0.5)
    print("Done. Open the teacher dashboard to see the analysis.")


if __name__ == "__main__":
    main()
