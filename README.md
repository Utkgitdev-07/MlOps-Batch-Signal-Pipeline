# MLOps Task 0 — Batch Signal Pipeline

A minimal, reproducible, observable batch job that reads OHLCV data, computes a
rolling mean on `close`, derives a binary trading signal, and writes structured
metrics + logs.

## What it does

1. Loads and validates `config.yaml` (`seed`, `window`, `version`)
2. Loads and validates `data.csv` (must contain a `close` column, must be non-empty/readable)
3. Computes `rolling_mean = close.rolling(window).mean()`
   - The first `window - 1` rows have no full window yet, so `rolling_mean` is `NaN`
     for those rows and they are **excluded** from the signal / signal_rate calculation
     (kept in `rows_processed`, but their `signal` is left as `NaN`).
4. Derives `signal = 1 if close > rolling_mean else 0`
5. Writes `metrics.json` (success or error schema) and `run.log` (structured logs)

## Files

```
run.py            # main script
config.yaml        # seed / window / version
data.csv           # provided OHLCV data (10,000 rows)
requirements.txt   # pandas, numpy, PyYAML
Dockerfile
README.md
metrics.json        # sample output from a successful run
run.log             # sample log from a successful run
```

## Local run

```bash
pip install -r requirements.txt

python run.py \
  --input data.csv \
  --config config.yaml \
  --output metrics.json \
  --log-file run.log
```

Exit code is `0` on success, non-zero on any validation/processing error.
`metrics.json` is always written, in both cases.

## Docker

Build:
```bash
docker build -t mlops-task .
```

Run:
```bash
docker run --rm mlops-task
```

The image bundles `data.csv` and `config.yaml` and runs the exact CLI command
internally (see `CMD` in the `Dockerfile`) — no paths are hardcoded inside
`run.py` itself; they're all passed as `--input` / `--config` / `--output` /
`--log-file` arguments. The container prints the final `metrics.json` to
stdout and exits `0` on success.

To pull the output files back out of the container instead of just reading
stdout:
```bash
docker run --rm -v "$(pwd)/out:/app" mlops-task
```
(this mounts a local `out/` folder over `/app` so `metrics.json` and
`run.log` land on your host)

## Example metrics.json (success)

```json
{
  "version": "v1",
  "rows_processed": 10000,
  "metric": "signal_rate",
  "value": 0.4991,
  "latency_ms": 41,
  "seed": 42,
  "status": "success"
}
```

## Example metrics.json (error)

```json
{
  "version": "v1",
  "status": "error",
  "error_message": "Required column 'close' not found in input data"
}
```

## Reproducibility

- `numpy.random.seed(seed)` is set from config at job start.
- The rolling-mean / signal logic is purely deterministic given the same
  input file and `window`, so `rows_processed`, `signal_rate`, and `seed`
  are identical across runs. Only `latency_ms` varies run-to-run (wall-clock
  timing), which is expected and does not affect correctness.

## Error handling covered

- Missing config file / invalid YAML / missing required config fields
- Missing input file / empty input file / invalid CSV / missing `close` column
- All errors are logged (with traceback) and produce a valid `metrics.json`
  with `status: "error"` and a descriptive `error_message`, plus a non-zero
  exit code.
