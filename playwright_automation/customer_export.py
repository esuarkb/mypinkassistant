from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from playwright_automation.step_log import step

CUSTOMER_LIST_URL = "https://apps.marykayintouch.com/customer-list"


def ensure_customer_list_ready(page: Page, timeout_ms: int = 30000) -> None:
    """
    Wait until the MyCustomers customer list page is ready enough to export.
    """
    try:
        page.goto(CUSTOMER_LIST_URL)
        page.get_by_role("button", name="Export").wait_for(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise RuntimeError("MyCustomers customer list was not ready: Export button not found.")


def download_customer_export(page: Page, save_path: str) -> str | None:
    """
    Opens MyCustomers customer list, exports the customer file,
    and saves it to `save_path`.

    Returns the saved file path, or None if there are no customers to export.
    """
    step("customer_export", 1, 6, "wait_export_ready", "navigating to customer list, waiting for 'Export' button")
    ensure_customer_list_ready(page)

    # Select all customers — checkbox only appears if there are rows
    step("customer_export", 2, 6, "select_all_checkbox", "clicking select-all (absent = empty customer list, not an error)")
    try:
        page.locator(".slds-checkbox_faux").first.click(timeout=10000)
    except PlaywrightTimeoutError:
        # No checkbox means the customer list is empty — nothing to import
        return None
    page.wait_for_timeout(500)

    # Start export flow
    step("customer_export", 3, 6, "click_export_button", "clicking 'Export'")
    page.get_by_role("button", name="Export").click()
    page.wait_for_timeout(500)

    # Click export option inside dialog
    step("customer_export", 4, 6, "click_export_customers_option", "clicking 'Export customers' option in dialog (text-blob selector — most fragile in codebase)")
    page.get_by_role("dialog").locator("div").filter(
        has_text="closeCloseExport customersAre"
    ).click()
    page.wait_for_timeout(500)

    # Confirm and capture download
    step("customer_export", 5, 6, "confirm_and_capture_download", "clicking 'Confirm', waiting for file download")
    with page.expect_download(timeout=30000) as download_info:
        page.get_by_role("button", name="Confirm").click()

    download = download_info.value

    step("customer_export", 6, 6, "save_download", f"saving export to {save_path}")
    out = Path(save_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(out))

    return str(out)