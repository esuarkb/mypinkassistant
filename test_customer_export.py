from pathlib import Path
from dotenv import load_dotenv

from playwright.sync_api import sync_playwright

from auth_core import get_consultant_intouch_creds
from playwright_automation.login import login_intouch
from playwright_automation.customer_export import download_customer_export

load_dotenv()


def main():
    consultant_id = 1  # change if needed for your local test account

    username, password = get_consultant_intouch_creds(consultant_id)
    username = (username or "").strip()
    password = (password or "").strip()

    if not username or not password:
        raise RuntimeError("Missing InTouch credentials for test consultant.")

    out_path = Path("/tmp/customer_import_test.xlsx")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,  # local test: keep visible
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/Chicago",
        )

        try:
            page = context.new_page()

            print("Logging in...")
            login_intouch(page, username, password)

            print("Downloading export...")
            saved = download_customer_export(page, str(out_path))

            print(f"Export saved to: {saved}")

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()