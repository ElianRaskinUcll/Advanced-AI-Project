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

---

## Issue 1.6 — Tabular feature-set voor forecasting model

**Wat gedaan**
- [src/features/build_features.py](src/features/build_features.py) met `build_features()`, `_aggregate_demand()` en `leave_one_day_out_splits()` als CV-helper.
- Granulariteit: H3 cell (resolutie 9, gekozen in issue 1.3) × hourly timestamp.
- Target: `demand = n_sales + n_calls` per (zone, hour).
- Features: `hour`, `day_type` (uit context.parquet), weather (`temperature`, `precipitation`, `sunshine`), lag features (`demand_lag_1`, `demand_lag_2`), `demand_rolling_3h` (rolling mean over [t-3, t-1]), zone-encoding (`zone_lat`, `zone_lng` van H3-centroid).
- Carthesisch product van 911 zones × 72 uren = **65.592 rijen × 17 kolommen** in [data/processed/features.parquet](data/processed/features.parquet).
- `fold`-kolom (0/1/2) maps elke datum naar een leave-one-day-out fold; helper `leave_one_day_out_splits()` levert `(train_idx, test_idx)` paren.

**Vlot**
- Target-totaal sanity: 3.985 = exact 2.219 sales + 1.766 calls — niets verloren in aggregation.
- DoD-verificatie via expliciete script: `demand_lag_1`, `demand_lag_2` en `demand_rolling_3h` cel-voor-cel vergeleken met re-derivation uit raw demand → 100% match. Static features (zone_lat/lng) constant per cel. Geen NaNs.
- Pipeline draait warning-vrij in ~3s.

**Problemen — geen blockers**
- 911 zones is meer dan de 575 in zones.geojson omdat calls H3-cellen kunnen raken die niet in stops/sales voorkwamen. Voor het model is dat juist nuttig (ook zones met enkel calls hebben future demand). Zones.geojson kan eventueel later uitgebreid worden, maar dat is geen blokker hier.
- Sparse target: 2.214 / 65.592 rijen (3.4%) hebben demand > 0. Normaal voor spatial-temporal forecasting; modellen moeten kunnen omgaan met veel nullen.

**Open punt voor later (subtle CV-leakage, geen DoD-issue)**
- Lag features kruisen dag-grenzen: bv. `demand_lag_1` voor 1 mei 00:00 = demand 30 apr 23:00. Bij leave-one-day-out CV op fold 0 (test = 30 apr) zit die 30-apr demand nog steeds in lags voor 1 mei (train) — strikt correct in de tijd, maar het CV-fold krijgt indirect informatie over de test-set via lags. Voor feature-leakage in DoD-zin (`geen toekomstige info`) is dat geen probleem — alle features kijken naar het verleden. Voor nette CV-evaluatie kan men lag-features per fold opnieuw berekenen of de eerste 2 uur van elke train-dag droppen. Documenteren in modeling-issue.

---

## Issue 1.7 — XGBoost forecasting baseline

**Wat gedaan**
- [src/models/xgb_forecast.py](src/models/xgb_forecast.py) met `train()`, `predict()`, `_cross_validate()`, `evaluate_per_day()`, `evaluate_per_zone_bucket()`, `plot_shap()`, `save_artifact()`.
- Optuna TPE sampler, 30 trials, search over `max_depth` (3-10), `learning_rate` (0.01-0.3 log), `n_estimators` (100-500), `subsample` (0.5-1), `colsample_bytree` (0.5-1). Objective: leave-one-day-out OOF MAE.
- Final model retrained op alle data met best params, gepickled in [models/xgb_v1.pkl](models/xgb_v1.pkl) samen met feature-names, params, en CV-results.
- SHAP `TreeExplainer` op steekproef van 5000 rijen → beeswarm summary plot in [reports/figures/shap_xgb_v1.png](reports/figures/shap_xgb_v1.png).
- `xgboost`, `optuna`, `shap` toegevoegd aan requirements.

**Resultaten — DoD ✅**

Best CV MAE (Optuna): **0.0608**. Best params: `max_depth=3, lr=0.077, n_estimators=101, subsample=0.95, colsample_bytree=0.68` — kleine boom, beperkt aantal trees. Past bij de schaarse target en de beperkte 3-dagen dataset.

| Held-out dag | n_test | MAE | RMSE |
|---|---:|---:|---:|
| 30 apr (weekday) | 21.864 | 0.045 | 0.418 |
| 1 mei (holiday) | 21.864 | **0.090** | 0.610 |
| 2 mei (weekend) | 21.864 | 0.048 | 0.389 |

| Zone-bucket | n_zones | total_demand | MAE | RMSE |
|---|---:|---:|---:|---:|
| low (laagste 1/3) | 304 | 321 | 0.015 | 0.122 |
| mid | 303 | 796 | 0.036 | 0.238 |
| **high (hoogste 1/3)** | **304** | **2.868** | **0.131** | **0.791** |

**Vlot**
- Pipeline draait end-to-end in ~3 min (30 trials × 3 folds = 90 fits).
- SHAP plot toont `demand_lag_1` als overheersende feature — autocorrelatie domineert bij 3 dagen training-data, wat zinvol is.
- Model laadt correct terug via pickle; `predict()` op verse rijen geeft consistente uitvoer.

**Problemen — geen blockers, wel inzichten**
- **Holiday-dag is de moeilijkste**: MAE 0.090 op 1 mei is 2× zo hoog als op weekday/weekend. Logisch — het volume op die dag is een outlier en bij leave-one-day-out heeft het model die verdeling niet gezien. Bij meer dagen training-data zou dit verbeteren.
- **High-demand zones zijn het moeilijkste**: MAE 0.131 vs 0.015 voor low-buckets. Dit is naturlijk proportioneel: high-demand zones hebben grotere variantie. Voor evaluatie in business-zin is dit de bucket die telt.
- **MAE in absolute termen lijkt laag** (0.06) maar dat komt door target-sparsity: 96.6% van rijen heeft demand=0. Voor de high-demand bucket — waar het er echt toe doet — is MAE 0.13. Dat moet in de fiche genuanceerd worden.

**Open punt voor latere modeling-issue**
- Lag-leakage uit feature-issue (1.6): bij strikte CV-evaluatie zouden lag-features per fold herberekend moeten worden zodat 30 apr's demand niet via lags in 1 mei's train-features doorlekt. Voor deze baseline acceptabel; dien voor productie-evaluatie.

---

## Issue 1.8 — Transformer sequence model

**Wat gedaan**
- [src/models/transformer_forecast.py](src/models/transformer_forecast.py) met PyTorch implementatie:
  - `PositionalEncoding` (sinusoïdaal, max_len 32)
  - Custom `EncoderLayer` (MultiheadAttention met `batch_first=True`, `need_weights=True` opt-in voor attention-export, LayerNorm, GELU FF)
  - `TransformerForecast` model: `Linear(10→32) → PosEnc → 2× EncoderLayer (4 heads, FF 64) → Linear(32→1)` op de laatste timestep
- Sequence-build: per (zone, t≥6) sliding-window van 6 uur features per zone via `np.lib.stride_tricks.sliding_window_view`. Resultaat: **60.126 sequences** van vorm (6, 10).
- Per-timestep features (10): hour, temperature, precipitation, sunshine, zone_lat, zone_lng, demand (past), day_type one-hot (3).
- StandardScaler per fold (fit op train), early stopping op val MAE (patience 5), Adam(lr=1e-3), MSE loss, batch 256.
- LODO eval (3 folds), final model retrained op alle data, attention plot van eerste sequence in test-set, alles gepickled in [models/transformer_v1.pt](models/transformer_v1.pt) met scaler-stats.
- Outputs: [reports/figures/transformer_loss_curves.png](reports/figures/transformer_loss_curves.png), [reports/figures/transformer_attention.png](reports/figures/transformer_attention.png).
- `torch` toegevoegd aan requirements (CPU-build).

**Resultaten**

| Held-out dag | n_test | epochs | MAE | RMSE | XGB MAE |
|---|---:|---:|---:|---:|---:|
| 30 apr (weekday) | 16.398 | 9 | 0.100 | 0.471 | 0.045 |
| 1 mei (holiday) | 21.864 | 7 | 0.130 | 0.581 | 0.090 |
| 2 mei (weekend) | 21.864 | 6 | 0.095 | 0.374 | 0.048 |

| Zone-bucket | MAE Transformer | MAE XGBoost |
|---|---:|---:|
| low | 0.060 | 0.015 |
| mid | 0.083 | 0.036 |
| high | 0.184 | 0.131 |

**DoD checks**
- ✅ **Training convergeert** — early stopping triggert na 6-9 epochs in elke fold. Loss curves tonen daling en plateau (zie figuur). Eerlijke kanttekening: de daling is klein in absolute termen (~5-10% van starting loss), wat erop wijst dat het model snel naar een quasi-constant predictiepatroon convergeert.
- ✅ **MAE rapporteerbaar** — per fold + per zone-bucket (tabel hierboven).
- ✅ **Attention weights visualiseerbaar** — 2 layers × 4 heads × 6×6 attention matrices voor eerste sequence in test-set. Zichtbaar patroon: laatste timestep (t-1) krijgt sterke aandacht in head 4 van layer 2 (autoregressieve afhankelijkheid).

**Vlot**
- Sequence-build via stride_tricks is razendsnel (60k windows in <1s).
- Attention export via custom encoder layer (`need_weights=True`) werkte direct; PyTorch's standaard `nn.TransformerEncoderLayer` gooit de attention weg.
- Pipeline volledig op CPU in ~3 min (klein model, beperkte data).

**Problemen — Windows DLL bug**
- `import torch` faalde met `WinError 1114: DLL initialization routine failed` wanneer `pandas` eerder werd geïmporteerd. Reproduceerbaar: `python -c "import pandas; import torch"` faalt; `python -c "import torch; import pandas"` werkt. Vermoedelijk MKL-conflict tussen pandas' vendored libs en torch's native libs op deze Windows-installatie. **Fix:** `import torch` als allereerste in de module, vóór andere wetenschappelijke imports. Comment toegevoegd in de file.
- Bash (Git Bash MINGW) heeft een ander DLL-search-path en faalt zelfs bij directe `python -c "import torch"`. PowerShell werkt. Voor reproduceerbaarheid: pipeline draaien via `pwsh -c "python -m src.models.transformer_forecast"` of via een Makefile-target dat PowerShell-aware is.

**Inzicht voor de fiche (Challenges)**
- **XGBoost slaat de Transformer op alle metrieken**: weekday 0.045 vs 0.100 (Transformer is 2× slechter), high-bucket 0.131 vs 0.184. Dit is een ECHTE bevinding voor het rapport, niet een fout. Met slechts 3 dagen data en een schaarse target (96% zeros) is het signaal te zwak voor een sequence-model om er voordeel uit te halen — autocorrelatie via XGBoost-lag-features volstaat. Transformer-architectuur shines pas bij langere histories en/of multi-zone interacties (cross-attention), wat hier afwezig is.
- **Plateauing zonder echte daling** in fold 0/2 train-loss bevestigt: het model parkeert snel op een near-constant predictie. Dit is geen falen van de implementatie, maar van het model-data fit. Voor de fiche: framing als "advanced architecture toegevoegd voor Technical Depth, vergelijking laat zien dat baseline XGBoost optimaal is voor deze data-schaal — sequence-model zou shine bij langere historie".

**Open punt voor later**
- Met meer dagen data (>14) zou de Transformer waarschijnlijk competitief worden. Niet relevant voor deze 3-dagen export, maar wel voor productie waar continu data binnenkomt.

---

## Issue 2.4 — Forecast model comparison + simulator-keuze

**Wat gedaan**
- [notebooks/03_forecast_comparison.ipynb](notebooks/03_forecast_comparison.ipynb) draait end-to-end via nbconvert.
- 3 modellen vergeleken op gemeenschappelijke 60.126-rij subset (t≥6 per zone): naïef (lag-1), XGBoost, Transformer.
- LODO OOF predicties opnieuw berekend voor alle 3 modellen (XGBoost herbruikt Optuna best_params, Transformer hertraint per fold).
- MAE/RMSE-tabel per fold + per zone-bucket.
- [reports/figures/forecast_comparison_1mei.png](reports/figures/forecast_comparison_1mei.png) — voorspelling vs werkelijkheid voor 1 mei (held-out feestdag), aggregaat per uur over alle zones.

**Vlot**
- Notebook draait in ~3 min (XGBoost CV ~20s, Transformer CV ~2 min, plot/tabellen instant).
- Importpattern (torch eerst) consistent met issue 1.8 toegepast.
- Comparison op gemeenschappelijke subset eerlijk: alle 3 modellen voorspellen op identieke (zone, uur)-paren.

**KRITIEKE BEVINDING — XGBoost is degeneraat**

De per-rij MAE-cijfers suggereren XGBoost wint duidelijk:

| Fold | naive | XGBoost | Transformer |
|---|---:|---:|---:|
| 30/4 weekday | 0.097 | **0.060** | 0.100 |
| 1/5 holiday | 0.134 | **0.090** | 0.130 |
| 2/5 weekend | 0.075 | **0.048** | 0.095 |

Maar de plot van 1 mei laat zien dat **XGBoost voorspelt vlak rond 0** voor de hele dag — terwijl de actual demand tussen 12u-18u rond 270 piekt. Verificatie: XGBoost's MAE per zone-bucket komt **drie decimalen overeen** met `mean(demand)` per bucket (low 0.0160 = 321/20064, mid 0.0398 = 796/19998, high 0.1429 = 2868/20064). Een model dat altijd 0 predict heeft per definitie `MAE = mean(|y|)` — dus XGBoost predict effectief constante 0.

**Oorzaak**: `objective=reg:absoluteerror` op een target die voor 96% nullen is → MAE-optimaal predict de mediaan, en dat is 0. XGBoost heeft wiskundig precies gedaan wat we vroegen, maar dat is operationeel useless.

**Beslissing — Transformer drijft de simulator aan**

Ondanks de hogere per-rij MAE (0.109 overall vs XGBoost 0.066) wint de Transformer voor het simulator-doel:
- **Geeft non-triviale, shape-correcte voorspellingen.** Op 1 mei volgt de Transformer de daily curve (piek 13u, dal 15u, tweede piek 18u). Magnitude-onderschat (~50%), maar de vorm is er.
- **Schaalt mee bij meer data.** Sequence-modellen leren wekelijkse patronen die boosted trees missen.

**Simulator-implicatie**: issue 2.6+ laadt `models/transformer_v1.pt`. `xgb_v1.pkl` blijft bewaard als referentie/anti-pattern voor het rapport.

**Open punten voor latere modeling-issues**
- Magnitude-onderschatting (~50% piek) → kalibratie of log-target retrain.
- XGBoost retrainen met `objective=reg:squarederror` of log-target zou de degenereerheid verhelpen — open issue.
- Per-rij MAE is geen goede metric voor sparse forecasting; introduceer shape-aware metric (dynamic time warping, sum-correlation) — open issue.

**Inzicht voor de fiche (Challenges-faced)**
> "Initial XGBoost baseline tuned for MAE on 96%-sparse demand collapsed to predicting the median (0) — mathematically MAE-optimal but operationally useless. Per-bucket MAE matched mean(demand) to 3 decimals, confirming the model never produced non-trivial outputs. Switched simulator backend to the Transformer despite its higher per-row MAE (0.109 vs 0.066), because it produces shape-correct demand curves on aggregate. Open: retrain XGBoost with squared-error objective + introduce shape-aware validation metric."

Dit is letterlijk een textbook-Challenge: per-row MAE was de verkeerde metric, en pas de aggregaat-plot onthulde de degeneratie.

---

## Issue 3.1 — Environment skeleton

**Wat gedaan**
- [src/env/dispatcher_env.py](src/env/dispatcher_env.py) met `DispatcherEnv(gymnasium.Env)`: `reset()`, `step()`, `observation_space` (Box, 31 floats), `action_space` (`MultiDiscrete([n_zones]*n_vans)` = 15 × 575).
- `__main__` draait een volledige dag uit met een random agent: 66 steps van 10 min = 11 uur (10:00→21:00 UTC), geen crash, totaal_reward = 0 (placeholder).
- `gymnasium.utils.env_checker.check_env()` slaagt → API-contract correct.
- `gymnasium` toegevoegd aan requirements.

**Tijdstap-keuze: 10 minuten**
- Realistisch voor inter-zone-rijden (5-10 min stadsverkeer per zone-wissel).
- 11-uurs operating window → 66 steps/episode: kort genoeg voor snelle RL-iteratie.
- Hourly forecast features (uit issue 1.6) zijn binnen één step constant → eenvoudige join.

**Skeleton scope (deze issue)**
- Observation: `[zones_per_van (15), busy_flag_per_van (15), hour_of_day (1)]` = 31 floats. **Placeholder** — issue 3.2 breidt uit met weather, day_type en demand-forecast.
- Action: per van een doelzone (0..n_zones-1). Vrije vans verplaatsen instant naar doel; busy vans negeren de actie.
- Reward = 0 (vast). Issue 3.3+ definieert de reward-functie.
- Operating window 10:00-21:00 UTC; einde-dag termineert het episode.

**Vlot**
- Strakke separatie tussen "skeleton-geldig" (deze issue) en "rijke state/reward" (volgende issues) maakt het mogelijk de Gym-API-validatie nu al groen te krijgen zonder de simulatielogica vooraf te vergrendelen.
- `env_checker` validatie als compact DoD-bewijs bovenop de "random agent runt een dag" check.

**Problemen — geen.**

**Open punten voor volgende issues**
- 3.2: state vector uitbreiden met weather, day_type, demand-forecast per top-N zones.
- 3.3: reward-functie (waarschijnlijk: served_demand − travel_cost − missed_calls_penalty).
- Travel-tijd modelering (vans zijn nu instant verplaatsbaar; in productie 5-10 min reistijd op basis van stops.parquet of GPS-snelheid).
- Busy-state logica: hoe lang blijft een kar busy nadat hij verkocht? Issue 3.2/3.3.

---

## Issue 3.2 — State, action, reward design (MDP-spec)

**Wat gedaan**
- [docs/mdp_spec.md](docs/mdp_spec.md) — één-pagina spec (59 regels) met:
  - **State** (177 floats): `current_hour, day_type[3], weather[3], vans_state[4·15], pending_calls[3·20], zone_demand_forecast[50]`. Defaults gepind: N=15, K=20, Z=50.
  - **Action** per kar: zone-index of `STAY = n_zones`. `MultiDiscrete([n_zones+1] * N)`. Busy-vans negeren actie.
  - **Reward** = `+1·answered_call + α·revenue − β·distance − γ·unanswered_call`.
  - α / β / γ gemotiveerd op basis van EDA-cijfers.

**Concrete reward-parameters**

| Param | Waarde | Korte motivatie |
|---|---:|---|
| α | 0.10 | Gemiddelde sale €14 (€31k / 2.219 sales) → α=0.1 levert +1.4 reward bovenop de +1 voor answered_call. Sale-grootte weegt mee zonder te overschaduwen. |
| β | 0.10 | 5km rijden ≈ −0.5 reward (≈ 20% van een sale). Ontmoedigt willekeurig kruisen, beboet niet noodzakelijk verplaatsen. |
| γ | 2.00 | 80% miss-rate op feestdag = grootste pijn. γ=2 maakt missen kostbaarder dan de +2.4 winst van een answered+sale → agent leert calls te prioriteren. |

**Concrete swing**: call beantwoorden vs missen = ~+4.4 reward swing. 5km rijden naar die call (−0.5) blijft ruim winstgevend (+1.9 netto).

**Vlot**
- α/β/γ gepind op concrete data-cijfers uit eerdere issues (gem. sale-waarde uit EDA, miss-rate van issue 1.5) → defenseable in fiche.
- `estimated_revenue` lookup-strategie genoteerd: `mean_sale_value_per_zone` op basis van de 3-dagen historiek.
- Termination/truncation expliciet vastgelegd (terminated bij 21:00 UTC, geen truncation).

**Problemen — geen.** Zuivere documentatie-issue.

**Open (latere issues)**
- 3.3+ moet de spec implementeren in `DispatcherEnv` (state-uitbreiding, action `STAY`, reward-functie, travel-tijd via `distance_km / 25 km/u`).
- α/β/γ zijn een eerste pin; reward-shaping experimenten kunnen ze tunen.
