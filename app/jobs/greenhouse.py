from app.browser.client import BrowserClient
from app.jobs.extractor import extract_job
from app.jobs.models import Job


def extract_greenhouse_job(
    browser: BrowserClient,
    url: str,
) -> Job:
    browser.open(url)

    page_text = browser.get_text()

    lines = [
        line.strip()
        for line in page_text.splitlines()
        if line.strip()
    ]

    title = lines[0]
    location = lines[1]

    company = browser.get_title()
    company = company.replace("Job Application for ", "")
    company = company.split(" at ")[-1]

    return extract_job(
        title=title,
        company=company,
        location=location,
        description=page_text,
        source="Greenhouse",
        url=url,
    )