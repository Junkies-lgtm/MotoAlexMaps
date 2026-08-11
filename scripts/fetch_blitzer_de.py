#!/usr/bin/env python3
"""
fetch_blitzer_de.py

Laedt feste Blitzer (highway=speed_camera) fuer ganz Deutschland ueber die
Overpass-API, bundeslandweise (16 Einzelabfragen statt einer riesigen), und
fuehrt die Ergebnisse automatisch zu einer Datei blitzer_deutschland.json
zusammen.

Gedacht fuer wartungsarmen, wiederkehrenden Betrieb (z.B. woechentlich per
Windows-Aufgabenplanung oder cron). Ein einzelner Lauf terminiert immer von
selbst -- es gibt keine Endlosschleife.

Ausfallverhalten:
  - Pro Bundesland wird ueber mehrere Overpass-Mirrors versucht.
  - Schlaegt ein Bundesland fehl, wird es mit steigender Wartezeit
    (Exponential Backoff, gedeckelt) erneut versucht.
  - Die maximale Gesamt-Retry-Zeit PRO BUNDESLAND ist auf RETRY_BUDGET_SECONDS
    begrenzt (Default 5 Minuten). Danach wird das Bundesland als
    fehlgeschlagen markiert und uebersprungen -- der Lauf insgesamt bricht
    dadurch nie komplett ab.
  - Bereits erfolgreich geladene Bundeslaender aus vorherigen Laeufen
    (state.json) werden bei einem kompletten Fehlschlag als Fallback benutzt,
    damit die Gesamtdatei nicht durch einen einzelnen schlechten Lauf leer
    oder unvollstaendig wird.

Aufruf:
    python fetch_blitzer_de.py
"""

import json
import logging
import random
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from manifest_utils import sha256_of_file, update_section

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = OUTPUT_DIR / "blitzer_deutschland.json"
STATE_DIR = OUTPUT_DIR / "blitzer_state"          # ein JSON pro Bundesland
LOG_FILE = OUTPUT_DIR / "fetch_blitzer_de.log"
MANIFEST_PATH = OUTPUT_DIR.parent / "manifest.json"   # Repo-Root, eine Ebene ueber scripts/

RETRY_BUDGET_SECONDS = 10 * 60     # max. Wartezeit+Versuche PRO Bundesland
INITIAL_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 45
REQUEST_TIMEOUT_SECONDS = 100       # knapp ueber dem serverseitigen [timeout:90]
                                     # der Query -> genug Luft, aber ein einzelner
                                     # haengender Versuch blockiert nicht zu lange

# Mehrere Mirrors, falls einer down/langsam ist oder blockt (406 etc.)
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

USER_AGENT = "MotoAlex-Blitzer-Fetcher/1.0 (Kontakt: privates Projekt)"

# Name + ISO3166-2-Code. Der Code wird fuer die Overpass-Abfrage benutzt statt
# des Namens -- vermeidet Mehrdeutigkeiten bei der Namenssuche (z.B. gab es bei
# reiner Namensabfrage fuer Bayern auffaellig wenige Treffer, vermutlich weil
# "name"="Bayern" nicht zuverlaessig die richtige/vollstaendige Area trifft).
BUNDESLAENDER = [
    ("Baden-Württemberg", "DE-BW"),
    ("Bayern", "DE-BY"),
    ("Berlin", "DE-BE"),
    ("Brandenburg", "DE-BB"),
    ("Bremen", "DE-HB"),
    ("Hamburg", "DE-HH"),
    ("Hessen", "DE-HE"),
    ("Mecklenburg-Vorpommern", "DE-MV"),
    ("Niedersachsen", "DE-NI"),
    ("Nordrhein-Westfalen", "DE-NW"),
    ("Rheinland-Pfalz", "DE-RP"),
    ("Saarland", "DE-SL"),
    ("Sachsen", "DE-SN"),
    ("Sachsen-Anhalt", "DE-ST"),
    ("Schleswig-Holstein", "DE-SH"),
    ("Thüringen", "DE-TH"),
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("blitzer")


def build_query(iso_code: str) -> str:
    # Direkte Suche ueber den ISO3166-2-Code statt ueber den Namen -- eindeutig,
    # keine Verwechslungsgefahr mit gleichnamigen kleineren Gebieten/Relationen.
    return f"""
    [out:json][timeout:90];
    area["ISO3166-2"="{iso_code}"]->.bl;
    (
      node["highway"="speed_camera"](area.bl);
      way["highway"="speed_camera"](area.bl);
    );
    out center;
    """


def query_overpass(query: str) -> dict:
    """Ein einzelner HTTP-Versuch gegen einen zufaellig gewaehlten Mirror.
    Wirft eine Exception bei jedem Fehler (Netzwerk, Timeout, HTTP-Fehler,
    kaputtes JSON)."""
    mirror = random.choice(OVERPASS_MIRRORS)
    data = query.encode("utf-8")
    req = urllib.request.Request(
        mirror,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        raw = resp.read()
    return json.loads(raw)


def fetch_bundesland_with_retry(bundesland: str, iso_code: str) -> list | None:
    """Versucht ein Bundesland zu laden, mit Exponential Backoff, bis
    RETRY_BUDGET_SECONDS ueberschritten ist. Gibt die Liste der Elemente
    zurueck oder None bei endgueltigem Fehlschlag."""
    query = build_query(iso_code)
    deadline = time.monotonic() + RETRY_BUDGET_SECONDS
    backoff = INITIAL_BACKOFF_SECONDS
    attempt = 0

    while True:
        attempt += 1
        try:
            result = query_overpass(query)
            elements = result.get("elements", [])

            # Plausibilitaetscheck: ein technisch erfolgreicher Abruf mit 0
            # Treffern ist fuer ein Bundesland (das garantiert feste Blitzer
            # hat) fast immer ein Server-seitiges Problem bei Overpass, keine
            # echte Datenlage. Wird als Fehlschlag gewertet -> erneuter
            # Versuch, statt eine 0 als "letzten guten Stand" zu speichern.
            if len(elements) == 0:
                raise ValueError("Antwort kam durch, aber 0 Treffer -- vermutlich "
                                  "unvollstaendige Overpass-Antwort, kein Erfolg")

            log.info("  %s: OK (%d Kameras, Versuch %d)",
                      bundesland, len(elements), attempt)
            return elements
        except Exception as exc:
            remaining = deadline - time.monotonic()
            log.warning("  %s: Versuch %d fehlgeschlagen (%s), noch ~%ds Budget",
                        bundesland, attempt, exc, max(0, int(remaining)))
            if remaining <= 0:
                log.error("  %s: Retry-Budget aufgebraucht, gebe auf", bundesland)
                return None
            sleep_for = min(backoff, remaining)
            time.sleep(sleep_for)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


def load_previous_state(bundesland: str) -> list | None:
    path = STATE_DIR / f"{bundesland}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("  %s: alter Stand nicht lesbar (%s)", bundesland, exc)
        return None


def save_state(bundesland: str, elements: list) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"{bundesland}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(elements, f, ensure_ascii=False)


def normalize_element(el: dict, bundesland: str) -> dict:
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    return {
        "id": f"{el.get('type')}/{el.get('id')}",
        "lat": lat,
        "lon": lon,
        "bundesland": bundesland,
        "tags": el.get("tags", {}),
    }


def main() -> None:
    started = datetime.now(timezone.utc)
    log.info("=== Blitzer-Abfrage Deutschland gestartet ===")

    all_elements: dict[str, dict] = {}   # id -> normalisiertes Element
    failed: list[str] = []
    used_fallback: list[str] = []

    for bundesland, iso_code in BUNDESLAENDER:
        log.info("Bundesland: %s (%s)", bundesland, iso_code)
        elements = fetch_bundesland_with_retry(bundesland, iso_code)

        if elements is None:
            previous = load_previous_state(bundesland)
            if previous is not None:
                log.warning("  %s: nutze letzten erfolgreichen Stand (%d Kameras)",
                            bundesland, len(previous))
                elements = previous
                used_fallback.append(bundesland)
            else:
                log.error("  %s: kein alter Stand vorhanden, Bundesland fehlt "
                           "in diesem Lauf komplett", bundesland)
                failed.append(bundesland)
                continue
        else:
            save_state(bundesland, elements)

        for el in elements:
            norm = normalize_element(el, bundesland)
            if norm["lat"] is not None and norm["lon"] is not None:
                all_elements[norm["id"]] = norm

    result = {
        "generated_at": started.isoformat(),
        "source": "OpenStreetMap via Overpass API (highway=speed_camera)",
        "count": len(all_elements),
        "failed_bundeslaender": failed,
        "fallback_bundeslaender": used_fallback,
        "cameras": list(all_elements.values()),
    }

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=None)

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    log.info("=== Fertig in %.0fs: %d Kameras gesamt, %d Bundeslaender komplett "
              "fehlgeschlagen, %d ueber Fallback ===",
              duration, len(all_elements), len(failed), len(used_fallback))

    if failed:
        log.warning("Fehlende Bundeslaender in diesem Lauf: %s", ", ".join(failed))

    # Manifest aktualisieren -- Version/Pruefsumme der Gesamtdatei, damit die
    # App per raw-GitHub-URL pruefen kann, ob eine neue blitzer_deutschland.json
    # vorliegt, ohne die (mehrere hundert KB grosse) Datei selbst laden zu muessen.
    blitzer_section = {
        "version": started.strftime("%Y-%m-%d"),
        "size_bytes": OUTPUT_FILE.stat().st_size,
        "sha256": sha256_of_file(OUTPUT_FILE),
        "camera_count": len(all_elements),
    }
    update_section(MANIFEST_PATH, "blitzer", blitzer_section)
    log.info("Manifest aktualisiert: %s", MANIFEST_PATH)


if __name__ == "__main__":
    main()
