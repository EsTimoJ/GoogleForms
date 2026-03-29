"""
bot.py — Selenium Google Forms bot.

How it works
------------
1. Load config.yaml.
2. Generate a coherent answer profile via AnswerGenerator.
3. Open the Google Form in a controlled Chrome session.
4. Fill each question using the generated profile.
5. Submit the form.
6. Wait a randomised delay (derived from answers_per_hour) then repeat.

NOTE: The question selectors / XPaths below are marked with TODO comments.
      Once you attach the Google Form HTML, replace every TODO selector with
      the real one and map it to the corresponding answer key.
"""

import logging
import random
import sys
import time
from pathlib import Path

import yaml

from matrix import AnswerGenerator

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict) -> None:
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = log_cfg.get("log_file")
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Browser factory
# ---------------------------------------------------------------------------

def build_driver(cfg: dict) -> "webdriver.Chrome":
    """Return a configured Chrome WebDriver."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    browser_cfg = cfg["browser"]
    options = Options()

    if browser_cfg.get("headless", True):
        # --headless=new requires Chrome 109+; works with all current releases
        options.add_argument("--headless=new")

    options.add_argument(f"--window-size={browser_cfg['window_width']},{browser_cfg['window_height']}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")

    if browser_cfg.get("disable_automation_flags", True):
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

    if browser_cfg.get("rotate_user_agent", True):
        ua = random.choice(browser_cfg["user_agents"])
        options.add_argument(f"--user-agent={ua}")
        logging.debug("Using user-agent: %s", ua)

    chrome_path = browser_cfg.get("chromedriver_path")
    if chrome_path:
        service = Service(executable_path=chrome_path)
    else:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)

    # Mask webdriver property
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


# ---------------------------------------------------------------------------
# Delay helpers
# ---------------------------------------------------------------------------

def compute_delay_range(cfg: dict) -> tuple[float, float]:
    """Return (min_seconds, max_seconds) between submissions."""
    rate = cfg["rate"]
    min_s = rate.get("min_delay_sec")
    max_s = rate.get("max_delay_sec")
    if min_s is None:
        min_s = 3600.0 / rate["answers_per_hour_max"]
    if max_s is None:
        max_s = 3600.0 / rate["answers_per_hour_min"]
    return float(min_s), float(max_s)


def human_pause(cfg: dict) -> None:
    """Small pause between field interactions."""
    rate = cfg["rate"]
    # Defaults mirror config.yaml rate.field_interaction_delay_* values
    delay = random.uniform(
        rate.get("field_interaction_delay_min", 0.4),
        rate.get("field_interaction_delay_max", 1.8),
    )
    time.sleep(delay)


# ---------------------------------------------------------------------------
# Form filler  (TODO: update selectors after attaching form HTML)
# ---------------------------------------------------------------------------

class FormFiller:
    """
    Fills one Google Form submission using a pre-generated answer profile.

    Each _fill_* method corresponds to one form question.  After you attach
    the Google Form HTML:
      1. Identify the XPath / CSS selector for each question's radio buttons
         or dropdown options.
      2. Replace the TODO placeholder with the real selector.
      3. Map the answer key to the matching option text via config option_map.
    """

    def __init__(self, driver, cfg: dict):
        self.driver = driver
        self.cfg = cfg
        self.q = cfg["questions"]

    def _resolve_option_text(self, question_key: str, answer_key: str) -> str:
        """Return the form option text for a given question + answer key."""
        return self.q[question_key]["option_map"][answer_key]

    def _click_radio_by_text(self, option_text: str) -> None:
        """
        Click a radio-button or checkbox whose visible label matches option_text.

        TODO: Replace the XPath below once you attach the form HTML.
              Google Forms wraps option labels in <span> inside <label>.
              A typical selector is:
              //span[contains(@class,'appsMaterialWizToggleRadiogroupEl')]
                    [normalize-space(text())='<option_text>']
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        # TODO: Update XPath to match the real form structure
        xpath = (
            f"//div[@role='radiogroup']"
            f"//span[normalize-space(text())='{option_text}']"
        )
        wait = WebDriverWait(self.driver, 10)
        element = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        element.click()

    def _fill_question(self, question_key: str, answer_key: str) -> None:
        """Generic helper: resolve option text then click the radio."""
        option_text = self._resolve_option_text(question_key, answer_key)
        logging.debug("  [%s] clicking '%s'", question_key, option_text)
        self._click_radio_by_text(option_text)
        human_pause(self.cfg)

    # --- Individual question fillers ---

    def fill_age(self, profile: dict) -> None:
        """TODO: verify selector for age question."""
        self._fill_question("age", profile["age"])

    def fill_income(self, profile: dict) -> None:
        """TODO: verify selector for income question."""
        self._fill_question("income", profile["income"])

    def fill_invests_now(self, profile: dict) -> None:
        """TODO: verify selector for current-investing question."""
        self._fill_question("invests_now", profile["invests_now"])

    def fill_first_invest(self, profile: dict) -> None:
        """
        TODO: verify selector for 'Kada pirmą kartą investavote?' question.
        'neinvestuoju' option is kept rare via config constraints.
        """
        self._fill_question("first_invest", profile["first_invest"])

    def fill_risk(self, profile: dict) -> None:
        """TODO: verify selector for risk-tolerance question."""
        self._fill_question("risk", profile["risk"])

    def fill_drop_reaction(self, profile: dict) -> None:
        """TODO: verify selector for market-drop reaction question."""
        self._fill_question("drop_reaction", profile["drop_reaction"])

    def fill_literacy(self, profile: dict) -> None:
        """TODO: verify selector for financial-literacy question."""
        self._fill_question("literacy", profile["literacy"])

    def submit(self) -> None:
        """
        Click the form's submit button.

        TODO: Update the selector below after attaching form HTML.
              Google Forms typically uses a <span> with text 'Pateikti' or
              'Submit' inside a button element.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        # TODO: Update XPath for the real submit button
        xpath = "//span[normalize-space(text())='Pateikti']"
        wait = WebDriverWait(self.driver, 10)
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        btn.click()
        logging.debug("Form submitted.")

    # --- Main entry point ---

    def fill_and_submit(self, profile: dict) -> None:
        """Execute the full filling sequence for one form submission."""
        logging.info(
            "Filling form — profile: %s | invests: %s | first_invest: %s | "
            "risk: %s | drop: %s | literacy: %s",
            profile["_profile_label"],
            profile["invests_now"],
            profile["first_invest"],
            profile["risk"],
            profile["drop_reaction"],
            profile["literacy"],
        )

        self.fill_age(profile)
        self.fill_income(profile)
        self.fill_invests_now(profile)
        self.fill_first_invest(profile)
        self.fill_risk(profile)
        self.fill_drop_reaction(profile)
        self.fill_literacy(profile)
        self.submit()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(config_path: str = "config.yaml", max_submissions: int | None = None) -> None:
    """
    Main bot loop.

    Parameters
    ----------
    config_path   : path to config.yaml
    max_submissions : stop after this many submissions (None = run forever)
    """
    cfg = load_config(config_path)
    setup_logging(cfg)

    log = logging.getLogger(__name__)
    log.info("Bot starting. Form URL: %s", cfg["form"]["url"])

    session_stats: dict = {"total": 0, "neinvestuoju": 0}
    generator = AnswerGenerator(cfg, session_stats)
    min_delay, max_delay = compute_delay_range(cfg)
    log.info(
        "Rate: %.0f–%.0f answers/hour  →  delay %.0f–%.0f s between submissions",
        cfg["rate"]["answers_per_hour_min"],
        cfg["rate"]["answers_per_hour_max"],
        min_delay,
        max_delay,
    )

    submission_count = 0

    while True:
        if max_submissions is not None and submission_count >= max_submissions:
            log.info("Reached max_submissions=%d. Stopping.", max_submissions)
            break

        driver = build_driver(cfg)
        try:
            driver.get(cfg["form"]["url"])
            log.debug("Page loaded.")
            time.sleep(random.uniform(1.5, 3.0))  # let the form render

            profile = generator.generate()

            if cfg.get("logging", {}).get("print_answer_summary", True):
                _print_summary(profile, submission_count + 1)

            filler = FormFiller(driver, cfg)
            filler.fill_and_submit(profile)

            submission_count += 1
            stats = generator.stats()
            log.info(
                "Submission #%d complete.  neinvestuoju fraction: %.1f%%",
                submission_count,
                100.0 * stats["neinvestuoju"] / max(stats["total"], 1),
            )

        except Exception as exc:
            log.error("Error during submission #%d: %s", submission_count + 1, exc, exc_info=True)
        finally:
            driver.quit()

        if max_submissions is not None and submission_count >= max_submissions:
            break

        delay = random.uniform(min_delay, max_delay)
        log.info("Waiting %.1f s before next submission...", delay)
        time.sleep(delay)

    log.info(
        "Session finished.  Total submissions: %d | neinvestuoju: %d (%.1f%%)",
        session_stats["total"],
        session_stats["neinvestuoju"],
        100.0 * session_stats["neinvestuoju"] / max(session_stats["total"], 1),
    )


def _print_summary(profile: dict, n: int) -> None:
    print(
        f"\n{'─'*50}\n"
        f"  Submission #{n}\n"
        f"  Profile  : {profile['_profile_label']}\n"
        f"  Age      : {profile['age']}\n"
        f"  Income   : {profile['income']}\n"
        f"  Invests  : {profile['invests_now']}\n"
        f"  1st inv. : {profile['first_invest']}\n"
        f"  Risk     : {profile['risk']}\n"
        f"  Drop     : {profile['drop_reaction']}\n"
        f"  Literacy : {profile['literacy']}\n"
        f"{'─'*50}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Google Forms bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--max", type=int, default=None, help="Maximum number of submissions"
    )
    args = parser.parse_args()

    run(config_path=args.config, max_submissions=args.max)
