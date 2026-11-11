# YeNo × Builderr Volume Bot — entry by zkgvn

Paper bot for the YeNo volume challenge ($500 first prize, closes 30 Nov
2026). Starts with $10 simulated cash, must complete $1,000 of BUY+SELL
volume in 24 hours and finish flat. No deposit, no account, no real trades.

## Files

| file | what it is |
|---|---|
| `bot.py` | The entry: stdlib-only `POST /decide` server (default port 8080) |
| `strategy.py` | Decision logic (parameterised; `PARAMS` = shipped tuning) |
| `test_bot.py` | 13 unit tests (`python3 test_bot.py`) |
| `simulator.py` | Synthetic paper evaluator (BTC random walk + probit books) |
| `tune.py` | Tuning driver, stages A/B/C (`python3 tune.py A|B|C`) |
| `run_simulation.py` | Held-out validation, seeds 37–60 + stress settings |
| `SPEC.md` | Spec verified live 12 Nov 2026 (contract, fees, scoring, board) |
| `TEST_RESULTS.md` | Honest test results, tuning tables, calibration caveats |
| `SUBMIT.md` | Exact submit steps (NOT executed — awaiting instruction) |
| `kit/` | Official starter kit, byte-identical to the downloads |
| `evidence/` | Raw challenge page HTML + JSON specs fetched 12 Nov 2026 |

## Strategy (one paragraph)

House Bot v1 with three changes only: (1) **$0.15 headroom** on
`maxCashUsd` so a fill against the later execution book (250 ms latency)
isn't rejected by a 1–2 cent move; (2) **minimum BTC gap $80** instead of
$50 — fewer, higher-conviction entries; (3) a **regime filter** — after 8
bleeding cycles, entries require a $100 gap. Everything else is exactly
House Bot v1 (5 shares, 90 s entry window, 2 cycles/market, forced exit at
60 s, breakeven sell, $0.10/share stop). Wider windows, more cycles,
dynamic sizing, take-profit tweaks and trend-riding all tested worse or
neutral in the simulator and were dropped.

## Run

```bash
python3 bot.py 8080
# second terminal:
python3 kit/yeno-smoke-test.py --url http://127.0.0.1:8080/decide \
    --observation kit/yeno-sample-observation.json
# -> {"contractSmokePassed": true, ...}
```

## Test

```bash
python3 test_bot.py        # 13 unit tests
python3 run_simulation.py  # held-out validation (takes ~2-3 min)
```

## Honest status

- Contract smoke test: PASS. Unit tests: 13/13 PASS.
- Simulator (synthetic data only — Builderr publishes no market data):
  held-out seeds 37–60, median volume **$225** vs house bot $219,
  median cash **$3.73** vs $2.90. **Qualified 0/24 for both bots.**
- Nobody has qualified in any published diagnostic; the official house
  bot's best dev path was $942.59 of $1,000. This entry is a modest,
  robust improvement over the house baseline, not a favorite. Details in
  `TEST_RESULTS.md`.
- **Not submitted.** Submit steps (repo + email to submit@builderr.ai)
  are in `SUBMIT.md`, awaiting instruction.
