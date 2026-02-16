# playwright_automation/login.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


MYCUSTOMERS_URL = "https://apps.marykayintouch.com/customer-list"

def _wait_for_mycustomers_ready(page: Page, timeout_ms: int = 30000) -> None:
    """
    When logged in + MyCustomer is usable, this button exists.
    """
    page.get_by_role("button", name="New Customer").wait_for(timeout=timeout_ms)

def _is_mycustomers_ready(page: Page) -> bool:
    try:
        _wait_for_mycustomers_ready(page, timeout_ms=1500)
        return True
    except PlaywrightTimeoutError:
        return False
    
def login_intouch(page: Page, username: str, password: str) -> None:
    
    username = (username or "").strip()
    password = (password or "").strip()
    
    if not username or not password:
        raise RuntimeError(
            "Missing Intouch credentials. Please set them in Settings."
        )

    # Go to login page
    page.goto(MYCUSTOMERS_URL, wait_until="domcontentloaded")

    # Fill login fields
    page.get_by_role("textbox", name="Consultant Number").wait_for(state="visible", timeout=30000)
    page.get_by_role("textbox", name="Consultant Number").fill(username)
    #page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Password").fill(password)
    #page.wait_for_timeout(100)

    # Submit
    page.get_by_text("Log In").click()

    # Allow redirects / MFA / slow loads
    #page.wait_for_timeout(7000)
    
    _wait_for_mycustomers_ready(page, timeout_ms=45000)
    
    # Basic sanity check: we should no longer be on the login page
    if "login" in page.url.lower():
        raise RuntimeError(
            "Intouch login failed. Please try again or double-check your username and password."
        )
