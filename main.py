"""polymarket-nvidia-ceo-forecast-01 entry: adaptive persistence forecast.

For each market, the median stays at the last price (a prediction market's
price is a martingale: no predictable drift), and the spread widens like a
random walk, but with a per-market sigma estimated from the market's own
recent realized volatility instead of the house baseline's fixed 0.0025:

    q_tau(h) = clamp(x + z_tau * sigma * sqrt(h), 0, 1), rounded to 6 decimals

with sigma = clamp(realized vol of 1-minute returns over the last 120
minutes, 0.0003, 0.004).

Why this beats the fixed baseline (practice loss 0.2787 vs 0.3636):
- Most of these markets sit flat for minutes at a time, so the recent
  2-hour realized vol is far below 0.0025 for most markets, and a narrower
  interval pays less at every quiet minute.
- The floor (0.0003) keeps intervals honest on dead-quiet markets, so a
  sudden jump does not blow up the pinball loss; the cap (0.004) keeps a
  market that just jumped from staying wide forever.
- Longer windows (12h+) are worse: they drag old jumps into sigma and
  widen every interval for hours after the jump is gone.

Alternatives tested on the same six practice cases and rejected:
- Mean reversion / drift toward the recent mean: no gain (loss 0.2895+).
- Empirical quantiles of h-step changes: worse (0.355+); their median
  drifts off the last price and the median error grows.
- Logit-space random walk: worse (0.315+).
- EWMA volatility (half-life 15 min): 0.2784, a tie within noise, but less
  stable across cases; the plain 120-minute boxcar is kept.
- Wider tail quantiles (jump protection): worse; the floor already covers it.

Validated locally (own scorer, reproduces the baseline's published
0.363589 / median error 0.767503 / coverage 0.949642 exactly):
practice loss 0.278732, median error 0.767503, coverage 0.8914, beats the
baseline on all six practice cases; two runs byte-identical; max 0.17 s
per case (limit 8 s).

Standard library only, no network, deterministic: the output is a pure
function of the input file, so two runs are byte-identical.
"""

import json
import math
import os

# The quantile levels the contest scores, in the order each row lists them.
QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level, to 6 decimals.
Z = [-1.644854, -0.67449, 0.0, 0.67449, 1.644854]

# Minutes of recent 1-minute returns used for the realized volatility.
VOL_WINDOW = 120
# Floor and cap on sigma (price units per square-root minute).
SIGMA_FLOOR = 0.0003
SIGMA_CAP = 0.004


def realized_vol(prices, window):
    """Per-minute realized volatility over the last `window` 1-minute returns."""
    n = len(prices)
    if n < 2:
        return 0.0
    start = max(0, n - 1 - window)
    total = 0.0
    count = 0
    for i in range(start, n - 1):
        d = prices[i + 1] - prices[i]
        total += d * d
        count += 1
    if count == 0:
        return 0.0
    return math.sqrt(total / count)


def price6(x):
    """x clamped to [0, 1] and rounded to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


def forecast_market(prices, horizon):
    """240 rows of five quantiles for one market, median at the last price."""
    if not prices:
        raise ValueError("market has no prices")
    x = prices[-1]
    sigma = realized_vol(prices, VOL_WINDOW)
    sigma = min(SIGMA_CAP, max(SIGMA_FLOOR, sigma))
    rows = []
    for h in range(1, horizon + 1):
        spread = sigma * math.sqrt(h)
        row = [price6(x + z * spread) for z in Z]
        for j in range(1, 5):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return rows


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(output_dir, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for name in sorted(os.listdir(input_dir)):
        if not name.endswith(".in"):
            continue
        case_id = name[: -len(".in")]
        with open(os.path.join(input_dir, name), encoding="utf-8") as f:
            case = json.load(f)
        if case["quantiles"] != QUANTILES:
            raise ValueError(
                f"{name} asks for quantiles {case['quantiles']}, not {QUANTILES}"
            )
        forecasts = [
            {"id": m["id"], "q": forecast_market(m["prices"], case["horizon_minutes"])}
            for m in case["markets"]
        ]
        with open(os.path.join(output_dir, case_id + ".out"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"forecasts": forecasts}) + "\n")


if __name__ == "__main__":
    main()
