"""Find open Greenhouse-hosted Data/Analytics Engineer postings not seen before.

Usage: .venv/bin/python scripts/find_greenhouse_jobs.py [--count 20] [--write]
Without --write the candidates are only printed. With --write they replace data/test_jobs.yaml
(the previous list should already be saved as data/test_jobs_batchN.yaml).
"""
import argparse
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TITLE = re.compile(r"\b(data engineer|analytics engineer|data platform engineer|data infrastructure engineer|"
                   r"software engineer,? data|data analytics engineer)\b", re.I)
SENIORITY_OUT = re.compile(r"\b(staff|principal|director|vp|manager|head|lead|intern|architect)\b", re.I)
NOT_A_FIT = re.compile(r"clearance|secret|embedded|full[- ]?stack|firmware|hardware|machine learning engineer", re.I)
MAX_PER_COMPANY = 3
US_OK = re.compile(r"united states|remote|usa|\bus\b|new york|seattle|,\s*[A-Z]{2}\b", re.I)
FOREIGN = re.compile(r"canada|india|\buk\b|london|germany|poland|spain|brazil|ireland|toronto|emea|apac|singapore|latam|mexico", re.I)


def seen_ids() -> set[str]:
    ids: set[str] = set()
    for path in [*ROOT.glob("data/test_jobs*.yaml"), ROOT / "data" / "submissions.json"]:
        if path.exists():
            ids.update(re.findall(r"/jobs/(\d+)", path.read_text()))
    return ids


def fetch_board(token: str) -> tuple[str, list]:
    try:
        with urllib.request.urlopen(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", timeout=15) as r:
            return token, json.load(r)["jobs"]
    except Exception:
        return token, []


def stays_on_greenhouse(url: str) -> bool:
    """The agent only accepts job-boards.greenhouse.io pages; company-site redirects would fail validation."""
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            final = r.geturl()
        return final.startswith("https://job-boards.greenhouse.io/") and "/jobs/" in final
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    used = seen_ids()
    tokens = sorted({t for line in (ROOT / "data" / "greenhouse_boards.txt").read_text().splitlines()
                     if not line.lstrip().startswith("#") for t in line.split()})
    candidates = []
    with ThreadPoolExecutor(16) as pool:
        for token, jobs in pool.map(fetch_board, tokens):
            for job in jobs:
                loc = job["location"]["name"]
                if (str(job["id"]) in used or not TITLE.search(job["title"]) or SENIORITY_OUT.search(job["title"]) or NOT_A_FIT.search(job["title"])
                        or not US_OK.search(loc) or FOREIGN.search(loc)):
                    continue
                candidates.append((token, job["title"].strip(), loc, f"https://job-boards.greenhouse.io/{token}/jobs/{job['id']}"))
    with ThreadPoolExecutor(16) as pool:
        live = [c for c, ok in zip(candidates, pool.map(lambda c: stays_on_greenhouse(c[3]), candidates)) if ok]
    per_company: dict[str, int] = {}
    picked = []
    for item in live:                      # keep the batch varied: no company dominates
        if per_company.get(item[0], 0) < MAX_PER_COMPANY and len(picked) < args.count:
            per_company[item[0]] = per_company.get(item[0], 0) + 1
            picked.append(item)
    for token, title, loc, url in picked:
        print(f"{token} | {title} | {loc} | {url}")
    print(f"\n{len(picked)} of {len(live)} live candidates ({len(candidates)} matched, {len(tokens)} boards searched)")
    if args.write:
        lines = ["# Batch 3: fresh Greenhouse postings (verified open; never seen in earlier batches or the ledger).",
                 "default_job: job_01", "", "jobs:"]
        for i, (token, title, loc, url) in enumerate(picked, 1):
            lines += [f"  job_{i:02d}:", f"    company: {token}", f"    title: {json.dumps(title)}", f"    url: {url}"]
        (ROOT / "data" / "test_jobs.yaml").write_text("\n".join(lines) + "\n")
        print("wrote data/test_jobs.yaml")


if __name__ == "__main__":
    main()
