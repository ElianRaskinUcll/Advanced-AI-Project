# Progress

Per issue: wat gedaan, wat vlot ging, en waar we tegen problemen liepen.

---

## Issue #11 — Repository setup

**Wat gedaan**
- Mappenstructuur aangemaakt: `data/raw/`, `data/processed/`, `notebooks/`, `src/`, `models/`, `reports/figures/`, `tests/`, `scripts/`.
- `.gitignore` (Python + macOS), `LICENSE` (MIT), `requirements.txt`, `Makefile`, README skeleton met de 6 gevraagde secties.
- Bestaande bestanden opgeruimd: [dataVisualisatie.ipynb](notebooks/dataVisualisatie.ipynb) → `notebooks/`, raw data → `data/raw/`, `exportData.ipynb` + `test.py` verwijderd.
- Op verzoek toch raw data **wel** in git gehouden (afwijking van originele issue-tekst): `.gitignore`-regel voor `data/raw/` weer geschrapt.

**Vlot**
- DoD-validatie via `pip install --dry-run -r requirements.txt` resolvet alles zonder errors.
- 71 git renames correct gedetecteerd na de file-moves (history blijft behouden).

**Problemen**
- Eerste poging `data/raw/` te gitignoren met `data/raw/` + `!data/raw/.gitkeep` werkte niet — git recursed niet in een ignored directory. Opgelost met patroon `data/raw/*` + negation. Na de scope-wijziging (raw data wel in git) sowieso weer geschrapt.
- `mv foubertai_export data/raw/...` gebruikte normale `mv` ipv `git mv`, waardoor git aanvankelijk delete + add zag ipv rename. Opgelost door `git add` van nieuwe locatie + `git add -u` op oude locatie zodat git de renames detecteert.
- macOS `._*` metadata-bestanden zaten in de initial commit. Worden nu door `.gitignore` weggefilterd op de nieuwe locatie — toevallige cleanup.

---

## Issue — Canonieke data loader + master dataframe

**Wat gedaan**
- [src/data/load.py](src/data/load.py) met 8 `load_*` functies (één per tabel + GPS).
- Standaard joins geïmplementeerd: sales+shifts (voor zone), sale_orders→sales→shifts, calls met `answered` flag, GPS per kar (geconcateneerde DF met `icecream_van_id`).
- Datatypes correct gecast: datetimes via `parse_dates`, categoricals (status, reservation_type, addressen, menu names), numerics (Int64 nullable waar nodig, float64).
- `build_master_dataframe()` levert lange event-tabel met exact `(timestamp, zone, event_type, van_id, value)`.
- Output naar [data/processed/events.parquet](data/processed/events.parquet) — 11.510 events.
- `pyarrow` toegevoegd aan requirements voor parquet write.

**Vlot**
- Alle event-counts matchen de README exact: 2.219 sales, 7.273 sale_orders, 1.766 calls (469 answered + 1.297 missed), 38 reservations, 88 shifts.
- `python -W error -m src.data.load` (warnings → errors) draait door zonder errors.

**Problemen**
- `python -m src.data.load` gaf `RuntimeWarning` omdat `src/data/__init__.py` `load.py` al pre-importeerde. Init leeggemaakt — gebruikers importeren nu via `from src.data.load import ...`.
- `pd.read_csv` faalde initieel met `Unable to parse "924�"` op Windows wegens default encoding. Toegevoegd: `encoding="utf-8"` in `_read_tsv`.
- Toch nog dezelfde error: bleek dat één rij in `2026-05-01/07_calls.tsv` een **literal** U+FFFD replacement-character heeft in `address_zipcode` (`"924�"`) — datavuil in de bron, geen encoding bug. Opgelost door zipcode als string in te lezen en daarna `pd.to_numeric(..., errors="coerce").astype("Int64")` zodat die ene rij `<NA>` wordt zonder de hele load te breken.
- Beslissing: GPS (~697k punten) **niet** in events.parquet opgenomen — wel beschikbaar via `load_gps()`. Anders zou de event-tabel ~60× opgeblazen worden door tracking-data die geen "event" is.

**Open punt voor later**
- `zone` mengt nu twee semantieken: `icecream_van_zone_id` voor operationele events vs `address_zipcode` voor klant-events. Bij behoefte aan harmonisatie → eigen issue.
