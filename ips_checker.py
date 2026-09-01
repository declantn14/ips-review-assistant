"""
ips_checker.py

Rule-based logic for the IPS Drafting/Review Assistant.

This module deliberately contains NO AI calls. Every number here is
computed with plain arithmetic so the checks are deterministic and
auditable -- the AI layer (see ai_narrative.py) is only used afterward,
to turn these structured findings into a readable memo. Keeping the
math and the language generation separate means the tool never lets
an LLM "invent" a portfolio number.

Core objects
------------
IPS parameters (dict), shape:
    {
      "client_name": str,
      "risk_tolerance": str,
      "time_horizon_years": int,
      "liquidity_reserve_pct": float,       # minimum % of portfolio in Cash
      "single_position_limit_pct": float,   # max % any one holding may represent
      "allocation_targets": {
          "<Asset Class>": {"min": float, "max": float},
          ...
      },
      "constraints": [str, ...]             # free-text restrictions, checked
                                             # against each holding's
                                             # restricted_flags column
    }

Portfolio (pandas.DataFrame), required columns:
    name, ticker, asset_class, market_value, restricted_flags
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Finding:
    check: str
    status: str  # "OK" or "FLAG"
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.check, "status": self.status, "detail": self.detail}


def load_ips(path: str) -> dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def load_portfolio(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"name", "ticker", "asset_class", "security_type", "market_value", "restricted_flags"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Portfolio CSV is missing required columns: {sorted(missing)}")
    df["restricted_flags"] = df["restricted_flags"].fillna("")
    df["market_value"] = df["market_value"].astype(float)
    return df


def compute_allocation(df: pd.DataFrame) -> pd.Series:
    """Return actual allocation % by asset class, indexed by asset class."""
    total = df["market_value"].sum()
    by_class = df.groupby("asset_class")["market_value"].sum()
    return (by_class / total * 100).round(2)


def check_allocation_bands(actual_alloc: pd.Series, targets: dict[str, dict]) -> list[Finding]:
    findings = []
    all_classes = set(actual_alloc.index) | set(targets.keys())
    for asset_class in sorted(all_classes):
        actual_pct = float(actual_alloc.get(asset_class, 0.0))
        band = targets.get(asset_class)
        if band is None:
            findings.append(Finding(
                check=f"Allocation band -- {asset_class}",
                status="FLAG",
                detail=(f"Portfolio holds {actual_pct:.1f}% in {asset_class}, which has no "
                        f"target band defined in the IPS. Either the IPS needs to define one, "
                        f"or this exposure may be unauthorized."),
                data={"asset_class": asset_class, "actual_pct": actual_pct},
            ))
            continue
        lo, hi = float(band["min"]), float(band["max"])
        if actual_pct < lo:
            findings.append(Finding(
                check=f"Allocation band -- {asset_class}",
                status="FLAG",
                detail=(f"{asset_class} is {actual_pct:.1f}% of the portfolio, below the IPS "
                        f"target range of {lo:.0f}-{hi:.0f}%."),
                data={"asset_class": asset_class, "actual_pct": actual_pct, "min": lo, "max": hi},
            ))
        elif actual_pct > hi:
            findings.append(Finding(
                check=f"Allocation band -- {asset_class}",
                status="FLAG",
                detail=(f"{asset_class} is {actual_pct:.1f}% of the portfolio, above the IPS "
                        f"target range of {lo:.0f}-{hi:.0f}%."),
                data={"asset_class": asset_class, "actual_pct": actual_pct, "min": lo, "max": hi},
            ))
        else:
            findings.append(Finding(
                check=f"Allocation band -- {asset_class}",
                status="OK",
                detail=f"{asset_class} is {actual_pct:.1f}%, within the IPS target range of {lo:.0f}-{hi:.0f}%.",
                data={"asset_class": asset_class, "actual_pct": actual_pct, "min": lo, "max": hi},
            ))
    return findings


def check_concentration(df: pd.DataFrame, limit_pct: float) -> list[Finding]:
    """
    Single-position limits in a real IPS almost always apply to individual
    securities (a single stock or bond), not to a diversified fund or ETF --
    an index fund can be 20% of a portfolio without being a "concentrated
    bet" the way a single stock at 20% would be. So this check only looks
    at rows tagged security_type == "Single Stock" (case-insensitive match
    on "single" is used so single bonds/other single-name types also count).
    """
    total = df["market_value"].sum()
    findings = []
    single_name = df[df["security_type"].str.strip().str.lower().str.contains("single", na=False)].copy()
    single_name["pct"] = (single_name["market_value"] / total * 100).round(2)
    breaches = single_name[single_name["pct"] > limit_pct].sort_values("pct", ascending=False)
    if breaches.empty:
        findings.append(Finding(
            check="Single-position concentration",
            status="OK",
            detail=(f"No individual security exceeds the IPS single-position limit of "
                    f"{limit_pct:.0f}% (diversified funds/ETFs are excluded from this check)."),
        ))
    else:
        for _, row in breaches.iterrows():
            findings.append(Finding(
                check=f"Single-position concentration -- {row['ticker']}",
                status="FLAG",
                detail=(f"{row['name']} ({row['ticker']}) is {row['pct']:.1f}% of the portfolio, "
                        f"above the IPS single-position limit of {limit_pct:.0f}%."),
                data={"ticker": row["ticker"], "pct": float(row["pct"]), "limit": limit_pct},
            ))
    return findings


def check_liquidity(actual_alloc: pd.Series, liquidity_reserve_pct: float,
                     cash_asset_class: str = "Cash") -> list[Finding]:
    actual_cash_pct = float(actual_alloc.get(cash_asset_class, 0.0))
    if actual_cash_pct < liquidity_reserve_pct:
        return [Finding(
            check="Liquidity reserve",
            status="FLAG",
            detail=(f"Cash/cash-equivalents are {actual_cash_pct:.1f}% of the portfolio, below "
                    f"the IPS liquidity reserve requirement of {liquidity_reserve_pct:.0f}%."),
            data={"actual_pct": actual_cash_pct, "required_pct": liquidity_reserve_pct},
        )]
    return [Finding(
        check="Liquidity reserve",
        status="OK",
        detail=(f"Cash/cash-equivalents are {actual_cash_pct:.1f}% of the portfolio, meeting the "
                f"IPS liquidity reserve requirement of {liquidity_reserve_pct:.0f}%."),
        data={"actual_pct": actual_cash_pct, "required_pct": liquidity_reserve_pct},
    )]


def check_restricted_holdings(df: pd.DataFrame, constraints: list[str]) -> list[Finding]:
    """
    Naive keyword match: flags any holding whose restricted_flags tag
    (e.g. "tobacco") appears as a word inside one of the IPS's free-text
    constraints (e.g. "No direct tobacco holdings").

    This is intentionally simple -- a real version would use a maintained
    restricted-securities list rather than string matching, but it's
    enough to demonstrate the check for a portfolio-project build.
    """
    findings = []
    flagged_rows = df[df["restricted_flags"].str.strip() != ""]
    if flagged_rows.empty:
        findings.append(Finding(
            check="Restricted holdings",
            status="OK",
            detail="No holdings carry a restricted-category flag.",
        ))
        return findings

    constraints_text = " ".join(constraints).lower()
    any_violation = False
    for _, row in flagged_rows.iterrows():
        tags = [t.strip().lower() for t in row["restricted_flags"].split(",") if t.strip()]
        matched_tags = [t for t in tags if t in constraints_text]
        if matched_tags:
            any_violation = True
            findings.append(Finding(
                check=f"Restricted holding -- {row['ticker']}",
                status="FLAG",
                detail=(f"{row['name']} ({row['ticker']}) is tagged '{', '.join(matched_tags)}', "
                        f"which appears to violate an IPS constraint."),
                data={"ticker": row["ticker"], "tags": matched_tags},
            ))
    if not any_violation:
        findings.append(Finding(
            check="Restricted holdings",
            status="OK",
            detail="Flagged holdings exist but none match a constraint stated in the IPS.",
        ))
    return findings


def run_all_checks(ips: dict[str, Any], portfolio: pd.DataFrame) -> dict[str, Any]:
    """Run every check and return a structured result bundle."""
    actual_alloc = compute_allocation(portfolio)

    findings: list[Finding] = []
    findings += check_allocation_bands(actual_alloc, ips["allocation_targets"])
    findings += check_concentration(portfolio, float(ips["single_position_limit_pct"]))
    findings += check_liquidity(actual_alloc, float(ips["liquidity_reserve_pct"]))
    findings += check_restricted_holdings(portfolio, ips.get("constraints", []))

    return {
        "actual_allocation": actual_alloc.to_dict(),
        "total_market_value": float(portfolio["market_value"].sum()),
        "findings": [f.as_dict() for f in findings],
        "flag_count": sum(1 for f in findings if f.status == "FLAG"),
        "ok_count": sum(1 for f in findings if f.status == "OK"),
    }
