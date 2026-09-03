from playwright.sync_api import Browser, Page, Playwright, sync_playwright


class BrowserClient:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    def start(self) -> None:
        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.launch(
            headless=False
        )

        self.page = self.browser.new_page()

    def open(self, url: str) -> None:
        if self.page is None:
            raise RuntimeError("Browser has not been started.")

        self.page.goto(url)

    def get_title(self) -> str:
        if self.page is None:
            raise RuntimeError("Browser has not been started.")

        return self.page.title()

    def get_text(self) -> str:
        if self.page is None:
            raise RuntimeError("Browser has not been started.")

        return self.page.locator("body").inner_text()

    def close(self) -> None:
        if self.browser is not None:
            self.browser.close()

        if self.playwright is not None:
            self.playwright.stop()