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

import datetime
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


def _is_active_hour(start: int, end: int) -> bool:
    """Return True if the current hour falls within [start, end)."""
    hour = datetime.datetime.now().hour
    if start <= end:
        return start <= hour < end
    # Wraps midnight, e.g. start=22, end=6 → active 22-23 and 0-5
    return hour >= start or hour < end


def _seconds_until_active(start_hour: int) -> float:
    """Return seconds from now until *start_hour*:00 today or tomorrow."""
    now = datetime.datetime.now()
    target = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


# ---------------------------------------------------------------------------
# Form filler
# ---------------------------------------------------------------------------

class FormFiller:
    """
    Fills one Google Form submission using a pre-generated answer profile.

    Each _fill_* method corresponds to one form question.  Radio buttons are
    located via their ``data-value`` attribute.  Linear-scale radios are
    scoped to their question container via the sentinel hidden input.
    """

    def __init__(self, driver, cfg: dict):
        self.driver = driver
        self.cfg = cfg
        self.q = cfg["questions"]

    def _resolve_option_text(self, question_key: str, answer_key: str) -> str:
        """Return the form option text for a given question + answer key."""
        return self.q[question_key]["option_map"][answer_key]

    def _click_radio_by_text(self, option_text: str) -> None:
        """Click a radio whose data-value matches option_text."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        escaped = self._xpath_escape(option_text)
        xpath = f"//div[@data-value={escaped} and @role='radio']"
        wait = WebDriverWait(self.driver, 10)
        element = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        element.click()

    @staticmethod
    def _xpath_escape(text: str) -> str:
        """Return an XPath-safe string literal, handling quotes."""
        if "'" not in text:
            return f"'{text}'"
        if '"' not in text:
            return f'"{text}"'
        # Contains both — use concat(), e.g. "it's \"ok\"" → concat('it',"'",'s "ok"')
        parts = text.split("'")
        return "concat(" + ",\"'\",".join(f"'{p}'" for p in parts) + ")"

    def _click_scale_radio(self, entry_id: str, value: str) -> None:
        """Click a numeric radio in a linear-scale question, scoped by entry ID."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        xpath = (
            f"//input[@name='entry.{entry_id}_sentinel']"
            f"/ancestor::div[contains(@class,'Qr7Oae')]"
            f"//div[@data-value='{value}' and @role='radio']"
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
        self._fill_question("age", profile["age"])

    def fill_education(self, profile: dict) -> None:
        self._fill_question("education", profile["education"])

    def fill_employment(self, profile: dict) -> None:
        self._fill_question("employment", profile["employment"])

    def fill_income(self, profile: dict) -> None:
        self._fill_question("income", profile["income"])

    def fill_fin_literacy_q1(self, profile: dict) -> None:
        self._fill_question("fin_literacy_q1", profile["fin_literacy_q1"])

    def fill_fin_literacy_q2(self, profile: dict) -> None:
        self._fill_question("fin_literacy_q2", profile["fin_literacy_q2"])

    def fill_fin_literacy_q3(self, profile: dict) -> None:
        self._fill_question("fin_literacy_q3", profile["fin_literacy_q3"])

    def fill_invests_now(self, profile: dict) -> None:
        self._fill_question("invests_now", profile["invests_now"])

    def fill_first_invest(self, profile: dict) -> None:
        self._fill_question("first_invest", profile["first_invest"])

    def fill_risk(self, profile: dict) -> None:
        self._fill_question("risk", profile["risk"])

    def fill_risk_agreement(self, profile: dict) -> None:
        self._fill_question("risk_agreement", profile["risk_agreement"])

    def fill_drop_reaction(self, profile: dict) -> None:
        self._fill_question("drop_reaction", profile["drop_reaction"])

    def _fill_scale_question(self, question_key: str, value: str) -> None:
        """Generic helper for linear-scale questions."""
        entry_id = self.q[question_key]["entry_id"]
        logging.debug("  [%s] clicking scale value '%s'", question_key, value)
        self._click_scale_radio(entry_id, value)
        human_pause(self.cfg)

    def fill_social_trust_q1(self, profile: dict) -> None:
        self._fill_scale_question("social_trust_q1", profile["social_trust_q1"])

    def fill_social_trust_q2(self, profile: dict) -> None:
        self._fill_scale_question("social_trust_q2", profile["social_trust_q2"])

    def fill_social_trust_q3(self, profile: dict) -> None:
        self._fill_scale_question("social_trust_q3", profile["social_trust_q3"])

    def fill_fin_trust_q1(self, profile: dict) -> None:
        self._fill_scale_question("fin_trust_q1", profile["fin_trust_q1"])

    def fill_fin_trust_q2(self, profile: dict) -> None:
        self._fill_scale_question("fin_trust_q2", profile["fin_trust_q2"])

    def fill_fin_trust_q3(self, profile: dict) -> None:
        self._fill_scale_question("fin_trust_q3", profile["fin_trust_q3"])

    def fill_happiness(self, profile: dict) -> None:
        self._fill_scale_question("happiness", profile["happiness"])

    def fill_life_satisfaction(self, profile: dict) -> None:
        self._fill_scale_question("life_satisfaction", profile["life_satisfaction"])

    def submit(self) -> None:
        """Click the form's submit button."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        xpath = "//span[normalize-space(text())='Pateikti']"
        wait = WebDriverWait(self.driver, 10)
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        btn.click()
        logging.debug("Form submitted.")

    # --- Main entry point ---

    def fill_and_submit(self, profile: dict) -> None:
        """Execute the full filling sequence for one form submission."""
        logging.info(
            "Filling form — profile: %s | invests: %s | risk: %s",
            profile["_profile_label"],
            profile["invests_now"],
            profile["risk"],
        )

        # Gender is a hidden pre-set field — do NOT interact with it.
        # Questions are filled in form order.
        self.fill_age(profile)
        self.fill_education(profile)
        self.fill_employment(profile)
        self.fill_income(profile)
        self.fill_fin_literacy_q1(profile)
        self.fill_fin_literacy_q2(profile)
        self.fill_fin_literacy_q3(profile)
        self.fill_invests_now(profile)
        self.fill_first_invest(profile)
        self.fill_risk(profile)
        self.fill_risk_agreement(profile)
        self.fill_drop_reaction(profile)
        self.fill_social_trust_q1(profile)
        self.fill_social_trust_q2(profile)
        self.fill_social_trust_q3(profile)
        self.fill_fin_trust_q1(profile)
        self.fill_fin_trust_q2(profile)
        self.fill_fin_trust_q3(profile)
        self.fill_happiness(profile)
        self.fill_life_satisfaction(profile)
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

    # Schedule & burst settings
    schedule = cfg.get("schedule", {})
    active_start = schedule.get("active_hours_start", 0)
    active_end = schedule.get("active_hours_end", 24)
    burst_chance = schedule.get("burst_chance", 0.0)
    burst_multiplier = schedule.get("burst_multiplier", 3)
    log.info(
        "Schedule: active hours %02d:00–%02d:00 | burst chance %.0f%% (×%d)",
        active_start, active_end, burst_chance * 100, burst_multiplier,
    )

    last_burst_hour: int | None = None
    is_burst = False
    submission_count = 0

    while True:
        if max_submissions is not None and submission_count >= max_submissions:
            log.info("Reached max_submissions=%d. Stopping.", max_submissions)
            break

        # --- Active-hours gate ---
        if not _is_active_hour(active_start, active_end):
            wait = _seconds_until_active(active_start)
            log.info(
                "Outside active hours (%02d:00–%02d:00). Sleeping %.0f s until next window.",
                active_start, active_end, wait,
            )
            time.sleep(wait)
            continue

        # --- Burst check (re-evaluated each new clock hour) ---
        current_hour = datetime.datetime.now().hour
        if current_hour != last_burst_hour:
            is_burst = random.random() < burst_chance
            last_burst_hour = current_hour
            if is_burst:
                log.info(
                    "Burst hour activated! Submitting ~%dx faster this hour.",
                    burst_multiplier,
                )

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
        if is_burst:
            delay /= burst_multiplier
        log.info(
            "Waiting %.1f s before next submission...%s",
            delay, " (burst)" if is_burst else "",
        )
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
        f"  Profile       : {profile['_profile_label']}\n"
        f"  Age           : {profile['age']}\n"
        f"  Education     : {profile['education']}\n"
        f"  Employment    : {profile['employment']}\n"
        f"  Income        : {profile['income']}\n"
        f"  Fin.Lit. Q1   : {profile['fin_literacy_q1']}\n"
        f"  Fin.Lit. Q2   : {profile['fin_literacy_q2']}\n"
        f"  Fin.Lit. Q3   : {profile['fin_literacy_q3']}\n"
        f"  Invests       : {profile['invests_now']}\n"
        f"  1st inv.      : {profile['first_invest']}\n"
        f"  Risk          : {profile['risk']}\n"
        f"  Risk agree.   : {profile['risk_agreement']}\n"
        f"  Drop react.   : {profile['drop_reaction']}\n"
        f"  Social trust  : {profile['social_trust_q1']}, {profile['social_trust_q2']}, {profile['social_trust_q3']}\n"
        f"  Fin. trust    : {profile['fin_trust_q1']}, {profile['fin_trust_q2']}, {profile['fin_trust_q3']}\n"
        f"  Happiness     : {profile['happiness']}\n"
        f"  Life satisf.  : {profile['life_satisfaction']}\n"
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
