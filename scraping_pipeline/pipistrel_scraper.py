#!/usr/bin/env python3
"""Scrape Pipistrel Cloud events into event folders with CSV files and metadata.

Outputs:
- data/raw_zips/by_plane/<aircraft_id>/Event_YYYY-MM-DD_HHMM_<flight_id>/...zip
- data/raw_csv/by_plane/<aircraft_id>/Event_YYYY-MM-DD_HHMM_<flight_id>/*.csv
- data/raw_csv/by_plane/<aircraft_id>/Event_YYYY-MM-DD_HHMM_<flight_id>/event_metadata.json
- data/processed/scrape_manifest.csv

Charging events without CSV files are still kept via event metadata and note text.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_MANIFEST_PATH = DEFAULT_DATA_DIR / "processed" / "scrape_manifest.csv"

BASE_URL = "https://cloud.pipistrel.si"
AIRCRAFT_LIST_PATH = "/electro/aircraft/"
LOGIN_PATH = "/electro/login"
DEFAULT_AIRCRAFT_IDS = [166, 192]
FLIGHT_ID_RE = re.compile(r"details\('\.\./flight/',\s*(\d+)\)")
MANIFEST_FIELDS = [
    "flight_id",
    "aircraft_id",
    "registration",
    "list_date",
    "detail_date",
    "detail_flight_type",
    "detail_duration",
    "detail_note",
    "route",
    "pilot",
    "aircraft_type",
    "detail_aircraft",
    "fleet",
    "departure_airport",
    "destination_airport",
    "battery_type",
    "end_of_flight_hobbs",
    "event_dir_name",
    "raw_csv_dir",
    "metadata_path",
    "note_txt_path",
    "csv_found",
    "csv_file_count",
    "csv_files",
    "csv_zip_url",
    "csv_zip_path",
    "csv_zip_sha256",
    "scraped_at_utc",
    "scrape_error",
]

load_dotenv(SCRIPT_DIR / ".env")


@dataclass
class FlightListRow:
    aircraft_id: int
    flight_id: int
    list_date: str
    route: str
    aircraft_type: str
    registration: str
    fleet: str
    note: str
    pilot: str
    engine_duration: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def sanitize_filename_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9-]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "unknown"


def parse_event_datetime(raw_value: str) -> Optional[datetime]:
    if not raw_value:
        return None
    text = clean_text(raw_value)
    text = text.replace("a.m.", "AM").replace("p.m.", "PM")
    text = text.replace("a.m", "AM").replace("p.m", "PM")
    text = re.sub(r"\b([A-Za-z]{3,9})\.", r"\1", text)
    text = re.sub(r"\bSept\b", "Sep", text, flags=re.IGNORECASE)
    text = text.replace("a.m", "AM").replace("p.m", "PM")
    text = re.sub(r",\s*noon$", ", 12:00 PM", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*midnight$", ", 12:00 AM", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*(\d{1,2})\s*(AM|PM)$", r", \1:00 \2", text, flags=re.IGNORECASE)
    for fmt in ("%b %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def build_event_dir_name(detail_date: str, flight_id: int) -> str:
    dt = parse_event_datetime(detail_date)
    if dt is not None:
        stamp = dt.strftime("%Y-%m-%d_%H%M")
    else:
        stamp = sanitize_filename_component(detail_date)[:48]
    return f"Event_{stamp}_{flight_id}"


def write_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_manifest_rows(path: Path) -> Dict[int, Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows: Dict[int, Dict[str, str]] = {}
        for row in reader:
            try:
                rows[int(row.get("flight_id", ""))] = row
            except ValueError:
                continue
        return rows


def save_manifest_rows(path: Path, rows: Dict[int, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (str(r.get("aircraft_id", "")), str(r.get("detail_date", "")), int(r.get("flight_id", 0))))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in ordered:
            safe_row = {field: row.get(field, "") for field in MANIFEST_FIELDS}
            writer.writerow(safe_row)


def find_existing_event_dir(raw_csv_plane_dir: Path, flight_id: int) -> Optional[Path]:
    if not raw_csv_plane_dir.exists():
        return None
    matches = sorted(raw_csv_plane_dir.glob(f"*_{flight_id}"))
    for match in matches:
        if match.is_dir() and (match / "event_metadata.json").exists():
            return match
    return None


def load_existing_event_manifest_row(raw_csv_plane_dir: Path, flight_id: int) -> Optional[Dict[str, Any]]:
    event_dir = find_existing_event_dir(raw_csv_plane_dir, flight_id)
    if event_dir is None:
        return None
    meta_path = event_dir / "event_metadata.json"
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def classify_csv_kind(file_name: str) -> str:
    lower = file_name.lower()
    if lower.endswith("_warns.csv"):
        return "warns"
    if re.search(r"_\d+\.csv$", lower):
        return "aux"
    return "raw"


def is_valid_zip_bytes(payload: bytes) -> bool:
    if not payload:
        return False
    try:
        return zipfile.is_zipfile(io.BytesIO(payload))
    except OSError:
        return False


class PipistrelClient:
    def __init__(self, username: str, password: str, timeout: int = 30) -> None:
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            }
        )
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def login(self, next_path: str = AIRCRAFT_LIST_PATH) -> None:
        login_url = f"{BASE_URL}{LOGIN_PATH}?next={next_path}"
        resp = self.session.get(login_url, timeout=self.timeout)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
        csrf_token = csrf_input.get("value", "") if csrf_input else ""
        if not csrf_token:
            raise RuntimeError("Could not find CSRF token on login page")

        payload = {
            "csrfmiddlewaretoken": csrf_token,
            "username": self.username,
            "password": self.password,
        }
        post_resp = self.session.post(
            login_url,
            data=payload,
            headers={"Referer": login_url},
            timeout=self.timeout,
            allow_redirects=True,
        )
        post_resp.raise_for_status()

        test_resp = self.session.get(f"{BASE_URL}{AIRCRAFT_LIST_PATH}", timeout=self.timeout)
        test_resp.raise_for_status()
        if "logout" not in test_resp.text.lower():
            raise RuntimeError("Login failed. Check username/password.")

    def get(self, path_or_url: str) -> requests.Response:
        target = path_or_url if path_or_url.startswith("http") else f"{BASE_URL}{path_or_url}"
        resp = self.session.get(target, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def get_soup(self, path_or_url: str) -> BeautifulSoup:
        return BeautifulSoup(self.get(path_or_url).text, "html.parser")


def parse_total_pages(soup: BeautifulSoup) -> int:
    max_page = 1
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "page=" not in href:
            continue
        query = urlparse(href).query
        page_str = parse_qs(query).get("page", [None])[0]
        if page_str and page_str.isdigit():
            max_page = max(max_page, int(page_str))
    return max_page


def get_soup_with_retries(
    client: PipistrelClient,
    path_or_url: str,
    attempts: int,
    backoff_seconds: float,
    context: str,
) -> Optional[BeautifulSoup]:
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return client.get_soup(path_or_url)
        except requests.RequestException as exc:
            if attempt >= max(1, attempts):
                logging.error("%s failed after %s attempt(s): %s", context, attempt, exc)
                return None
            wait_s = max(0.0, backoff_seconds) * attempt
            logging.warning(
                "%s failed (attempt %s/%s): %s. Retrying in %.1fs.",
                context,
                attempt,
                max(1, attempts),
                exc,
                wait_s,
            )
            time.sleep(wait_s)


def parse_aircraft_page_context(soup: BeautifulSoup) -> Dict[str, str]:
    context: Dict[str, str] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 2:
            continue
        key = clean_text(tds[0].get_text(" ", strip=True)).lower()
        value = clean_text(tds[1].get_text(" ", strip=True))
        if key:
            context[key] = value
    return context


def parse_flight_rows_with_defaults(
    soup: BeautifulSoup,
    aircraft_id: int,
    default_registration: str = "",
    default_aircraft_type: str = "",
    default_fleet: str = "",
) -> list[FlightListRow]:
    rows: list[FlightListRow] = []
    for tr in soup.find_all("tr", class_="clickable-aircraft"):
        onclick = tr.get("onclick", "")
        match = FLIGHT_ID_RE.search(onclick)
        if not match:
            continue
        tds = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if len(tds) < 8:
            continue
        if len(tds) >= 9:
            row = FlightListRow(
                aircraft_id=aircraft_id,
                flight_id=int(match.group(1)),
                list_date=tds[1],
                route=tds[2],
                aircraft_type=tds[3],
                registration=tds[4],
                fleet=tds[5],
                note=tds[6],
                pilot=tds[7],
                engine_duration=tds[8],
            )
        else:
            row = FlightListRow(
                aircraft_id=aircraft_id,
                flight_id=int(match.group(1)),
                list_date=tds[1],
                route=tds[3],
                aircraft_type=default_aircraft_type,
                registration=default_registration,
                fleet=default_fleet,
                note=tds[4],
                pilot=tds[5],
                engine_duration=tds[6],
            )
        rows.append(row)
    return rows


def parse_flight_details(soup: BeautifulSoup) -> Dict[str, str]:
    details: Dict[str, str] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 2:
            continue
        key = clean_text(tds[0].get_text(" ", strip=True)).lower()
        value = clean_text(tds[1].get_text(" ", strip=True))
        if key:
            details[key] = value
    return details


def find_processed_csv_zip_url(soup: BeautifulSoup, page_url: str) -> Optional[str]:
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if "/media/processed_data/" in low and low.endswith(".zip") and "/images/" not in low:
            return urljoin(page_url, href)
    return None


def download_csv_zip(client: PipistrelClient, csv_url: str) -> tuple[Optional[bytes], str, Optional[int]]:
    candidates = [csv_url]
    if "/electro/media/" in csv_url:
        candidates.append(csv_url.replace("/electro/media/", "/media/"))

    seen: set[str] = set()
    deduped: list[str] = []
    for item in candidates:
        if item not in seen:
            deduped.append(item)
            seen.add(item)

    last_status: Optional[int] = None
    last_url = csv_url
    for candidate in deduped:
        last_url = candidate
        try:
            resp = client.get(candidate)
            payload = resp.content
            if is_valid_zip_bytes(payload):
                return payload, candidate, None
            last_status = resp.status_code
            logging.warning(
                "Downloaded non-ZIP payload from %s (status=%s, content-type=%s, bytes=%s).",
                candidate,
                resp.status_code,
                resp.headers.get("Content-Type"),
                len(payload),
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 404:
                last_status = 404
                continue
            raise
    return None, last_url, last_status


def extract_csvs_from_zip_bytes(
    zip_bytes: bytes,
    out_dir: Path,
    include_warns: bool,
    overwrite: bool,
) -> list[Dict[str, str]]:
    extracted: list[Dict[str, str]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            out_name = Path(member.filename).name
            if not out_name:
                continue
            if not out_name.lower().endswith(".csv"):
                continue
            kind = classify_csv_kind(out_name)
            if kind == "warns" and not include_warns:
                continue
            out_path = out_dir / out_name
            if out_path.exists() and not overwrite:
                extracted.append({"csv_name": out_name, "csv_kind": kind, "csv_path": str(out_path.resolve())})
                continue
            with zf.open(member) as src, out_path.open("wb") as dst:
                dst.write(src.read())
            extracted.append({"csv_name": out_name, "csv_kind": kind, "csv_path": str(out_path.resolve())})
    return extracted


def iter_flights(
    client: PipistrelClient,
    aircraft_ids: list[int],
    max_pages: int,
    start_page: int,
    target_regs: set[str],
    page_fetch_retries: int,
    page_fetch_backoff: float,
) -> Iterator[FlightListRow]:
    seen_ids: set[int] = set()
    for aircraft_id in aircraft_ids:
        base_path = f"/electro/aircraft/{aircraft_id}"
        first_soup = get_soup_with_retries(
            client,
            base_path,
            attempts=page_fetch_retries,
            backoff_seconds=page_fetch_backoff,
            context=f"Aircraft {aircraft_id} page 1 fetch",
        )
        if first_soup is None:
            continue
        aircraft_context = parse_aircraft_page_context(first_soup)
        default_registration = aircraft_context.get("registration", "")
        default_aircraft_type = aircraft_context.get("type", "")
        default_fleet = aircraft_context.get("fleet", "")
        discovered_pages = parse_total_pages(first_soup)
        crawl_start = max(1, start_page)
        total_pages = discovered_pages if max_pages <= 0 else min(discovered_pages, crawl_start + max_pages - 1)
        logging.info(
            "Aircraft %s: discovered %s page(s). Crawling page range %s..%s.",
            aircraft_id,
            discovered_pages,
            crawl_start,
            total_pages,
        )

        for page in range(crawl_start, total_pages + 1):
            path = base_path if page == 1 else f"{base_path}?page={page}"
            soup = first_soup if page == 1 else get_soup_with_retries(
                client,
                path,
                attempts=page_fetch_retries,
                backoff_seconds=page_fetch_backoff,
                context=f"Aircraft {aircraft_id} page {page} fetch",
            )
            if soup is None:
                continue
            rows = parse_flight_rows_with_defaults(
                soup,
                aircraft_id=aircraft_id,
                default_registration=default_registration,
                default_aircraft_type=default_aircraft_type,
                default_fleet=default_fleet,
            )
            logging.info("Aircraft %s page %s: %s flight rows found.", aircraft_id, page, len(rows))
            for row in rows:
                if row.flight_id in seen_ids:
                    continue
                seen_ids.add(row.flight_id)
                if target_regs and row.registration.upper() not in target_regs:
                    continue
                yield row


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Pipistrel Cloud events into CSV/event folders.")
    parser.add_argument("--username", default=os.getenv("PIPISTREL_USERNAME"), help="Pipistrel username")
    parser.add_argument("--password", default=os.getenv("PIPISTREL_PASSWORD"), help="Pipistrel password")
    parser.add_argument("--request-timeout", type=int, default=30, help="HTTP timeout in seconds for each request.")
    parser.add_argument("--registrations", nargs="+", default=["C-GAUW", "C-GMUW"], help="Tail registrations to include.")
    parser.add_argument("--aircraft-ids", nargs="+", type=int, default=DEFAULT_AIRCRAFT_IDS, help="Aircraft IDs to crawl.")
    parser.add_argument("--output-dir", default=str(DEFAULT_DATA_DIR), help="Base data directory.")
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH), help="Manifest CSV path.")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages per aircraft from --start-page. 0 means all pages.")
    parser.add_argument("--start-page", type=int, default=1, help="First page number to crawl for each aircraft ID.")
    parser.add_argument("--max-flights", type=int, default=0, help="Maximum events to process. 0 means no limit.")
    parser.add_argument("--include-warns", action="store_true", help="Include *_warns.csv files when extracting ZIPs.")
    parser.add_argument("--force-redownload", action="store_true", help="Download ZIP again even if already present.")
    parser.add_argument("--overwrite-extracted", action="store_true", help="Overwrite extracted CSV files if they already exist.")
    parser.add_argument("--page-fetch-retries", type=int, default=3, help="Retries for aircraft list page fetches.")
    parser.add_argument("--page-fetch-backoff", type=float, default=1.0, help="Backoff seconds * retry attempt for page fetch retries.")
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True, help="Skip events with existing event_metadata.json in raw_csv.")
    parser.add_argument("--sleep-seconds", type=float, default=0.15, help="Delay between flight detail requests.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging verbosity.")
    return parser.parse_args()


def main() -> int:
    args = build_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s | %(levelname)s | %(message)s")

    if not args.username or not args.password:
        raise SystemExit("Missing credentials. Set --username/--password or PIPISTREL_USERNAME/PIPISTREL_PASSWORD.")

    output_dir = Path(args.output_dir)
    raw_zip_root = output_dir / "raw_zips" / "by_plane"
    raw_csv_root = output_dir / "raw_csv" / "by_plane"
    raw_zip_root.mkdir(parents=True, exist_ok=True)
    raw_csv_root.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest_path)
    manifest_rows = load_manifest_rows(manifest_path)

    target_regs = {r.upper() for r in args.registrations}
    logging.info("Target registrations: %s", ", ".join(sorted(target_regs)))
    logging.info("Target aircraft IDs: %s", ", ".join(str(x) for x in args.aircraft_ids))

    client = PipistrelClient(args.username, args.password, timeout=args.request_timeout)
    client.login()
    logging.info("Login succeeded.")

    processed = 0
    downloaded = 0
    errors = 0
    skipped_existing = 0

    for row in iter_flights(
        client,
        aircraft_ids=args.aircraft_ids,
        max_pages=args.max_pages,
        start_page=args.start_page,
        target_regs=target_regs,
        page_fetch_retries=args.page_fetch_retries,
        page_fetch_backoff=args.page_fetch_backoff,
    ):
        if args.max_flights > 0 and processed >= args.max_flights:
            break

        plane_csv_root = raw_csv_root / str(row.aircraft_id)
        if args.skip_existing:
            existing_row = load_existing_event_manifest_row(plane_csv_root, row.flight_id)
            if existing_row is not None and not args.force_redownload:
                skipped_existing += 1
                manifest_rows[row.flight_id] = {field: existing_row.get(field, "") for field in MANIFEST_FIELDS}
                continue

        processed += 1
        scrape_error = ""
        csv_url = ""
        csv_path = ""
        csv_sha256 = ""
        csv_found = 0
        csv_files: list[Dict[str, str]] = []
        detail_map: Dict[str, str] = {}
        detail_resp_url = ""

        try:
            detail_path = f"/electro/flight/{row.flight_id}"
            detail_resp = client.get(detail_path)
            detail_resp_url = detail_resp.url
            detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
            detail_map = parse_flight_details(detail_soup)

            event_date = detail_map.get("date") or row.list_date or f"flight_{row.flight_id}"
            event_dir_name = build_event_dir_name(event_date, row.flight_id)
            zip_event_dir = raw_zip_root / str(row.aircraft_id) / event_dir_name
            csv_event_dir = raw_csv_root / str(row.aircraft_id) / event_dir_name
            csv_event_dir.mkdir(parents=True, exist_ok=True)

            csv_url = find_processed_csv_zip_url(detail_soup, detail_resp_url) or ""
            if csv_url:
                zip_event_dir.mkdir(parents=True, exist_ok=True)
                zip_name = Path(urlparse(csv_url).path).name
                local_zip = zip_event_dir / zip_name
                zip_bytes: Optional[bytes] = None
                download_url = csv_url
                missing_status: Optional[int] = None

                if local_zip.exists() and not args.force_redownload:
                    cached = local_zip.read_bytes()
                    if is_valid_zip_bytes(cached):
                        zip_bytes = cached
                    else:
                        logging.warning("Cached ZIP is invalid for flight %s (%s). Re-downloading.", row.flight_id, local_zip.name)
                        local_zip.unlink(missing_ok=True)

                if zip_bytes is None:
                    zip_bytes, download_url, missing_status = download_csv_zip(client, csv_url)
                    if zip_bytes is not None and is_valid_zip_bytes(zip_bytes):
                        local_zip.write_bytes(zip_bytes)
                        downloaded += 1
                    elif zip_bytes is not None:
                        logging.warning("Downloaded ZIP still invalid for flight %s (%s).", row.flight_id, download_url)
                        zip_bytes = None

                if zip_bytes is not None:
                    csv_found = 1
                    csv_url = download_url
                    csv_sha256 = hashlib.sha256(zip_bytes).hexdigest()
                    csv_path = str(local_zip.resolve())
                    csv_files = extract_csvs_from_zip_bytes(
                        zip_bytes=zip_bytes,
                        out_dir=csv_event_dir,
                        include_warns=args.include_warns,
                        overwrite=args.overwrite_extracted,
                    )
                else:
                    logging.warning("Flight %s CSV ZIP not downloadable (HTTP %s): %s", row.flight_id, missing_status, csv_url)

            metadata_path = csv_event_dir / "event_metadata.json"
            note_txt_path = csv_event_dir / "note.txt"
            note_text = detail_map.get("note", "")
            if note_text:
                write_text_file(note_txt_path, note_text)

            manifest_row: Dict[str, Any] = {
                "flight_id": row.flight_id,
                "aircraft_id": row.aircraft_id,
                "registration": row.registration,
                "list_date": row.list_date,
                "detail_date": detail_map.get("date", ""),
                "detail_flight_type": detail_map.get("flight type", ""),
                "detail_duration": detail_map.get("duration", ""),
                "detail_note": note_text,
                "route": row.route,
                "pilot": row.pilot,
                "aircraft_type": row.aircraft_type,
                "detail_aircraft": detail_map.get("aircraft", ""),
                "fleet": row.fleet,
                "departure_airport": detail_map.get("departure airport", ""),
                "destination_airport": detail_map.get("destination airport", ""),
                "battery_type": detail_map.get("battery type", ""),
                "end_of_flight_hobbs": detail_map.get("end of flight hobbs", ""),
                "event_dir_name": event_dir_name,
                "raw_csv_dir": str(csv_event_dir.resolve()),
                "metadata_path": str(metadata_path.resolve()),
                "note_txt_path": str(note_txt_path.resolve()) if note_text else "",
                "csv_found": csv_found,
                "csv_file_count": len(csv_files),
                "csv_files": ";".join(item["csv_name"] for item in csv_files),
                "csv_zip_url": csv_url,
                "csv_zip_path": csv_path,
                "csv_zip_sha256": csv_sha256,
                "scraped_at_utc": utc_now_iso(),
                "scrape_error": "",
            }
            write_json_file(
                metadata_path,
                {
                    **manifest_row,
                    "detail_fields": detail_map,
                    "detail_page_url": detail_resp_url,
                    "list_note": row.note,
                    "engine_duration": row.engine_duration,
                    "csv_files_detail": csv_files,
                },
            )
            manifest_rows[row.flight_id] = manifest_row
        except Exception as exc:  # pylint: disable=broad-exception-caught
            errors += 1
            scrape_error = str(exc)
            logging.exception("Flight %s failed: %s", row.flight_id, scrape_error)
            fallback_date = row.list_date or f"flight_{row.flight_id}"
            event_dir_name = build_event_dir_name(fallback_date, row.flight_id)
            csv_event_dir = raw_csv_root / str(row.aircraft_id) / event_dir_name
            csv_event_dir.mkdir(parents=True, exist_ok=True)
            metadata_path = csv_event_dir / "event_metadata.json"
            manifest_row = {
                "flight_id": row.flight_id,
                "aircraft_id": row.aircraft_id,
                "registration": row.registration,
                "list_date": row.list_date,
                "detail_date": detail_map.get("date", ""),
                "detail_flight_type": detail_map.get("flight type", ""),
                "detail_duration": detail_map.get("duration", ""),
                "detail_note": detail_map.get("note", row.note),
                "route": row.route,
                "pilot": row.pilot,
                "aircraft_type": row.aircraft_type,
                "detail_aircraft": detail_map.get("aircraft", ""),
                "fleet": row.fleet,
                "departure_airport": detail_map.get("departure airport", ""),
                "destination_airport": detail_map.get("destination airport", ""),
                "battery_type": detail_map.get("battery type", ""),
                "end_of_flight_hobbs": detail_map.get("end of flight hobbs", ""),
                "event_dir_name": event_dir_name,
                "raw_csv_dir": str(csv_event_dir.resolve()),
                "metadata_path": str(metadata_path.resolve()),
                "note_txt_path": "",
                "csv_found": 0,
                "csv_file_count": 0,
                "csv_files": "",
                "csv_zip_url": csv_url,
                "csv_zip_path": csv_path,
                "csv_zip_sha256": csv_sha256,
                "scraped_at_utc": utc_now_iso(),
                "scrape_error": scrape_error,
            }
            write_json_file(
                metadata_path,
                {
                    **manifest_row,
                    "detail_fields": detail_map,
                    "detail_page_url": detail_resp_url,
                    "list_note": row.note,
                    "engine_duration": row.engine_duration,
                },
            )
            manifest_rows[row.flight_id] = manifest_row

        time.sleep(max(args.sleep_seconds, 0.0))

    save_manifest_rows(manifest_path, manifest_rows)
    logging.info("Done.")
    logging.info("Events processed: %s", processed)
    logging.info("ZIP files downloaded: %s", downloaded)
    logging.info("Events skipped (already processed): %s", skipped_existing)
    logging.info("Errors: %s", errors)
    logging.info("Manifest CSV: %s", manifest_path.resolve())
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
