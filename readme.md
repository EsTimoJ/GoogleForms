# Google Forms Bot

A configurable Selenium Python bot that fills Google Forms answers at a
human-like pace, following the statistical tendencies of 120 genuine
responses.

---

## File overview

| File | Purpose |
|---|---|
| `config.yaml` | **All** settings — form URL, rate, matrix, option text mapping |
| `matrix.py` | Probability engine — generates coherent answer profiles |
| `bot.py` | Selenium automation loop |
| `requirements.txt` | Python dependencies |

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Edit config.yaml
#    • Set form.url to your Google Form link
#    • Update questions.*.option_map values to match the exact option text
#      on the form (attach the form HTML and we will update the selectors too)

# 3. Run
python bot.py                      # runs indefinitely
python bot.py --max 20             # stop after 20 submissions
python bot.py --config my.yaml     # use a custom config file
```

---

## Key configuration options

| Key | Default | Description |
|---|---|---|
| `form.url` | *(must set)* | Full Google Form URL |
| `rate.answers_per_hour_min` | `4` | Fewest submissions per hour |
| `rate.answers_per_hour_max` | `8` | Most submissions per hour |
| `constraints.neinvestuoju_max_fraction` | `0.05` | Max share of answers that may use "neinvestuoju" |
| `browser.headless` | `true` | Run without a visible browser window |
| `browser.rotate_user_agent` | `true` | Cycle through real browser user-agents |
| `matrix[*].weight` | varies | How often each age/income profile is sampled |
| `matrix[*].invest_prob` | varies | Probability this profile currently invests |

---

## How the answer generator works

```
Pick profile (age + income) --> decide "invests?"
       |                               |
       |                        (if no + quota ok)
       |                         --> "neinvestuoju"
       |                        (else) --> time-range option
       |
       +--> decide risk  (non-investors nudged toward no_risk)
       |
       +--> decide drop reaction  (investors + high risk --> buy_more)
       |
       +--> decide literacy  (mean score +/- jitter --> low/medium/high)
```

---

## Example answer outputs

### Example 1 — Profile: "45–54 / EUR 801–1500" (Older Conservative)

```
Profile  : 45-54 / EUR 801-1500
Age      : 45-54
Income   : 801-1500
Invests  : no
1st inv. : neinvestuoju          <- rare; quota allows it here (first submission)
Risk     : no_risk               <- strongly no-risk profile
Drop     : hold                  <- hold is dominant for this group
Literacy : low                   <- literacy_mean=1.73 -> score lands in "low"
```

**Form text that would be clicked:**
- Age: "45–54"
- Income: "801–1500 €"
- Currently invests: "Ne"
- First invested: "Neinvestuoju"
- Risk tolerance: "Jokia rizika nepriimtina"
- 20% drop reaction: "Nieko nedaryčiau, laukčiau"
- Financial literacy: "Žemas"

---

### Example 2 — Profile: "35–44 / EUR 1501–2500" (Mature Confident Investor)

```
Profile  : 35-44 / EUR 1501-2500
Age      : 35-44
Income   : 1501-2500
Invests  : yes
1st inv. : over_five_years       <- this profile skews toward longer tenure
Risk     : above_average         <- above-average risk is typical here
Drop     : hold                  <- primary tendency; buy_more is secondary
Literacy : high                  <- literacy_mean=2.80 -> score lands in "high"
```

**Form text that would be clicked:**
- Age: "35–44"
- Income: "1501–2500 €"
- Currently invests: "Taip"
- First invested: "Prieš daugiau nei 5 metus"
- Risk tolerance: "Aukštesnė nei vidutinė rizika"
- 20% drop reaction: "Nieko nedaryčiau, laukčiau"
- Financial literacy: "Aukštas"

---

## Next step

Attach the Google Form HTML.  We will then:
1. Map each question's div/span selectors to the `_fill_*` methods in `bot.py`.
2. Verify the exact option label text and update `config.yaml` option_map entries.
3. Handle any multi-page / "Next" button navigation if the form spans pages.
