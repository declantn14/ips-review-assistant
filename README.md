# IPS Review Assistant

A small tool that checks a client portfolio against its Investment Policy
Statement (IPS) and uses Claude to turn the results into a plain-English
review memo, the way a wealth/asset management business office would want
to see it in a client file.

**The design idea:** every number in this tool is computed by plain,
deterministic Python (`ips_checker.py`) -- allocation percentages,
concentration checks, liquidity coverage, restricted-holding checks. The
AI (`ai_narrative.py`) is only used *after* the math is done, to explain
what the flags mean for this specific client and prioritize what to fix
first. The model never computes or invents a figure. That separation is
the whole point: it's what would make a tool like this trustworthy enough
to actually put in front of clients or compliance, instead of just being
an AI demo.

## What it checks

- **Allocation bands** -- is each asset class within the IPS's stated
  min/max target range?
- **Single-position concentration** -- does any individual security (not
  diversified funds/ETFs) exceed the IPS's single-position limit?
- **Liquidity reserve** -- is enough of the portfolio in cash/cash
  equivalents to meet the IPS's stated reserve requirement?
- **Restricted holdings** -- does any holding carry a tag (e.g.
  "tobacco") that matches a constraint stated in the IPS?

## Quick start

```bash
pip install -r requirements.txt

# Get a key at https://console.anthropic.com/settings/keys
export ANTHROPIC_API_KEY=sk-ant-...

streamlit run app.py
```

Then open the URL Streamlit prints (usually http://localhost:8501). The
app loads with sample data already in place, so you can click **Run
review** immediately to see it work, or paste your own key into the
sidebar instead of using an environment variable.

The sample data (`sample_data/`) is a deliberately messy portfolio: it's
overweight US equity, short on cash, has one concentrated single stock,
and holds a tobacco stock against a "no tobacco" constraint, so a first
run has something real to show.

## Using your own data

**IPS parameters** -- upload a JSON file shaped like `sample_data/sample_ips.json`:

```json
{
  "client_name": "...",
  "risk_tolerance": "Moderate",
  "time_horizon_years": 15,
  "liquidity_reserve_pct": 5,
  "single_position_limit_pct": 10,
  "allocation_targets": {
    "US Equity": {"min": 30, "max": 50}
  },
  "constraints": ["No direct tobacco holdings"]
}
```

**Portfolio holdings** -- upload a CSV shaped like `sample_data/sample_portfolio.csv`,
with columns: `name, ticker, asset_class, security_type, market_value, restricted_flags`.
`security_type` should be `"Single Stock"` for individual securities (these
are the only rows checked against the concentration limit) or `"Fund"` /
`"Cash Equivalent"` otherwise. `restricted_flags` is a comma-separated list
of tags (e.g. `tobacco`) or blank.

You can also edit either data set directly in the app's tables instead of
uploading a file.

## Deploying it (for a resume link / demo)

The easiest option is [Streamlit Community Cloud](https://share.streamlit.io):
push this folder to a GitHub repo, connect it there, and add your
`ANTHROPIC_API_KEY` under the app's Secrets settings instead of an
environment variable. That gives you a live link you can put on a resume
or LinkedIn rather than only a local demo.

## Notes and honest limitations

- The restricted-holdings check is a simple keyword match between a
  holding's tag and the IPS's constraint text -- a real compliance system
  would check against a maintained restricted-securities list instead.
- This is a review/flagging tool, not a trading or compliance system of
  record, and nothing here is investment advice.
- Natural extensions if you want to keep building: exporting the memo as
  a PDF for a client file, tracking allocation drift over time instead of
  a single point-in-time snapshot, and supporting multiple accounts/households
  at once.
