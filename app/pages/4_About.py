"""About-pagina — projectcontext, aanpak, links voor de defense.

Geen model-loads, dus require_files niet nodig. Gewone tekst-page met
expanders zodat het kort blijft op kleine schermen.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from app.sidebar import inject_css, render_sidebar

st.set_page_config(page_title="About — Foubert", page_icon="ℹ️", layout="wide")
inject_css()
render_sidebar()

st.title("ℹ️ About — Foubert Dispatcher")
st.markdown(
    "**Waar moet elke ijswagen vandaag naartoe?** Een end-to-end systeem dat "
    "demand-forecasting combineert met reinforcement learning om dispatching "
    "voor [Foubert IJs](https://www.foubert.eu) te optimaliseren."
)

st.divider()

c1, c2 = st.columns([3, 2], gap="large")

with c1:
    st.subheader("Aanpak in drie lagen")
    st.markdown(
        """
**1. Demand-forecaster** voorspelt vraag per (zone, uur) op basis van historische
sales, GPS-stops, weer (Open-Meteo) en feestdagen. Twee modellen vergeleken:
- **XGBoost** met Optuna-tuning + SHAP-feature-attributie.
- **Transformer** (2-layer, 4 heads) met self-attention over een 24h-context.

**2. Gym-compatibele simulator** (`DispatcherEnv`) speelt één dag af in
10-minuten-stappen, op een grid van 911 H3-zones × tot 15 vans. Sales en calls
worden per step gesampled uit de forecast; de env exposes een MDP met
discrete macro-actions ("blijf hier" / "ga naar drukste buurzone" / etc.).

**3. RL-agents** leren optimale dispatch-strategieën:
- **Random** & **Greedy** (nearest-free-van) als baselines.
- **Historical replay** vervangt de geleerde policy door de echte van-trajecten
  uit de export — referentiepunt voor "wat zou Foubert zelf doen".
- **Tabular Q-learning** over 4 macro-options per van.
- **DQN** (PyTorch, target-net, replay-buffer).
        """
    )

    st.subheader("Kernresultaat")
    st.markdown(
        """
Op de 3 dagen × 5 seeds (mean over alle runs):

| Agent | % calls answered | Revenue (€) | Distance (km) | Response (min) |
|---|---:|---:|---:|---:|
| **Q-learning** | **30.6** | **2.765** | 1.947 | 57 |
| DQN | 28.1 | 2.603 | 3.703 | 78 |
| Historical (echte trajecten) | 20.4 | 1.659 | 4.766 | 122 |
| Greedy (nearest free van) | 19.5 | 1.575 | **1.121** | **22** |
| Random | 14.7 | 1.085 | 12.677 | 149 |

Tabular Q-learning leidt op revenue + % answered + neglected zones; greedy is
sneller in response-time maar haalt minder totale revenue. Een ablation toonde
dat DQN met **oracle ground-truth forecast** ~3× zoveel sales realiseert dan
met de geleerde Transformer — **forecast-kwaliteit is de dominante hefboom**,
niet agent-architectuur.
        """
    )

with c2:
    st.subheader("Stack")
    st.markdown(
        """
- Python 3.12, PyTorch 2.x, XGBoost, Optuna, SHAP
- Gymnasium, scikit-learn (DBSCAN), H3 (resolution 9, ~150m)
- Streamlit + PyDeck + Altair voor de demo-app
- Open-Meteo API voor historisch weer
- Pytest + Ruff voor tests + lint
        """
    )

    st.subheader("Links")
    st.markdown(
        """
- 💻 [GitHub repo](https://github.com/RalphBogaertUCLL/Advanced-AI-Project)
- 📚 [docs/limitations.md](https://github.com/RalphBogaertUCLL/Advanced-AI-Project/blob/main/docs/limitations.md) — eerlijke inventaris van wat dit systeem niet doet
- 📋 [docs/mdp_spec.md](https://github.com/RalphBogaertUCLL/Advanced-AI-Project/blob/main/docs/mdp_spec.md) — state/action/reward design
- 📓 [notebooks/05_agent_comparison.ipynb](https://github.com/RalphBogaertUCLL/Advanced-AI-Project/blob/main/notebooks/05_agent_comparison.ipynb) — detail-analyse
- 📊 [results/eval_summary.csv](https://github.com/RalphBogaertUCLL/Advanced-AI-Project/blob/main/results/eval_summary.csv) — 5 agents × 3 dagen × 5 seeds
        """
    )

    st.subheader("Context")
    st.caption(
        "UCLL Bachelor Toegepaste Informatica — semester 2, vak **Advanced AI**. "
        "Auteur: Ralph Bogaert. Begeleider-ondersteuning: ChatGPT/Claude voor "
        "boilerplate + brainstorm; alle architecturele beslissingen, evaluatie en "
        "interpretatie zijn eigen werk."
    )

st.divider()

with st.expander("Wat zit niet in deze demo?"):
    st.markdown(
        """
- **Geen multi-day training** voor RL-agents: episodes zijn 1 dag, agent reset elke
  dag. Reden: 3 dagen data is te weinig voor multi-day continuity zonder overfitting.
- **Geen real-time call-pulsing** op de Dispatch-kaart — pydeck heeft geen native CSS-
  animaties. Vervangen door kleur-staat-overgang (geel → groen/rood).
- **Geen pydeck click-events** in de Forecast-kaart — Streamlit's pydeck-component
  ondersteunt geen native click-event. Vervangen door selectbox van top-30 zones.
- **Geen seed/dag-toggle** in Comparison — bewust strict scope; de offline eval-suite
  ([scripts/run_evaluation.py](https://github.com/RalphBogaertUCLL/Advanced-AI-Project/blob/main/scripts/run_evaluation.py))
  doet de N-seed × N-dag analyse al.

Alle trade-offs zijn gedocumenteerd in [docs/limitations.md](https://github.com/RalphBogaertUCLL/Advanced-AI-Project/blob/main/docs/limitations.md).
        """
    )

with st.expander("Hoe interpreteer ik de resultaten?"):
    st.markdown(
        """
- **% answered**: aandeel calls dat een van binnen 30 min in dezelfde zone had.
- **Revenue (€)**: aantal sales × gemiddelde sale-waarde (€14, gederiveerd uit
  `sale_orders.parquet`).
- **Distance (km)**: totale gereden afstand door alle vans samen op de dag.
- **Response (min)**: gemiddelde tijd van call-creatie tot aankomst van een van.
- **Fairness Gini**: ongelijkheid tussen zones in service-niveau (0 = elke zone
  evenveel bediend, 1 = één zone krijgt alles). Lager = eerlijker.
- **Neglected zones %**: aandeel zones met ≥1 call die nooit beantwoord werd.

In de **Efficiency frontier** scatter (Comparison-tab) is **linksboven ideaal**:
veel revenue, weinig km. Q-learning zit daar; greedy zit linksonder (efficiënt
maar weinig revenue); random zit rechtsonder (veel km, weinig revenue).
        """
    )
