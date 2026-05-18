"""
Seed the database with 20 fake responses per module.
Distributions are designed to reproduce the classic Tversky / Kahneman effects:
  Letter K: arm "first" overestimates (availability), arm "third" underestimates.
  Steve: most students pick Librarian (representativeness, base rate ignored).
  Taxi: probability framing anchors near 80 percent (witness accuracy),
        frequentist framing more diffuse, closer to the Bayesian 57 percent.

Usage:
  python seed_fake_data.py
"""
import os
import sys
import time
import uuid

import requests

BASE = os.getenv("SEED_BASE", "http://127.0.0.1:5001")

LETTER_K_FIRST = [
    (5, "I tried to think of words starting with K and got things like king, kid, knife. There seem to be a decent amount."),
    (8, "Recalled words like king, kitchen, knee, kind. Maybe somewhat common."),
    (10, "Words like keep, kind, key come to mind. Probably around 10 percent."),
    (10, "Counted in my head: king, kitchen, knife, knee. Several come to mind quickly."),
    (12, "Letter K starts many basic words. My estimate is around 12 percent."),
    (15, "There are quite a few common K words. I think 15 is reasonable."),
    (15, "Thought of about a dozen K starting words. Guessed proportionally."),
    (18, "Many words: king, kid, keep, kind, kitchen, key. Felt like a lot."),
    (20, "Felt like K starts a lot of common nouns. Estimated high."),
    (25, "Lots of common K words. Probably around a quarter of all words."),
]

LETTER_K_THIRD = [
    (0.5, "Could barely think of any word with K as the third letter. Very rare."),
    (1, "Couldn't recall any examples easily. Probably under 1 percent."),
    (2, "Thinking of words like ask, joke. Few examples came up."),
    (2, "Hard to retrieve examples. My best guess is 2 percent."),
    (3, "Only thought of a few like make, like. Position three is uncommon."),
    (3, "K is rare in English anyway, especially in this position."),
    (5, "Thinking systematically, K is rare so 5 percent seems right."),
    (5, "Letter frequencies suggest K is uncommon. Position matters less."),
    (8, "Took my time and came up with ask, joke, like, make. Could be 8 percent."),
    (10, "Considering English uses K in many positions, maybe higher than feels."),
]

STEVE_DATA = [
    ("Librarian", "Physician", "He sounds like a librarian. Shy and orderly fits perfectly."),
    ("Librarian", "Physician", "The description matches the librarian stereotype."),
    ("Librarian", "Farmer", "He sounds quiet, like someone who works in books."),
    ("Librarian", "Salesman", "Tidy and orderly equals librarian."),
    ("Librarian", "Physician", "Meek and detail oriented strongly suggests librarian."),
    ("Librarian", "Farmer", "His personality fits the librarian image."),
    ("Librarian", "Physician", "Shy and structured points to librarian over the others."),
    ("Librarian", "Salesman", "All those traits scream librarian to me."),
    ("Librarian", "Physician", "Picked librarian because of the order and detail orientation."),
    ("Librarian", "Farmer", "He fits the librarian stereotype too well."),
    ("Librarian", "Salesman", "Withdrawn personality says librarian."),
    ("Librarian", "Farmer", "Steve seems methodical, likely a librarian."),
    ("Librarian", "Physician", "Loves order and structure, classic librarian."),
    ("Farmer", "Librarian", "There are way more farmers than librarians in any population, so I picked farmer first based on base rates."),
    ("Farmer", "Salesman", "Statistically, there are more farmers, even if personality fits librarian."),
    ("Farmer", "Physician", "Base rate matters: farmer is more common as an occupation."),
    ("Physician", "Librarian", "He could be a meticulous doctor. Detail oriented fits."),
    ("Physician", "Farmer", "Maybe a careful pathologist or researcher type doctor."),
    ("Salesman", "Librarian", "I considered the base rates. More salesmen than librarians."),
    ("Airline Pilot", "Physician", "Pilots are very detail oriented and orderly. Could fit."),
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
    print(f"Seeding letter_k ({len(LETTER_K_FIRST)} first + {len(LETTER_K_THIRD)} third)...")
    ok = 0
    for num, text in LETTER_K_FIRST:
        if post("/submit/letter_k", fresh_cookies({"arm_letter_k": "first"}),
                {"numeric": num, "text": text}):
            ok += 1
    for num, text in LETTER_K_THIRD:
        if post("/submit/letter_k", fresh_cookies({"arm_letter_k": "third"}),
                {"numeric": num, "text": text}):
            ok += 1
    print(f"  letter_k: {ok}/{len(LETTER_K_FIRST) + len(LETTER_K_THIRD)} submitted")


def seed_steve():
    print(f"Seeding steve ({len(STEVE_DATA)})...")
    ok = 0
    for c1, c2, text in STEVE_DATA:
        if post("/submit/steve", fresh_cookies(),
                {"choice_1": c1, "choice_2": c2, "text": text}):
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
