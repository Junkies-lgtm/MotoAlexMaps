#!/usr/bin/env python3
"""
fetch_rd5_germany.py

Laedt alle fuer ganz Deutschland benoetigten BRouter-.rd5-Kacheln von
brouter.de herunter -- robust, fortsetzbar, ein Fehlschlag stoppt nicht
die anderen Kacheln.

Kachel-Liste (5x5 Grad, deckt die Landesflaeche Deutschlands ab):
    E5_N45   E5_N50   E5_N55
    E10_N45  E10_N50
             E15_N50

Aufruf:
    python fetch_rd5_germany.py
    python fetch_rd5_germany.py --output-dir D:/BRouterTiles
    python fetch_rd5_germany.py --force
"""

import argparse
import logging
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from manifest_utils import sha256_of_file, update_section

BASE_URL = "https://brouter.de/brouter/segments4"

GERMANY_TILES = [
    "E5_N45", "E5_N50", "E5_N55",
    "E10_N45", "E10_N50",
    "E15_N50",
]

RETRY_BUDGET_SECONDS = 5 * 60
INITIAL_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 45
REQUEST_TIMEOUT_SECONDS = 120

USER_AGENT = "MotoAlex-RD5-Fetcher/1.0 (Kontakt: privates Projekt)"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Laedt alle BRouter-.rd5-Kacheln fuer Deutschland herunter")
    p.add_argument("--output-dir", type=Path, default=Path("."),
                    help="Zielordner (Default: aktueller Ordner)")
    p.add_argument("--force", action="store_true",
                    help="Bereits vorhandene Kacheln trotzdem neu herunterladen")
    p.add_argument("--manifest-path", type=Path, default=None,
                    help="Pfad zum zentralen manifest.json (z.B. manifest.json im Repo-Root). "
                         "Wird nicht angegeben, bleibt das Manifest unangetastet -- praktisch fuer "
                         "lokale Testlaeufe ohne Repo-Kontext.")
    return p.parse_args()


def download_tile(tile_name: str, output_dir: Path, log: logging.Logger) -> bool:
    """Laedt eine einzelne .rd5-Kachel mit Retry/Backoff herunter.
    Gibt True bei Erfolg zurueck, False bei endgueltigem Fehlschlag."""
    url = f"{BASE_URL}/{tile_name}.rd5"
    output_path = output_dir / f"{tile_name}.rd5"
    tmp_path = output_dir / f"{tile_name}.rd5.part"

    deadline = time.monotonic() + RETRY_BUDGET_SECONDS
    backoff = INITIAL_BACKOFF_SECONDS
    attempt = 0

    while True:
        attempt += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                total_size = resp.headers.get("Content-Length")
                total_size = int(total_size) if total_size else None
                downloaded = 0

                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

            if total_size is not None and downloaded != total_size:
                raise IOError(f"Unvollstaendiger Download: {downloaded} von {total_size} Bytes")

            tmp_path.rename(output_path)
            size_mb = downloaded / (1024 * 1024)
            log.info("  -> OK (%.1f MB, Versuch %d)", size_mb, attempt)
            return True

        except Exception as exc:
            remaining = deadline - time.monotonic()
            log.warning("  -> Versuch %d fehlgeschlagen (%s), noch ~%ds Budget",
                        attempt, exc, max(0, int(remaining)))
            if tmp_path.exists():
                tmp_path.unlink()
            if remaining <= 0:
                log.error("  -> Retry-Budget aufgebraucht, gebe auf")
                return False
            sleep_for = min(backoff, remaining)
            time.sleep(sleep_for)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


def main() -> int:
    args = parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    log_file = output_dir / "fetch_rd5_germany.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )
    log = logging.getLogger("rd5")

    log.info("=== Download von %d Kacheln fuer Deutschland gestartet ===", len(GERMANY_TILES))

    succeeded = []
    skipped = []
    failed = []

    for i, tile in enumerate(GERMANY_TILES, start=1):
        log.info("[%d/%d] %s", i, len(GERMANY_TILES), tile)
        output_path = output_dir / f"{tile}.rd5"

        if output_path.exists() and not args.force:
            size_mb = output_path.stat().st_size / (1024 * 1024)
            log.info("  -> uebersprungen, %s existiert bereits (%.1f MB, --force zum Erzwingen)",
                      output_path.name, size_mb)
            skipped.append(tile)
            continue

        if download_tile(tile, output_dir, log):
            succeeded.append(tile)
        else:
            failed.append(tile)

    log.info("=== Fertig: %d erfolgreich, %d uebersprungen, %d fehlgeschlagen ===",
              len(succeeded), len(skipped), len(failed))
    if failed:
        log.warning("Fehlgeschlagene Kacheln: %s", ", ".join(failed))

    # Manifest aktualisieren -- nur mit den Kacheln, die tatsaechlich lokal
    # vorliegen (egal ob gerade frisch geladen oder schon vorher da).
    # Fehlgeschlagene Kacheln fehlen im Manifest-Abschnitt, damit die App
    # dort nicht faelschlich eine "aktuelle" Version vermutet.
    if args.manifest_path is not None:
        rd5_section = {}
        version = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for tile in GERMANY_TILES:
            tile_path = output_dir / f"{tile}.rd5"
            if tile_path.exists():
                rd5_section[tile] = {
                    "version": version,
                    "size_bytes": tile_path.stat().st_size,
                    "sha256": sha256_of_file(tile_path),
                }
        update_section(args.manifest_path, "rd5", rd5_section)
        log.info("Manifest aktualisiert: %s (%d Kacheln erfasst)",
                  args.manifest_path, len(rd5_section))

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
