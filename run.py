#!/usr/bin/env python3
"""
run.py - Minimal MLOps-style batch job.

Loads config + OHLCV data, computes a rolling mean on `close`,
derives a binary signal, and writes structured metrics + logs.

Usage:
    python run.py --input data.csv --config config.yaml --output metrics.json --log-file run.log
"""

import argparse
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
import yaml

REQUIRED_CONFIG_FIELDS = ("seed", "window", "version")


def build_logger(log_file: str) -> logging.Logger:
    """Configure a logger that writes to both a log file and stdout."""
    logger = logging.getLogger("mlops_task")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
    )

    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger


def write_metrics(output_path: str, payload: dict) -> None:
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)


def load_config(config_path: str, logger: logging.Logger) -> dict:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file: {e}")

    if not isinstance(config, dict):
        raise ValueError("Invalid config structure: expected a YAML mapping/object")

    missing = [field for field in REQUIRED_CONFIG_FIELDS if field not in config]
    if missing:
        raise ValueError(f"Config missing required field(s): {missing}")

    if not isinstance(config["seed"], int):
        raise ValueError("Config field 'seed' must be an integer")
    if not isinstance(config["window"], int) or config["window"] < 1:
        raise ValueError("Config field 'window' must be a positive integer")
    if not isinstance(config["version"], str):
        raise ValueError("Config field 'version' must be a string")

    logger.info(
        f"Config loaded + validated: seed={config['seed']}, "
        f"window={config['window']}, version={config['version']}"
    )
    return config


def _read_csv_robust(input_path: str) -> pd.DataFrame:
    """
    Read the CSV normally. Some exports (e.g. from Google Sheets) quote each
    entire row as a single field, collapsing everything into one column.
    Detect and repair that case so downstream logic sees real columns.
    """
    df = pd.read_csv(input_path)

    if df.shape[1] == 1 and "," in df.columns[0]:
        # The whole row was wrapped in quotes as one field; split it back out.
        col_name = df.columns[0]
        header = [c.strip() for c in col_name.split(",")]
        rows = [
            [v.strip() for v in str(val).split(",")]
            for val in df[col_name].tolist()
        ]
        df = pd.DataFrame(rows, columns=header)

    return df


def load_dataset(input_path: str, logger: logging.Logger) -> pd.DataFrame:
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if os.path.getsize(input_path) == 0:
        raise ValueError("Input file is empty")

    try:
        df = _read_csv_robust(input_path)
    except pd.errors.EmptyDataError:
        raise ValueError("Input file is empty or has no parseable columns")
    except pd.errors.ParserError as e:
        raise ValueError(f"Invalid CSV format: {e}")

    if df.empty:
        raise ValueError("Input file contains no data rows")

    if "close" not in df.columns:
        raise ValueError("Required column 'close' not found in input data")

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if df["close"].isna().all():
        raise ValueError("Column 'close' contains no valid numeric values")

    logger.info(f"Rows loaded: {len(df)}")
    return df


def compute_signal(df: pd.DataFrame, window: int, logger: logging.Logger) -> pd.DataFrame:
    df = df.copy()
    df["rolling_mean"] = df["close"].rolling(window=window, min_periods=window).mean()
    logger.info(f"Rolling mean computed with window={window} (first {window - 1} rows are NaN, excluded from signal)")

    df["signal"] = np.where(df["close"] > df["rolling_mean"], 1, 0)
    df.loc[df["rolling_mean"].isna(), "signal"] = np.nan
    logger.info("Binary signal generated: 1 if close > rolling_mean else 0")

    return df


def main():
    parser = argparse.ArgumentParser(description="Minimal MLOps batch job")
    parser.add_argument("--input", required=True, help="Path to input CSV file")
    parser.add_argument("--config", required=True, help="Path to config YAML file")
    parser.add_argument("--output", required=True, help="Path to output metrics JSON file")
    parser.add_argument("--log-file", required=True, help="Path to log file")
    args = parser.parse_args()

    logger = build_logger(args.log_file)
    start_time = time.time()
    logger.info("Job start")

    version = "v1"  # fallback in case config fails to load at all
    try:
        config = load_config(args.config, logger)
        version = config["version"]

        np.random.seed(config["seed"])
        logger.info(f"Random seed set to {config['seed']}")

        df = load_dataset(args.input, logger)
        df = compute_signal(df, config["window"], logger)

        valid = df.dropna(subset=["signal"])
        rows_processed = int(len(df))
        signal_rate = float(valid["signal"].mean()) if len(valid) > 0 else 0.0

        latency_ms = int((time.time() - start_time) * 1000)

        metrics = {
            "version": version,
            "rows_processed": rows_processed,
            "metric": "signal_rate",
            "value": round(signal_rate, 4),
            "latency_ms": latency_ms,
            "seed": config["seed"],
            "status": "success",
        }
        logger.info(f"Metrics summary: {metrics}")

        write_metrics(args.output, metrics)
        logger.info("Job end | status=success")
        print(json.dumps(metrics, indent=2))
        sys.exit(0)

    except Exception as e:
        logger.exception(f"Job failed: {e}")
        error_metrics = {
            "version": version,
            "status": "error",
            "error_message": str(e),
        }
        write_metrics(args.output, error_metrics)
        logger.info("Job end | status=error")
        print(json.dumps(error_metrics, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
