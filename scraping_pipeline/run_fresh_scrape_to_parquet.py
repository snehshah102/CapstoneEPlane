#!/usr/bin/env python3
"""Run a fresh Pipistrel scrape and then build parquet datasets.

This script assumes the raw event folders are starting fresh. It runs:
1. scraping_pipeline/pipistrel_scraper.py
2. scraping_pipeline/build_event_timeseries_parquet.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fresh scrape -> parquet pipeline runner.")
    parser.add_argument("--output-dir", default="data", help="Base data directory for scrape outputs.")
    parser.add_argument("--manifest-path", default="data/processed/scrape_manifest.csv", help="Manifest CSV written by the scraper.")
    parser.add_argument("--raw-root", default="data/raw_csv/by_plane", help="Raw event CSV root for parquet builder.")
    parser.add_argument("--manifest-out", default="data/processed/event_manifest.parquet", help="Parquet output for event manifest.")
    parser.add_argument("--timeseries-out", default="data/processed/event_timeseries.parquet", help="Parquet output for full event timeseries.")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages per aircraft for scrape. 0 means all pages.")
    parser.add_argument("--start-page", type=int, default=1, help="First page number to scrape.")
    parser.add_argument("--max-flights", type=int, default=0, help="Maximum events to scrape. 0 means all events.")
    parser.add_argument("--include-warns", action="store_true", help="Keep *_warns.csv in both scrape extraction and parquet build.")
    parser.add_argument("--include-soh-columns", action="store_true", help="Keep SOH columns in the parquet build.")
    parser.add_argument("--force-redownload", action="store_true", help="Force re-download during scrape.")
    parser.add_argument("--overwrite-extracted", action="store_true", help="Overwrite extracted CSV files during scrape.")
    parser.add_argument("--request-timeout", type=int, default=30, help="HTTP timeout for scraper requests.")
    parser.add_argument("--page-fetch-retries", type=int, default=3, help="Retries for aircraft list page fetches.")
    parser.add_argument("--page-fetch-backoff", type=float, default=1.0, help="Backoff seconds * retry attempt.")
    parser.add_argument("--sleep-seconds", type=float, default=0.15, help="Delay between detail requests.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging verbosity.")
    parser.add_argument("--registrations", nargs="+", default=["C-GAUW", "C-GMUW"], help="Registrations to scrape.")
    parser.add_argument("--aircraft-ids", nargs="+", type=int, default=[166, 192], help="Aircraft IDs to scrape.")
    return parser.parse_args()


def run_command(cmd: list[str]) -> None:
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    py = sys.executable

    scrape_cmd = [
        py,
        str(SCRIPT_DIR / "pipistrel_scraper.py"),
        "--output-dir", args.output_dir,
        "--manifest-path", args.manifest_path,
        "--request-timeout", str(args.request_timeout),
        "--max-pages", str(args.max_pages),
        "--start-page", str(args.start_page),
        "--max-flights", str(args.max_flights),
        "--page-fetch-retries", str(args.page_fetch_retries),
        "--page-fetch-backoff", str(args.page_fetch_backoff),
        "--sleep-seconds", str(args.sleep_seconds),
        "--log-level", args.log_level,
        "--no-skip-existing",
    ]
    if args.force_redownload:
        scrape_cmd.append("--force-redownload")
    if args.overwrite_extracted:
        scrape_cmd.append("--overwrite-extracted")
    if args.include_warns:
        scrape_cmd.append("--include-warns")
    if args.registrations:
        scrape_cmd.extend(["--registrations", *args.registrations])
    if args.aircraft_ids:
        scrape_cmd.extend(["--aircraft-ids", *[str(x) for x in args.aircraft_ids]])

    parquet_cmd = [
        py,
        str(SCRIPT_DIR / "build_event_timeseries_parquet.py"),
        "--raw-root", args.raw_root,
        "--manifest-out", args.manifest_out,
        "--timeseries-out", args.timeseries_out,
    ]
    if args.include_warns:
        parquet_cmd.append("--include-warns")
    if args.include_soh_columns:
        parquet_cmd.append("--include-soh-columns")
    if args.max_flights > 0:
        parquet_cmd.extend(["--max-events", str(args.max_flights)])

    run_command(scrape_cmd)
    run_command(parquet_cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
