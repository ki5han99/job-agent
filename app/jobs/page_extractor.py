from app.browser.client import BrowserClient
from app.jobs.extractor import extract_job
from app.jobs.models import Job


def extract_job_from_page(
    browser: BrowserClient,
    url: str,
    title: str,
    company: str,
    location: str,
    source: str,
) -> Job:
    browser.open(url)

    page_text = browser.get_text()

    return extract_job(
        title=title,
        company=company,
        location=location,
        description=page_text,
        source=source,
        url=url,
    )