from app.browser.client import BrowserClient
from app.jobs.extractor import extract_job
from app.jobs.models import Job


def extract_greenhouse_job(
    browser: BrowserClient,
    url: str,
) -> Job:
    browser.open(url)

    if browser.page is None:
        raise RuntimeError("Browser has not been started.")

    page_text = browser.get_text()

    lines = [
        line.strip()
        for line in page_text.splitlines()
        if line.strip()
    ]

    # Prefer the actual page heading instead of assuming
    # the first visible line is always the job title.
    title_element = browser.page.locator("h1")

    if title_element.count() > 0:
        title = title_element.first.inner_text().strip()
    elif lines:
        title = lines[0]
    else:
        title = "Unknown"

    # Try to get the location from the text immediately
    # after the title.
    location = "Unknown"

    if title in lines:
        title_index = lines.index(title)

        if title_index + 1 < len(lines):
            location = lines[title_index + 1]

    # Greenhouse page titles commonly contain the company name.
    page_title = browser.get_title()

    company = page_title

    if " at " in page_title:
        company = page_title.split(" at ")[-1]

    company = company.replace(
        "Job Application for ",
        "",
    ).strip()

    return extract_job(
        title=title,
        company=company,
        location=location,
        description=page_text,
        source="Greenhouse",
        url=url,
    )