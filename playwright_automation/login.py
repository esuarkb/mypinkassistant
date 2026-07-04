# playwright_automation/login.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from playwright_automation.step_log import step


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
    step("login", 1, 8, "goto_login", f"navigating to {MYCUSTOMERS_URL}")
    page.goto(MYCUSTOMERS_URL, wait_until="domcontentloaded")

    # Fill login fields
    step("login", 2, 8, "wait_consultant_number", "waiting for 'Consultant Number' textbox")
    page.get_by_role("textbox", name="Consultant Number").wait_for(state="visible", timeout=30000)
    step("login", 3, 8, "fill_credentials", "filling consultant number + password")
    page.get_by_role("textbox", name="Consultant Number").fill(username)
    page.wait_for_timeout(100)
    page.get_by_role("textbox", name="Password").fill(password)
    page.wait_for_timeout(100)

    # Submit
    step("login", 4, 8, "click_log_in", "clicking 'Log In'")
    page.get_by_text("Log In").click()

    # Allow redirects / MFA / slow loads
    #page.wait_for_timeout(7000)
    
    # Give the page a moment for login error banner to render
    page.wait_for_timeout(1500)

    # If invalid login message appears, fail immediately
    step("login", 5, 8, "check_invalid_login", "checking for 'Invalid login attempt.' banner")
    err = page.get_by_text("Invalid login attempt.", exact=True)
    if err.count() > 0 and err.first.is_visible():
        raise RuntimeError(
            "InTouch login failed: invalid username or password. "
            "Please update your credentials in Settings and try again."
        )

    # If post-login redirect landed on Salesforce "Finish Logging In" page, click through.
    step("login", 6, 8, "finish_logging_in", "checking for Salesforce 'Finish Logging In' interstitial (optional)")
    try:
        finish_btn = page.get_by_role("button", name="Finish Logging In")
        finish_btn.wait_for(state="visible", timeout=5000)
        finish_btn.click()
        page.wait_for_timeout(2000)
    except PlaywrightTimeoutError:
        pass

    # If still not on the customer list, navigate back directly — session cookie is set.
    step("login", 7, 8, "nav_back_mycustomers", "returning to customer list if redirected away")
    if MYCUSTOMERS_URL not in page.url:
        page.goto(MYCUSTOMERS_URL, wait_until="domcontentloaded")

    step("login", 8, 8, "wait_mycustomers_ready", "waiting for 'New Customer' button (MyCustomers ready)")
    _wait_for_mycustomers_ready(page, timeout_ms=45000)
    
    # Basic sanity check: we should no longer be on the login page
    #if "login" in page.url.lower():
    #    raise RuntimeError(
    #        "Intouch login failed. Please try again or double-check your username and password."
    #    )
