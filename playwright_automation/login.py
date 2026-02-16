# playwright_automation/login.py

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

# go straight to customer list page, which will redirect to login if not authenticated
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
    """
    Idmpotent:
      - If already logged in, returns immediately.
      - Otherwise logs in and waits until MyCustomers is ready.
    """
    username = (username or "").strip()
    password = (password or "").strip()
    if not username or not password:
        raise RuntimeError("Missing Intouch credentials. Please set them in Settings.")

    # Reasonable defaults (set once)
    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(45000)

    # 1) Go straight to MyCustomers (fastest path; triggers login redirect if needed)
    page.goto(MYCUSTOMERS_URL, wait_until="domcontentloaded")

    # 3) Not logged in yet — wait for login UI
    # Your previous script used these role/name selectors; keep them.
    try:
        page.get_by_role("textbox", name="Consultant Number").wait_for(timeout=30000)
        page.get_by_role("textbox", name="Password").wait_for(timeout=30000)
    except PlaywrightTimeoutError:
        # Sometimes the redirect chain finishes late; check again
        if _is_mycustomers_ready(page):
            return
        raise RuntimeError("Login page did not show expected fields (Consultant Number / Password). Please try again.")

    # 4) Fill + submit
    page.get_by_role("textbox", name="Consultant Number").fill(username)
    page.get_by_role("textbox", name="Password").fill(password)

    # Prefer role=button; fall back to text if needed
    btn = page.get_by_role("button", name="Log In")
    try:
        btn.click()
    except Exception:
        page.get_by_text("Log In", exact=True).click()

    # 5) Wait until we are *actually* back on MyCustomers and ready
    try:
        _wait_for_mycustomers_ready(page, timeout_ms=4500)
    except PlaywrightTimeoutError:
        # Helpful debug info without being too noisy
        raise RuntimeError(
            f"InTouch login failed: please check your username and password and try again."
        )