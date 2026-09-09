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
    
    # Nutzt das GitHub Token aus der Umgebung für stabiles API-Limit
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
    print("Starte Manifest-Generierung (Option B: Fokus auf Dateigröße)...")
    
    # Assets von beiden Releases abrufen
    mbtiles_assets = fetch_release_assets("latest-mbtiles")
    brouter_assets = fetch_release_assets("latest-rd5")
    
    all_files = {}
    
    # 1. MBTiles (Bundesländer) verarbeiten
    for asset in mbtiles_assets:
        name = asset["name"]
        # Ignoriere Hilfsdateien oder temporäre Reste im Release
        if name.endswith(".tmp") or name.endswith(".json") or name.endswith(".md"):
            continue
        all_files[name] = {
            "filename": name,
            "type": "mbtiles",
            "size_bytes": asset["size"],  # Exakte Bytegröße von GitHub
            "url": asset["browser_download_url"]
        }
        
    # 2. BRouter-Kacheln (.rd5) verarbeiten
    for asset in brouter_assets:
        name = asset["name"]
        if name.endswith(".tmp") or name.endswith(".json") or name.endswith(".md"):
            continue
        all_files[name] = {
            "filename": name,
            "type": "brouter",
            "size_bytes": asset["size"],  # Exakte Bytegröße von GitHub
            "url": asset["browser_download_url"]
        }

    # 3. Bundles definieren (Das "1-Klick-Deutschland-Paket")
    bundles = {
        "germany_complete": {
            "display_name": "Deutschland komplett",
            "description": "Reiht alle verfügbaren Bundesländer und BRouter-Routing-Kacheln in die Warteschlange ein.",
            "required_files": list(all_files.keys())
        }
    }
    
    # 4. Gesamt-Manifest zusammenbauen
    manifest = {
        "meta": {
            "version": int(datetime.now().strftime("%Y%m%d%H%M")), # Version als Timestamp (YYYYMMDDHHMM)
            "updated_at": datetime.now().isoformat(),
            "compatible_app_version": ">=1.0.0"
        },
        "bundles": bundles,
        "files": all_files
    }
    
    # 5. Manifest speichern
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, ensure_ascii=False)
        
    print(f"Erfolg! Manifest mit {len(all_files)} Dateien unter '{OUTPUT_FILE}' erstellt.")

if __name__ == "__main__":
    main()
