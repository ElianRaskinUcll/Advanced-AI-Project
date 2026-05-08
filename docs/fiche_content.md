# Fiche content dump — ruwe input

Bullet-lists per sectie. Cijfers en bronnen direct overneembaar in de technische fiche. Items met `<TODO>` zijn user-input die ik niet kan invullen.

---

## 1. Introduction

### Problem statement
- Foubert IJs (regio Bornem) heeft een fleet van 13-15 ijswagens per dag. In een 3-dagen export ziet men dat **vraag-aanbod-mismatch structureel is**:
  - 30 april 2026 (donderdag, weekday): **60% miss-rate** (217/363 calls onbeantwoord)
  - 1 mei 2026 (vrijdag, Dag van de Arbeid): **80% miss-rate** (778/968 calls onbeantwoord)
  - 2 mei 2026 (zaterdag, weekend): **69% miss-rate** (302/435 calls onbeantwoord)
- Op 1 mei was de vraag bijna 3× zo hoog als op een werkdag, met dezelfde fleet → grote verkoopkansen liggen liggen.

### Motivation
- Ice-cream-truck dispatching is een klassiek vehicle-routing-probleem, maar met **stochastische demand** die afhangt van weer, dag-type en wijk-typering.
- Gerichte zone-allocatie zou de miss-rate kunnen verlagen zonder fleet-uitbreiding (= goedkopere oplossing dan extra karren kopen).
- Project-doel: een end-to-end systeem bouwen dat (a) demand voorspelt per zone+uur, (b) een simulator-omgeving biedt voor policy-testen, en (c) RL-agents traint die niet-getrainde baselines overtreffen.

### Chosen approach (1 zin)
- Forecast demand per (H3-zone, uur) met XGBoost + Transformer, valideer in een Gymnasium-simulator gevoed door dat forecast, train tabular Q-learning + DQN met macro-acties, vergelijk eerlijk tegen random/greedy/historical baselines.

### Repo link
- `<TODO: GitHub URL invullen>`

---

## 2. Data

### Foubert dataset omvang
- **Bron**: Foubert IJs productie-database (`icecorpapi_productiondb`), export van 3 mei 2026.
- **Periode**: 3 opeenvolgende dagen — 30 april (do, baseline), 1 mei (vr feestdag), 2 mei (za weekend) 2026, telkens 00:00–23:59 UTC.
- **Omvang**: ~697.000 rijen verdeeld over 130 TSV-bestanden:
  - 7 hoofd-tabellen per dag: shifts (88), sales (2.219), sale_orders (7.273), menu_items (170), reservations (38), calls (1.766), vans (44)
  - GPS-tracking per kar (~5s sampling): 686.224 punten
- **Karren**: 15 actief op 30/4 en 1/5, 13 op 2/5 (ID's 5, 6, 8, 9, 10, 11, 13, 14, 15, 34, 35, 101, 102, 103).
- **Externe weer-data**: Open-Meteo Archive API, hourly temperature (°C), precipitation (mm), sunshine_duration (s/u) voor coordinates 51.10°N, 4.24°E (Bornem). 72 uren → 0 NaN, plausibele dag/nacht-cyclus 8-9°C → 22-24°C.

### Preprocessing stappen
- **Joins** (`src/data/load.py`):
  - sales + shifts (zone via shift_id)
  - sale_orders → sales → shifts
  - calls + answered-flag (`answered = shift_id.notna()`)
  - GPS per kar (geconcateneerd over 3 dagen + 30 vans)
- **Stop-detectie** (`src/zones.py`):
  - Filter GPS op velocity < 0.5 m/s (5.213/686.268 punten = 0.76%)
  - DBSCAN met haversine metric, eps=50m, **min_samples=2** (afgeweken van issue's 10)
  - 586 stop-clusters, 63.9% sales-coupling
- **Zone-grid**: H3 hexagons resolutie 9 (~150m edge). 911 zones met activiteit. Niet `area_id`/`zone_id` uit shifts (operationeel, niet ruimtelijk indexeerbaar).
- **Feature engineering** (`src/features/build_features.py`):
  - 65.592 rijen × 17 kolommen (911 zones × 72 uren)
  - Target: `demand = n_sales + n_calls` per (zone, uur)
  - Features: `hour`, `day_type` (one-hot 3), weather (3), `demand_lag_1`, `demand_lag_2`, `demand_rolling_3h` (rolling mean over [t-3, t-1]), `zone_lat`, `zone_lng` (H3-centroid)
  - **Geen leakage**: lag-features gebruiken strikt `shift(1)`/`shift(2)` per zone, geverifieerd via cell-by-cell re-derivation.
- **Calendar enrichment** (`src/context.py`): Belgische feestdagen 2026 (10 stuks) hardgecodeerd, `day_type` = holiday/weekend/weekday categoriaal.

### Challenges (data)
- **Privacy-strip**: alle PII verwijderd uit export — geen klantnamen/emails/telefoons/adressen, geen device-fingerprints, geen kar-namen. Locatie-precisie verlaagd: sales lat/lng op 4 decimalen (~10m), calls/reservations op 3 decimalen (~110m). GPS van karren behouden op 6 decimalen want vans rijden op publieke weg.
- **Geen klant-link tussen calls**: één klant die meerdere keren belt is bewust niet identificeerbaar in de export → **geen klant-segmentatie mogelijk**, alleen aggregaten.
- **3 dagen klein**: forceert leave-one-day-out CV met 3 folds, beperkt sequence-modellen (Transformer), maakt elke held-out dag kwetsbaar voor distributie-shift.
- **Vuile zipcode**: één rij in `2026-05-01/07_calls.tsv` had literal U+FFFD (`"924�"`) als address_zipcode. Tolerant ingelezen via `pd.to_numeric(errors='coerce')` zodat één rij naar `<NA>` ging zonder de hele load te breken.
- **macOS metadata in initial commit**: `._*` AppleDouble files zaten in raw export. Gefilterd via `.gitignore` na move naar `data/raw/foubertai_export/`.

---

## 3. Model & Methods

### Forecasting

**XGBoost** (`src/models/xgb_forecast.py`)
- Optuna TPE sampler, 30 trials, search over `max_depth` (3-10), `learning_rate` (0.01-0.3 log), `n_estimators` (100-500), `subsample` (0.5-1), `colsample_bytree` (0.5-1).
- Best params: `max_depth=3, lr=0.077, n_estimators=101, subsample=0.95, colsample_bytree=0.68`.
- Objective: MAE (`reg:absoluteerror`).
- Per-fold MAE: **0.045 (weekday) / 0.090 (holiday) / 0.048 (weekend)**.
- SHAP TreeExplainer toonde `demand_lag_1` als overheersende feature.

**Transformer** (`src/models/transformer_forecast.py`)
- Architectuur: `Linear(10 → 32) → SinusoidalPosEnc → 2× EncoderLayer (4 heads, FF dim 64, dropout 0.1) → Linear(32 → 1)` op de laatste timestep.
- Custom EncoderLayer voor attention-export (pytorch's standaard layer gooit attention weg).
- Input: 6-uur sliding window per zone (10 features per timestep).
- Training: Adam (lr=1e-3), MSE loss, batch 256, max 50 epochs, early stopping op val MAE (patience 5, val 10%).
- Per-fold MAE: 0.100 / 0.130 / 0.095. **Geen winst over XGBoost** ondanks meer parameters — sequence-modellen lijden onder 3-dagen-data.

**Cross-validatie**
- Leave-one-day-out (3 folds), expliciet gekozen omdat dag-grenzen de natuurlijke distributie-shift-unit zijn.

**Forecast comparison + decision** (notebook 02)
- Naïef baseline (`demand[t-1]`) overall MAE: 0.102.
- XGBoost: overall MAE 0.066 — laagste, **maar predict effectief constant 0**. Per-bucket MAE matched `mean(demand)` per bucket tot 3 decimalen (low: 0.0160 = 321/20064, etc) — wiskundig correct (MAE-optimaal predict de mediaan, mediaan = 0 op sparse target), operationeel useless.
- Transformer: overall MAE 0.109 — slechtst per-row, **maar shape-correct** (volgt daily curve op 1 mei: piek 13u, dal 15u, tweede piek 18u; magnitude undershoot ~50%).
- **Beslissing: Transformer drijft de simulator aan.** XGBoost ondanks beste MAE niet bruikbaar; naïef vereist ground-truth lag-1 dat in productie niet beschikbaar is.

### Simulation environment (`src/env/dispatcher_env.py`)

**Setup**
- Gymnasium-compatible (`gymnasium.utils.env_checker.check_env()` slaagt).
- Tijdstap: 10 minuten (motivatie: realistisch inter-zone rijden in stadsverkeer; 11u operating window 10:00-21:00 UTC = 66 steps/dag).
- 911 zones × 15 vans.

**State** (31 floats)
- Per van: `[zone_idx, busy_flag]` (×15)
- Globaal: `hour_of_day` (1)
- Skeleton — full MDP-spec state (pending_calls, weather, day_type, demand_forecast_top_50) is gedocumenteerd in `docs/mdp_spec.md` maar niet geïmplementeerd.

**Action**
- `MultiDiscrete([n_zones] * n_vans) = MultiDiscrete([911] * 15)` ≈ 10⁴⁵ unieke acties.
- Vrije vans verplaatsen instant naar doelzone; busy vans negeren actie (geen busy-state in skeleton).

**Reward**
- Returnt `0.0` (placeholder). Agents berekenen reward in hun eigen training-loop als `Δ n_total_sales` per step.
- Volledige MDP-spec reward (`+1·answered + α·revenue − β·distance − γ·unanswered` met α=0.10, β=0.10, γ=2.00) gedocumenteerd in `docs/mdp_spec.md`. Niet geïmplementeerd — open punt.

**Demand simulation**
- Forecast 1× per dag gecached in `reset()` (geen per-step model-call).
- **Calls** sampling: per (zone, uur), Poisson met λ = `forecast × call_fraction × slice_fraction` waar `call_fraction = total_calls / (total_calls + total_sales) ≈ 0.443` empirisch.
- **Sales** sampling: alleen in zones met ≥1 vrije van. Per-van Poisson met 2-ring H3 pooling (cell + 18 neighbors ≈ 750m diameter). Pooling absorbeert GPS-quantisatie en modelleert "een van bedient een gebied van een paar straten".
- `nr_of_people` per call: empirische distributie uit historische calls (categorieën `1-2`, `3-4`, …, `10+`).

**Validatie via replay** (notebook 03)
- DoD ±20% niet gehaald op sales (-48% vs historisch). Calls wel binnen ±20% (+11%).
- Iteraties met afnemend rendement: GPS replay → +pooling → +stops fallback → 2-ring; van -84% naar -48%. Verder uitbreiden niet fysiek verdedigbaar.
- **5.8× replay/random discriminator-ratio** voor sales — simulator onderscheidt informed vs willekeurige acties.
- Geaccepteerd als ondergrens; geen calibratie-scale toegepast (zou DoD via hack halen zonder bottleneck te verhelpen).
- Open punten: HDBSCAN voor quick-stops, H3 resolutie 8 voor minder GPS-jitter.

### RL agents (`src/agents/`)

**Random / Greedy / Historical** (issue 4.1)
- Random: `action_space.sample()`.
- Greedy: voor elke open call (≤30 min oud), stuur dichtstbijzijnde vrije van (haversine op H3-centroid).
- Historical: replay actuele GPS-trajecten via stops-fallback action-builder.

**Tabular Q-learning** (issue 4.2)
- 12 discrete states: `hour_bin (4) × open_calls_bin (3)`.
- 4 macro-acties: `stay / greedy / forecast_top / random` — hierarchical RL via macros (raw action space ≈ 10⁴⁵ untabulariseerbaar).
- α=0.3, γ=0.95, ε=1.0→0.05 decay 0.94/episode.
- Trained: 60 episodes × 2 dagen (30/4 + 1/5), test op 2/5.
- Single-test result: 140 sales (vs random 56, +150%).

**DQN** (issue 4.3)
- Q-net: 31 → 64 → 64 → 4 (ReLU activations).
- Target net (sync per 200 env-steps), replay buffer (10k cap, 500 warmup).
- Adam lr=1e-3, γ=0.95, batch 64, ε=1.0→0.05 lineair decay over 200 episodes, gradient clipping (max norm 5).
- 500 episodes (issue noemde 2000, plateau bereikt veel eerder voor 4-macro action space).
- Single-test result: 163 sales — leek beter dan Q-learning maar single-seed bevooroordeeld, multi-seed gaf andere ranking.

### Key hyperparameters (overzicht)

| Component | Hyperparameter | Waarde |
|---|---|---|
| XGBoost | objective | `reg:absoluteerror` |
| | max_depth | 3 |
| | learning_rate | 0.077 |
| | n_estimators | 101 |
| Transformer | d_model / heads / ff_dim / layers | 32 / 4 / 64 / 2 |
| | sequence length | 6 hours |
| | batch / lr / epochs | 256 / 1e-3 / 50 max + early stop (5) |
| Q-learning | states × macros | 12 × 4 |
| | α / γ | 0.3 / 0.95 |
| | episodes | 60 |
| DQN | hidden / replay / batch | (64, 64) / 10k / 64 |
| | target update / γ | 200 steps / 0.95 |
| | episodes | 500 |
| Reward weights (MDP-spec) | α / β / γ | 0.10 / 0.10 / 2.00 |

### Streamlit demo app
- **Niet geïmplementeerd in deze cyclus.** Ingepland voor latere issue (6.2 was bewuste-keuze-deferred per scope-decision). Stub-architectuur: forecast service + env + agents zijn modulair genoeg om snel een Streamlit-frontend bovenop te bouwen.
- `<TODO: vermelden in fiche of laten staan als "future work">`

---

## 4. Results & Evaluation

### Key tabel (agent × metric, mean over 3 dagen × 5 seeds — uit `results/eval_summary.csv`)

| Agent | % answered | Revenue (€) | Distance (km) | Response (min) | Fairness Gini | Neglected zones |
|---|---:|---:|---:|---:|---:|---:|
| **q_learning** | **30.6** | **2.765** | 1.947 | 57 | 0.17 | **1.9 %** |
| dqn | 28.1 | 2.603 | 3.703 | 78 | 0.19 | 3.6 % |
| historical | 20.4 | 1.659 | 4.766 | 122 | 0.20 | 9.0 % |
| greedy | 19.5 | 1.575 | **1.121** | **22** | **0.15** | 2.3 % |
| random | 14.7 | 1.085 | 12.677 | 149 | 0.18 | 22.1 % |

### Hero plots
- **fig1_pct_answered.png**: bar chart van % calls answered per agent met error bars (5 seeds). Q-learning leidt op 30.6%, random ondergrens 14.7%. Error bars klein → robuust over seeds.
- **fig4_reward_curves.png**: Q-learning training (60 episodes, plateau ~220 sales na ~25 episodes) + DQN training (500 episodes, zelfde niveau ~ep 200). Horizontale baseline-lijnen voor random/greedy/historical onderaan; getrainde agents domineren.
- Optionele extra: **fig2_coverage_heatmap.png** (agent presence vs actuele demand) bewijst dat de Q-policy geen random ronddraait — overlapt met demand-pieken op 12-19u.
- Optionele extra: **fig3_van_movements.png** (lat/lng-trajecten + zone-wissel-strip) toont vans clusteren rond Bornem in een ~30km radius.

### Key insights (in volgorde van belangrijkheid)

1. **Forecast-kwaliteit is dé hefboom (niet de agent-architectuur).** Ablation toonde: DQN met **oracle-forecast = +196%** sales over DQN met de geleerde Transformer-forecast (per dag: +203/+173/+239%). De Transformer-magnitude-undershoot uit het forecast-stadium limiteert alle agents harder dan welke RL-tweak ook.

2. **Tabular Q ≥ DQN op deze MDP** (200.8 vs 187.1 mean answered_calls, multi-seed). Function approximation is overkill bij 4 macro-acties — een 12-state tabel volstaat. Single-seed-result (DQN > Q) zat binnen seed-noise.

3. **Trade-off response-time vs total-sales**: greedy chase't individuele calls (23 min response, 115 sales) — RL pool't demand (52-75 min response, 187-201 sales). Voor totaal-omzet is RL beter, voor klantervaring per individuele call is greedy beter.

4. **Q-learning verdrievoudigt sales over random** (200.8 vs 76.3) en houdt de neglected-zones-percentage onder 2% — vans skippen nauwelijks demand-zones.

### App screenshots
- **N/A** — Streamlit-app niet geïmplementeerd. Bij eventuele app-bouw zou een screenshot van de "agent comparison"-pagina hier staan.

---

## 5. Contributions

### Wie deed wat
- `<TODO: solo of met partner? Indien partner, naam + verdeling invullen>`
- `<TODO: indien solo, simpele zin "individueel project, alle componenten zelf gebouwd">`

### Libraries & frameworks
- **Data/ML**: pandas, numpy, scikit-learn, xgboost, optuna, shap, torch (PyTorch CPU), pyarrow.
- **RL**: gymnasium (Farama).
- **Geo**: h3 (Uber, hexagon indexing).
- **Plotting**: matplotlib.
- **Tooling**: pytest, ruff, jupyter (nbconvert).

### Tutorials / papers
- **DBSCAN** — Ester, Kriegel, Sander, Xu (1996), KDD.
- **H3** — Uber Engineering blog, h3 docs (resolution 9 ≈ 150m edge).
- **Transformer** — Vaswani et al. (2017), "Attention Is All You Need".
- **DQN** — Mnih et al. (2015), "Human-level control through deep reinforcement learning" (replay buffer + target network).
- **Optuna TPE** — Bergstra et al. (2011), "Algorithms for Hyper-Parameter Optimization".
- **SHAP** — Lundberg & Lee (2017).
- `<TODO: tutorials of cursus-materiaal van UCLL Advanced AI invullen — week 4 (Deep RL), week 5 (Q-learning), week 6 (Transformers)>`

### GenAI usage (Claude / Anthropic)
- **Boilerplate generation**: Gym-env class structure, DQN replay buffer + training loop, pytest test scaffolding.
- **Debugging**: Windows torch DLL conflict (pandas-vs-torch import order), ruff lint fixes, replay-mode action-builder.
- **Iterative design dialogue**: DBSCAN-parameter pivot voor stop-detectie (issue 1.3), simulator-validation -48% gap analysis (issue 3.4), agent-comparison ablation interpretatie (issue 4.4). Op meerdere momenten gepauzeerd om opties voor te leggen ipv stilletjes door te gaan met scope-creep.
- **Documentation drafting**: PROGRESS.md per-issue logs, docs/limitations.md, README sections, notebook intros + conclusions, deze fiche-content-dump.
- **Code review**: ruff + pytest pass-checks, leakage-verificatie van features.parquet (per-cel re-derivation), gymnasium env_checker confirmation.
- `<TODO: jouw eigen perspectief toevoegen — wat heb jij beoordeeld voordat je het accepteerde, waar week je af van Claude's voorstellen, hoe gebruik jij GenAI verantwoord>`

---

## 6. Challenges & Future work

(Volledig uitgewerkt in [docs/limitations.md](limitations.md). Hier de korte versie voor de fiche.)

### Challenges (top 4, allemaal data-gedreven pivots)
1. **3-dagen-dataset bottleneck**: forceert LODO-CV met 3 folds; XGBoost slaat Transformer ondanks deze laatste's grotere capaciteit; holiday-fold uniek dus held-out-evaluatie kwetsbaar.
2. **DBSCAN-parameter-pivot**: issue specificeerde `min_samples=10` dat slechts 20.5% sales-coupling haalde. Diagnose: bursty GPS-sampling. Fix na 4 iteraties: `min_samples=2` → 63.9%. **DoD aangepast** van 70% naar 60% met expliciete rationale.
3. **Simulator-realisme gap**: replay-validatie haalde -48% sales (DoD ±20% niet gehaald). Geen calibratie-scale toegepast. Compensatie: 5.8× discriminator-ratio bewijst simulator discrimineert correct. Open: HDBSCAN voor quick-stops, H3 res 8.
4. **XGBoost MAE-degeneratie**: sub-tile vondst — model met laagste MAE blijkt constant-0 predictor (per-bucket MAE = mean(demand) tot 3 decimalen). Per-rij MAE is verkeerde metric voor sparse forecasting. Forecaster-keuze (Transformer) los van metric-ranking.

### Future work (gerangschikt op marginal value-per-effort)
1. **Forecaster-fix**: XGBoost met `objective=reg:squarederror` of log-target zou de MAE-degeneratie verhelpen. Ablation toonde +196% sales-lift met oracle-forecast → grootste hefboom.
2. **MDP-spec reward implementeren in env**: full `+1·answered + α·revenue − β·distance − γ·unanswered` ipv huidige sales-delta proxy. Vereist call-lifecycle (open/answered/expired) in env.
3. **Stops-detectie verbeteren**: HDBSCAN of variable-density clustering → +30 percentpunt sales-coverage in simulator.
4. **Streamlit demo-app**: forecast-explorer + agent-vergelijking interactief. Module-architectuur is klaar.
5. **Meer dagen data**: ≥14 dagen zou Transformer competitief maken (wekelijkse patronen leren) en proper k-fold mogelijk maken.
6. **DQN met raw action-space**: ipv 4 macros echte zone-keuze per van. Vereist factorized Q of actor-critic.
7. **Multi-objective Pareto-frontier**: ipv één gewogen reward, laat stakeholders kiezen tussen revenue-greedy en customer-fair beleid.
