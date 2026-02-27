#!/usr/bin/env python3
"""Legacy helper to nest flat ZIP files into per-event folders.

This is only for older layouts such as:
- data/raw_zips/by_plane/<plane_id>/<flight_bundle>.zip

It rewrites them to:
- data/raw_zips/by_plane/<plane_id>/<flight_bundle>/<flight_bundle>.zip

New scrapes already write event folders directly, so this script is mainly for legacy cleanup.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_RAW_ZIPS_DIR = PROJECT_ROOT / "data" / "raw_zips" / "by_plane"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Group legacy flat ZIPs into nested event folders.")
    parser.add_argument("--raw-zips", default=str(DEFAULT_RAW_ZIPS_DIR), help="Plane-based ZIP root folder.")
    parser.add_argument("--mode", choices=["copy", "move"], default="copy", help="copy: keep originals, move: relocate files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite destination file if it already exists.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_zips = Path(args.raw_zips)
    if not raw_zips.exists():
        raise SystemExit(f"Raw ZIP directory not found: {raw_zips}")

    total = 0
    nested = 0
    skipped = 0

    for plane_dir in sorted(p for p in raw_zips.iterdir() if p.is_dir()):
        for zpath in sorted(plane_dir.glob("*.zip")):
            total += 1
            dest_dir = plane_dir / zpath.stem
            dest = dest_dir / zpath.name
            if dest.exists() and not args.overwrite:
                skipped += 1
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            if args.mode == "copy":
                shutil.copy2(zpath, dest)
            else:
                shutil.move(zpath, dest)
            nested += 1

    print(f"ZIP files scanned: {total}")
    print(f"ZIP files nested: {nested}")
    print(f"ZIP files skipped: {skipped}")
    print(f"Raw ZIP root: {raw_zips.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
