"""Look up coordinates for place names (needs internet + `pip install osmnx`).
  python -m tools.geocode "Jayadeva Hospital, Bengaluru" "HSR Layout, Bengaluru"
Paste the printed lines into locations.json (origins or hospitals)."""
import sys


def main():
    import osmnx as ox
    for q in sys.argv[1:]:
        try:
            lat, lon = ox.geocode(q)
            print(f'{{"name": "{q.split(",")[0].strip()}", "lat": {lat:.5f}, "lon": {lon:.5f}}},')
        except Exception as e:
            print(f"# {q}: not found ({e})")


if __name__ == "__main__":
    main()
