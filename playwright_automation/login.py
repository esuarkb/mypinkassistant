# playwright_automation/login.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


LOGIN_URL = "https://mk.marykayintouch.com/s/login/"


def login_intouch(page: Page, username: str, password: str) -> None:
    if not username or not password:
        raise RuntimeError(
            "Missing Intouch credentials. Please set them in Settings."
        )

    # Go to login page
    page.goto(LOGIN_URL)
    page.wait_for_timeout(8000)

    # Fill login fields
    page.get_by_role("textbox", name="Consultant Number").fill(username)
    page.wait_for_timeout(500)

    page.get_by_role("textbox", name="Password").fill(password)
    page.wait_for_timeout(500)

    # Submit
    page.get_by_text("Log In").click()

    # Allow redirects / MFA / slow loads
    page.wait_for_timeout(7000)

    # Basic sanity check: we should no longer be on the login page
    if "login" in page.url.lower():
        raise RuntimeError(
            "Intouch login failed. Please try again or double-check your username and password."
        )
