import os
import json
import urllib.request
from datetime import datetime

# --- KONFIGURATION ---
REPO = "Junkies-lgtm/MotoAlexMaps"
OUTPUT_FILE = "maps_manifest.json"

def fetch_release_assets(tag):
    """Holt die Asset-Informationen eines bestimmten Tags über die GitHub API."""
    url = f"https://github.com{REPO}/releases/tags/{tag}"
    req = urllib.request.Request(
        url, 
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github.v3+json"}
    )
    
    # Falls ein GitHub Token in den Umgebungsvariablen existiert (für höhere API Limits)
    if "GITHUB_TOKEN" in os.environ:
        req.add_header("Authorization", f"token {os.environ['GITHUB_TOKEN']}")
        
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get("assets", [])
    except Exception as e:
        print(f"Fehler beim Abrufen des Tags {tag}: {e}")
        return []

def main():
    print("Starte Manifest-Generierung aus GitHub Releases...")
    
    # 1. Assets von beiden Releases abrufen
    mbtiles_assets = fetch_release_assets("latest-mbtiles")
    brouter_assets = fetch_release_assets("latest-rd5")
    
    all_files = {}
    
    # 2. MBTiles verarbeiten
    for asset in mbtiles_assets:
        name = asset["name"]
        if name.endswith(".tmp") or name.endswith(".json"):
            continue
        all_files[name] = {
            "filename": name,
            "type": "mbtiles",
            "size_bytes": asset["size"],
            "sha256": "placeholder_wird_bei_erstellung_erzeugt", # Siehe Erklärung unten
            "url": asset["browser_download_url"]
        }
        
    # 3. BRouter-Kacheln verarbeiten
    for asset in brouter_assets:
        name = asset["name"]
        if name.endswith(".tmp") or name.endswith(".json"):
            continue
        all_files[name] = {
            "filename": name,
            "type": "brouter",
            "size_bytes": asset["size"],
            "sha256": "placeholder_wird_bei_erstellung_erzeugt",
            "url": asset["browser_download_url"]
        }

    # 4. Bundles definieren (Deutschland komplett)
    bundles = {
        "germany_complete": {
            "display_name": "Deutschland komplett",
            "description": "Lädt alle verfügbaren Bundesländer und BRouter-Routing-Kacheln.",
            "required_files": list(all_files.keys())
        }
    }
    
    # 5. Manifest zusammenbauen
    manifest = {
        "meta": {
            "version": int(datetime.now().strftime("%Y%m%d%H%M")),
            "updated_at": datetime.now().isoformat(),
            "compatible_app_version": ">=1.0.0"
        },
        "bundles": bundles,
        "files": all_files
    }
    
    # 6. Speichern
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, ensure_ascii=False)
        
    print(f"Manifest erfolgreich mit {len(all_files)} Dateien erstellt!")

if __name__ == "__main__":
    main()
