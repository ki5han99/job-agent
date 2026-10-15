# Greenhouse live test jobs

Checked October 13, 2026. These URLs loaded specific job postings when checked;
availability must be checked again before each run. This is a manual MVP test
list, not an automated discovery queue.

| Company | Role | Location | URL |
| --- | --- | --- | --- |
| Garner Health | Data Engineer III | NYC, three office days per week | https://job-boards.greenhouse.io/garnerhealth/jobs/6181548004 |
| Garner Health | Senior Data Engineer | NYC, three office days per week | https://job-boards.greenhouse.io/garnerhealth/jobs/6181631004 |
| Underdog | Analytics Engineer II, Regulatory Reporting | United States, remote | https://job-boards.greenhouse.io/underdog/jobs/4727923005 |

The code reads `data/test_jobs.yaml`. Set `default_job` to a key in its `jobs`
mapping to choose the default. Run it with:

```sh
.venv/bin/python -B main.py
```

Override the configured default for one run with:

```sh
.venv/bin/python -B main.py 'https://job-boards.greenhouse.io/garnerhealth/jobs/6181548004'
```

The workflow must honor its filters and score thresholds. Do not force a SKIP
into form filling to obtain a test result. Never submit during these tests.
Unknown salary, authorization, sponsorship, relocation, and personal-history
answers must stay for human review. Underdog's sports question requires actual
candidate evidence; it is not permission to invent a personal connection.

The CLI currently closes its browser at the end. A persistent human handoff is
still an MVP gap; live assisted tests may hold cleanup until the human is done.

## Retired URLs

- Courier Health `5174299007`: returned the company listings page during the
  October 12 test.
- Garner Health `5844340004`: redirected to listings on October 13. The current
  Data Engineer III posting was found by following the company's board.
- Grafana Labs `5850008004`: redirected to listings on October 13.

Search snippets alone are not sufficient evidence that a job is still open.

## October 13 assisted test: Garner Data Engineer III

- Extraction returned the correct title and company; hard filters passed.
- Ollama score: 92; decision: AUTO_APPLY (preparation only).
- Seven fields verified: first name, last name, preferred name, email, phone
  country, phone, and LinkedIn.
- Resume verification failed. This does not establish whether the upload itself
  failed or verification ran before the upload completed; investigate next.
- Salary, authorization, sponsorship, relocation, location, and demographic
  questions remained for review. No prose questions were present.
- Report: NOT_READY, with 19 review entries and one failed verification.
- Parser included unnamed widget inputs and ambiguous Attach labels.
- Browser was held open by the assisted runner; no submission occurred.

This run used the existing uncommitted verifier edits already in the workspace;
it is not evidence that a clean checkout of the last commit behaves identically.
