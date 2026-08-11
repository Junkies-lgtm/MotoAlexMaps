"""
manifest_utils.py

Kleines Hilfsmodul zum Lesen und Aktualisieren des zentralen manifest.json
im Repo-Root. Mehrere Skripte (rd5, Blitzer, spaeter evtl. Karten) teilen
sich diese eine Datei -- jedes Skript aktualisiert NUR seinen eigenen
Abschnitt (top-level key), die Abschnitte der anderen bleiben unberuehrt.

Die App liest diese Datei spaeter ueber eine rohe GitHub-URL:
    https://raw.githubusercontent.com/<user>/<repo>/main/manifest.json
Das ist ein normaler Dateidownload (kein API-Call), zaehlt also nicht
gegen GitHubs API-Rate-Limit.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_of_file(path: Path) -> str:
    """Berechnet die SHA256-Pruefsumme einer Datei, ohne sie komplett in
    den Speicher zu laden (wichtig bei grossen .rd5/.mbtiles-Dateien)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> dict:
    """Laedt das bestehende manifest.json, oder liefert eine leere
    Grundstruktur, falls die Datei noch nicht existiert (erster Lauf)."""
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"generated_at": None}


def save_manifest(manifest: dict, manifest_path: Path) -> None:
    """Schreibt das Manifest zurueck, mit aktualisiertem Zeitstempel."""
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


def update_section(manifest_path: Path, section_key: str, section_data: dict) -> None:
    """Aktualisiert NUR den angegebenen Abschnitt (z.B. 'rd5' oder
    'blitzer') im gemeinsamen Manifest, laesst alle anderen Abschnitte
    unangetastet. Sicher gegenueber mehreren Skripten, die dieselbe
    Datei zu unterschiedlichen Zeitpunkten pflegen."""
    manifest = load_manifest(manifest_path)
    manifest[section_key] = section_data
    save_manifest(manifest, manifest_path)
