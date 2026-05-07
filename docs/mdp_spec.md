# MDP-spec — Dispatcher voor Foubert IJs

Eén-pagina referentie voor de simulator (`src/env/dispatcher_env.py`). Tijdstap = 10 min, episode = 10:00-21:00 UTC (66 steps/dag).

## State

Vector van vaste lengte. Notatie: N = #vans, K = #pending-call-slots, Z = #forecast-slots.

| Component | Dim | Inhoud |
|---|---:|---|
| `current_hour` | 1 | uur als float (bv. 14.5 voor 14:30) |
| `day_type` | 3 | one-hot: weekday / weekend / holiday |
| `weather` | 3 | temperatuur (°C), neerslag (mm), zonneschijn (s/u) — uit `context.parquet` |
| `vans_state` | 4·N | per van: `[zone_idx, busy_flag, busy_remaining_min, idle_min]` |
| `pending_calls` | 3·K | top-K oudste onbeantwoorde calls: `[zone_idx, age_min, nr_of_people]`, padding −1 |
| `zone_demand_forecast` | Z | predicted demand voor het volgende uur per top-Z zone (van Transformer-model) |

**Defaults:** N = 15, K = 20, Z = 50 → totale dim = 1 + 3 + 3 + 60 + 60 + 50 = **177 floats**. Box-space, schaalvrij (waardes worden in de policy genormaliseerd).

## Action

Per kar één keuze uit `{0, 1, …, n_zones-1, STAY}` waar `STAY = n_zones` (geen verplaatsing).

`action_space = MultiDiscrete([n_zones + 1] * N)`

Busy-vans negeren hun actie; vrije vans starten reizen naar `zone_idx`. Reistijd = `ceil(distance_km / 25 km/u × 60 min / 10)` steps; tijdens transit blijft de van busy.

## Reward

Per step, berekend over alle events tijdens dat 10-min-interval:

```
r_t = +1 · #answered_calls
      + α · estimated_revenue_EUR
      − β · distance_km_traveled
      − γ · #unanswered_calls
```

| Param | Waarde | Motivatie |
|---|---:|---|
| **α** | **0.10** | Gemiddelde sale = €14.0 (€31k / 2.219 sales in EDA). α = 0.10 betekent een sale levert ~+1.4 bovenop de +1 voor `answered_call` → totaal ≈ +2.4 reward per gerealiseerde verkoop. Klein genoeg om niet te overschaduwen, groot genoeg om sale-grootte mee te wegen. |
| **β** | **0.10** | Stadsritten kosten ~€0.30/km (brandstof + slijtage); we wegen het ruim hoger om actieve fleet-coördinatie aan te moedigen. 5 km rijden → −0.5 reward (≈ 20% van een gemiddelde sale-waarde) — ontmoedigt willekeurig kruisen, beboet niet noodzakelijk verplaatsen. |
| **γ** | **2.00** | EDA toonde 80% miss-rate op feestdag — onbeantwoorde calls zijn dé business-pijn. Een gemiste call kost €14 verwachte omzet (één call ≈ één sale); γ = 2 maakt elke miss −2 reward, **groter dan** het opbreng van een gemiddelde answered+sale (+2.4 → +0.4 marginaal voor het laatste km'tje). De agent leert daardoor expliciet calls te prioriteren boven cruise-rondjes. |

**Concrete swing**: een call beantwoorden vs missen = swing van ≈ +4.4 reward (van −2 naar +2.4). Een 5-km-rit naar die call (−0.5) blijft ruim winstgevend (+1.9 netto).

`estimated_revenue_EUR` komt van een lookup-tabel `mean_sale_value_per_zone`, gefit op de 3 dagen historiek (~€11-€18 per zone-bucket).

## Termination & truncation

- `terminated = True` zodra `time ≥ 21:00` (einde operating window).
- `truncated = False` (geen truncation in deze versie).
- Geen episode-restart binnen één dag.

## Open punten (latere issues)

- Travel-tijd nu lineair naar afstand met vaste 25 km/u; verfijnen met GPS-snelheid per zone-paar (issue 3.4+).
- `α / β / γ` zijn op basis van EDA-gemiddelden gepind. Reward-shaping experimenten (issue 4.x) kunnen ze tunen via grid-search op simulator-evaluatie.
- Demand forecast-update: 1× per uur; binnen het uur constant. Bij langere horizon (>1h) eventueel multi-step rollouts.
