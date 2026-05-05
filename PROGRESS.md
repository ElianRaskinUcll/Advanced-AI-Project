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

---

## Issue 1.3 — Verkooppunten reverse-engineeren + zone-systeem

**DoD-aanpassing:** oorspronkelijk ≥70% sales gematcht — bijgesteld naar **≥60%** na data-exploratie. Behaald: **63,9%** ✅.

**Wat gedaan**
- [src/zones.py](src/zones.py) met `cluster_stops()`, `match_sales_to_stops()`, `build_stops_and_zones()`.
- DBSCAN-clustering op trage GPS (`velocity<0.5 m/s`), haversine-metric, eps=50m.
- Matching per sale: dichtste geclusterd GPS-punt van **dezelfde van** binnen 100m + ±5min.
- H3 hexagons resolutie 9 (~150m) als zone-systeem; per stop en per sale toegewezen.
- Outputs: [data/processed/stops.parquet](data/processed/stops.parquet) (586 stops, 9 kolommen) en [data/processed/zones.geojson](data/processed/zones.geojson) (575 hexagons).
- Documentatie + Challenges-framing in [notebooks/01_eda_zones.ipynb](notebooks/01_eda_zones.ipynb).
- `scikit-learn` en `h3>=4` toegevoegd aan requirements.

**Vlot**
- Zone-keuze (H3 res 9) was rechttoe rechtaan motiveerbaar: `area_id`/`zone_id` is operationeel-per-shift, niet ruimtelijk; H3 geeft een deterministische map van willekeurige (lat, lng) naar zone, op de juiste schaal voor onze stop-radius.
- Eens parameters bijgesteld (zie hieronder): pipeline draait warning-vrij in ~2s (BallTree haversine doet zwaar werk).
- Toevallige bug in `load_gps`: één leeg bestand (`van_15.tsv` op 2 mei) gaf FutureWarning bij `pd.concat`. Direct opgelost door empty frames te skippen.

**Problemen — pivot-verhaal**
- **Issue-parameters letterlijk gevolgd** (`min_samples=10`): match-rate **20,5%**, ver onder DoD.
- **Diagnose:** GPS-sampling is bursty. Slechts 0,76% van GPS-punten heeft `velocity<0.5`; **maximaal 4** trage punten binnen 100m+5min van enige sale. `min_samples=10` clustert daardoor enkel langdurige depot-stays — echte verkoop-stops vallen buiten elk cluster. Concreet voorbeeld in inspectie: een van die 3,5 min op een sale-locatie staat genereert maar 1 GPS-punt met `velocity=0`; sampling-gaps tot 73s tijdens stilstand.
- **Pivot 1:** Per (van, dag) clusteren om time-windows realistisch te houden → 19,5% (geen wezenlijke verbetering: clusters blijven schaars).
- **Pivot 2:** Algoritme C voorgesteld — temporal density (≥3 buren binnen 50m+5min) en variant met "all neighbors within radius" (sustained-presence). Test: standaard temporal density flagde **99% van GPS** als stationary (sampling tijdens rijden is zo dicht dat 5min-venster altijd ≥3 buren binnen 50m heeft). Striktere "sustained-presence" variant gaf 1,7-24% flagged maar slechts **25,6%** match-rate — fundamentele mismatch tussen sample-pattern en algoritme-aanname.
- **Resolutie:** stop-detectie blijft velocity-gebaseerd (zoals de issue), maar `min_samples` van 10 → **2**. Met deze lenientie cluster bijna elk traag GPS-punt in een paar; sales matchen aan dichtste cluster-lid van dezelfde van → **63,9%** match-rate.
- **Halt en vragen ipv stilletjes afwijken:** ik pauzeerde voor de DoD-bijstelling om gebruiker mee te beslissen — gevalideerde aanpak. Bewaard als feedback voor toekomstige conflicten tussen issue-tekst en data-realiteit.

**Open punten voor later**
- `total_revenue` per stop telt enkel matched sales; ~36% sales is unmatched en tellen niet mee. Bij voorraad-modelering moet hier rekening mee gehouden worden.
- Sustained-presence (algoritme C) blijft conceptueel aantrekkelijker dan velocity-flagging, maar vereist andere GPS-sampling-eigenschappen dan deze fleet levert. Mocht een latere dataset wel uniforme sampling hebben, kan de aanpak heroverwogen worden.

---

## Issue 1.4 — Weer + kalender-context

**Wat gedaan**
- [src/context.py](src/context.py) met `fetch_weather()` (Open-Meteo Archive API), `add_day_type()`, `build_context()`.
- Per uur temperatuur, neerslag en zonneschijn-duur opgehaald voor Bornem (51.10°N, 4.24°E), 30 apr — 2 mei 2026, in UTC.
- `day_type` bepaald uit hardgecodeerde Belgische feestdagen 2026 + dayofweek: 30/4 → `weekday`, 1/5 → `holiday` (Dag van de Arbeid), 2/5 → `weekend`.
- Output [data/processed/context.parquet](data/processed/context.parquet): 72 rijen (24×3), kolommen `(timestamp, temperature, precipitation, sunshine, day_type)`.
- Plot [reports/figures/context_temperature.png](reports/figures/context_temperature.png) van temperatuur over 3 dagen.

**Vlot**
- Open-Meteo Archive heeft 2026-data — geen fallback nodig naar synthetic of nabij-jaar-substitutie zoals ik vooraf vreesde.
- Geen extra dependency: `urllib` uit stdlib volstaat voor één GET-call (vs. `requests` toevoegen aan requirements).
- DoD-checks beide groen: 0 NaNs in alle 5 kolommen, temperatuur-plot toont duidelijke diurnale cyclus (8-9°C 's nachts → 22-24°C op middag, twee zonnige + één frissere dag) — sluit aan bij wat je voor eind april in België verwacht.

**Problemen**
- Geen — issue draaide vlot vergeleken met 1.3.

**Belgische feestdagen-lijst** is hardgecodeerd voor 2026 ipv via een package. Reden: één jaar dekken volstaat voor dit project; `holidays`-package toevoegen voegt afhankelijkheid toe voor minimal value. Mocht de data uitbreiden naar andere jaren, dien de set uit te breiden of `holidays` toe te voegen.

---

## Issue 1.5 — EDA voor het Data-deel van de fiche

**Wat gedaan**
- [notebooks/02_eda.ipynb](notebooks/02_eda.ipynb) end-to-end uitvoerbaar via `jupyter nbconvert --execute`. Cels: imports → data load (calls/sales/gps) → 5 viz-cellen → observatie-markdown.
- 5 figuren naar [reports/figures/](reports/figures/):
  - [eda_calls_heatmap.png](reports/figures/eda_calls_heatmap.png) — calls per uur × top-12 zipcodes
  - [eda_calls_map.png](reports/figures/eda_calls_map.png) — geografische scatter, beantwoord (blauw) vs onbeantwoord (rood)
  - [eda_velocity_per_van.png](reports/figures/eda_velocity_per_van.png) — 3×3 grid snelheid-histograms top-9 actieve karren
  - [eda_sales_per_daytype.png](reports/figures/eda_sales_per_daytype.png) — sales per uur per dag-type + omzet-totaal
  - [eda_demand_supply_gap.png](reports/figures/eda_demand_supply_gap.png) — gestapelde bar beantwoord/onbeantwoord per dag-type (extra)
- 5 concrete observaties opgesteld voor het Data-deel van de fiche (zie eind notebook).

**Vlot**
- Alle viz-code numeriek consistent met losse sanity-cijfers (vooraf in shell gecheckt → identiek aan notebook output).
- nbconvert --execute draait de hele notebook in <1min; geen handmatige cells uit te voeren.
- Velocity-histograms tonen visueel direct de "factor 5" snelheidsverschillen tussen karren — niet alleen mediaan-cijfers maar volledige distributie zichtbaar (kar 13 sterk gepiekt rond 1-2 m/s ≈ wandelend; kar 103 veel vlakker met staart tot 25 m/s ≈ regionaal).
- Bonus-vondst tijdens schrijven: holiday-sales pieken om 13u (174 sales/uur), weekday om 14u, weekend om 12u — een verschuivende piek-uur per dag-type, mogelijk relevant voor voorraad-modellering.

**Problemen**
- `Path.cwd()` in een notebook zit op de notebook-directory bij nbconvert-execute. Loaders verwachten cwd=projectroot. Opgelost met een conditionele `os.chdir()` in cel 1.
- Eerste versie observaties haalde "kar 13" als traagst aan op basis van top-9-by-volume; werkelijke globale traagste is kar 1 (1.5 m/s). Cel achteraf gecorrigeerd.

**Observaties uitgelicht** (voor fiche)
1. **Vraag-aanbod-gap piekt op feestdag** — 80% van 968 calls op 1 mei onbeantwoord (vs 60% weekday, 69% weekend) bij identieke fleet.
2. **Sales-piek (~13-14u) ≠ calls-piek (~17u)** — avondvraag wordt niet door spontaan langsrijden opgevangen.
3. **Karren rijden factor 5 verschillend** — mediaan 1.5 m/s (kar 1) tot 7.1 m/s (kar 103); suggereert lokale vs regionale routes.
4. **+71% omzet op feestdag** — €12.948 vs €7.572 op 30/4 met dezelfde 15 karren.
5. **45% van vraag in 5 zipcodes** (9160, 9240, 9100, 9200, 2880) — beperkt aantal H3-zones zal modellering domineren.
