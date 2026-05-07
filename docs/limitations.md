# Limitations & future work

Eerlijke inventaris van wat dit project niet doet, zodat de defense vóór is op de kritiek. Voor elke limitatie: **wat** het is, **impact** in concrete cijfers, **mitigatie** die we toegepast hebben, en **future work**.

## 1. Drie-dagen-dataset

**Wat.** De volledige beschikbare dataset is `foubertai_export` met **3 opeenvolgende dagen**: 30 april 2026 (donderdag, weekday), 1 mei 2026 (vrijdag, Dag van de Arbeid), 2 mei 2026 (zaterdag, weekend). Eén weekday, één feestdag, één weekend-dag. Geen wekelijkse patronen, geen seizoenseffect, geen distributie-shift over tijd.

**Impact.**
- Sequence-model (Transformer, issue 1.8) kan geen langetermijn-afhankelijkheden leren; XGBoost slaat hem op alle metrics (zie issue 2.4 vergelijking).
- Cross-validatie is gefixeerd op leave-one-day-out met 3 folds — beperkte statistische power.
- Holiday (1 mei) is een unieke dag in de set — bij held-out evaluatie ziet het model dat distributie-regime nooit, wat de slechtere prestaties op die fold verklaart (XGBoost MAE 0.090 vs 0.045 op weekday in issue 1.7).

**Mitigatie.**
- LODO-CV bewust gekozen ipv random split, omdat dag-grenzen de natuurlijke unit voor distributie-shift zijn (issue 1.6).
- Multi-seed evaluatie (5 seeds per (agent, dag) in issue 5.1) middelt seed-variantie uit zodat conclusies niet op één run leunen.
- Lag-features per zone gebruiken kort-termijn historiek binnen de dag, het enige echte signaal dat 3 dagen biedt.

**Future work.** Productie-export uitbreiden naar **>14 dagen** zodat (a) de Transformer wekelijkse patronen kan leren, (b) k-fold CV met bv. 5 random folds werkt, (c) het model getest kan worden op echt out-of-distribution dagen (een toekomstige weekend, andere maand).

## 2. Simulator-realisme: meerdere niet-getoetste aannames

**Wat.** De simulator (issue 3.x) maakt vereenvoudigingen om binnen scope te blijven:
- **10-min tijdstap**: verplaatsing tussen zones is instant in elke step. Reële reistijd (5-10 min stadsverkeer) wordt niet gemodelleerd.
- **Geen answered/unanswered lifecycle**: een gegenereerde call blijft "open" tot ze automatisch matched wordt aan een van die in de zone is. Geen expliciete dispatching, geen call-expiratie.
- **Sales-sampling met 2-ring H3 pooling** (~750m diameter, issue 3.4): "een van bedient een gebied van een paar straten". Fysiek defendable, niet getoetst tegen werkelijk klant-loop-gedrag.
- **`nr_of_people` empirisch gesampled** uit historiek; in werkelijkheid context-afhankelijk.
- **`call_fraction = 0.443`** (issue 3.3) is globaal; per-zone of per-uur kan beter zijn.

**Impact.** Simulator-validatie (issue 3.4) toonde:
- Calls reproduceren binnen +11% van historisch (1 mei) → ✓.
- Sales reproduceren met **-48% afwijking** (replay 323 vs hist 616). DoD ±20% niet gehaald; oracle-test bevestigde dat dit een **sampling-bottleneck** is, niet een forecaster-bottleneck.
- Replay/random sales-ratio = 5.8× → simulator discrimineert wel correct tussen informed en willekeurige acties, wat downstream RL nodig heeft.

**Mitigatie.**
- Replay-validatie gedocumenteerd in [notebooks/04_sim_validation.ipynb](../notebooks/04_sim_validation.ipynb) met expliciete DoD-fail-rationale.
- Geen calibratie-scale toegepast om de DoD via een hack te halen — eerlijke ondergrens vastgelegd.
- Discriminator-ratio (5.8×) als alternatieve validation-metric: als de simulator policies onderscheidt, is hij bruikbaar voor RL-training, ook als absolute counts onder zitten.

**Future work.**
- Travel-tijd modelleren via `distance_km / 25 km/u` (gepind in MDP-spec, issue 3.2).
- Dispatching-lifecycle: expliciet bijhouden welke calls "geclaimd" zijn door welke van; calls die >60min ongeantwoord blijven verdwijnen of terugvallen naar de queue.
- HDBSCAN ipv DBSCAN voor stop-detectie — verhoogt sales-coverage van ~50% naar 70-80% (issue 3.4 open punt).
- H3 resolutie 8 (~500m cellen) zou GPS-jitter binnen één cel houden, maar vereist herbouw features.parquet en hertraining forecaster.

## 3. Reward-tuning gevoeligheid

**Wat.** De MDP-spec (issue 3.2) definieerde een reward-formule:

```
r = +1·answered_call + α·revenue − β·distance_km − γ·unanswered_call
```

met `α = 0.10`, `β = 0.10`, `γ = 2.00` gepind op EDA-cijfers (gem. sale €14, 80% miss rate op feestdag). **Maar deze formule is niet geïmplementeerd in de env** — `env.step()` retourneert reward = 0.0. De agents (Q-learning, DQN) computen reward in hun eigen training-loop als `Δ n_total_sales` per step.

**Impact.**
- Agents optimaliseren puur voor **gerealiseerde sales-count**, niet voor het volledige cost-balance dat de spec beoogde.
- **Distance** wordt niet meegenomen in optimization → agents kunnen onnodig veel rondrijden zonder penalty.
- **Unanswered calls** geven geen direct signaal → het is impliciet (vans niet bij call = geen sale = geen reward) maar niet geïsoleerd.
- Trade-off tussen 1 grote sale en 5 kleine onbeantwoorde calls is nu onmogelijk te leren.

**Mitigatie.**
- MDP-spec staat in [docs/mdp_spec.md](mdp_spec.md), met expliciete motivatie van α/β/γ — duidelijk dat dit een **eerste pin** was, geen experimentele winnaar.
- Multi-metric eval-suite (issue 5.1) meet revenue, distance, response-time, fairness — los van wat de agent intern optimaliseert. Stakeholders krijgen het volledige plaatje.
- Issue 4.4 ablation toonde dat agent-keuzes vooral door forecast-kwaliteit gedreven worden, niet door reward-tuning — α/β/γ tunen zou marginale winst leveren zonder forecaster-fix.

**Future work.**
- Volledige reward implementeren in `env.step()` — vereist `answered/unanswered` lifecycle (zie limitatie 2).
- Grid-search of Optuna over α/β/γ met simulator-evaluatie als objective.
- Multi-objective Pareto-frontier ipv één gewogen som (bv. via PPO of multi-objective RL) — laat stakeholders kiezen tussen revenue-greedy en customer-fair beleid.

## 4. Overfitting-risico

**Wat.** Beide getrainde agents (Q-learning, DQN) trainen op 30/4 + 1/5 en testen op 2/5. Slechts **één** held-out dag: seed-noise kan eindresultaat dwingen.

- Q-table: 48 entries (12 states × 4 macros), getraind op 60 episodes × 2 dagen.
- DQN: 64-64 hidden net, 500 episodes × 2 dagen, replay buffer 10k.

**Impact.**
- Issue 4.3 single-seed (seed=999) gaf DQN > Q-tabular (163 vs 140 sales). Issue 4.4 multi-seed (3 seeds × 3 dagen) gaf Q-tabular > DQN gemiddeld (200.8 vs 187.1). De single-seed conclusie zat dus binnen seed-noise.
- Beide agents leerden voornamelijk dat `forecast_top` macro (53-60% van picks) winnen is — die heuristiek is bekend zonder training. Echte policy-leerwinst boven heuristiek is beperkt.
- Test-dag (2 mei = weekend) heeft eigen distributie-regime; train-dagen dekten dat niet.

**Mitigatie.**
- Multi-seed evaluatie in 5.1 (5 seeds × 3 dagen) middelt zowel seed-noise als dag-distributie-effecten uit. Eindrapport rangschikt agents op de **mean** over alle (date, seed) tuples, niet op één run.
- Macro-design met 4 hand-gecodeerde opties houdt de policy-class klein → minder ruimte om te overfitten op trainingsdistributie.
- Reward-curves (issue 4.2/4.3) tonen plateau in zowel Q als DQN — geen tekenen van late-stage overfitting.

**Future work.**
- Meer dagen training (zie limitatie 1) zodat k-fold CV met meer folds mogelijk wordt.
- Out-of-distribution test op een **nieuwe dag-regime** (bv. regenachtige werkdag, of andere stad als die data ooit beschikbaar wordt).
- Regularisatie in DQN (L2-weight-decay, dropout) was niet nodig binnen 500 episodes maar kan overweegd worden bij langere training.

---

## Synthese

Drie van de vier limitaties leiden naar dezelfde plaats: **meer data**. De 3-dagen-beperking dwingt simulator-keuzes (sampling, geen lifecycle), beperkt model-capaciteit (Transformer onder XGBoost), en maakt elke held-out evaluatie kwetsbaar voor distributie-shift. De vierde — reward-tuning — is een implementatie-schuld die los van data verbeterd kan worden, maar issue 4.4 wijst uit dat **forecast-kwaliteit de grootste hefboom** is voor agent-prestaties (+196% met oracle vs predicted). Forecast-fix > reward-fix > meer data > meer simulator-realisme, in volgorde van marginal value-per-effort.
