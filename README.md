# Advanced-AI-Project

## Project overview
We gaan ijsverkoop optimaliseren door middel van een LLM te gebruiken om met data zoals drukte, evenementen, ... de beste route doorheen de stad te voorspellen + wat onze voorraden moeten zijn.

## Setup
```bash
git clone <repo-url>
cd Advanced-AI-Project
pip install -r requirements.txt
```

## Data
Ruwe data staat in `data/raw/`, verwerkte data in `data/processed/`.

## Usage
```bash
make all
# of: bash scripts/run_all.sh
```

## Results
Figuren en rapporten komen in `reports/figures/`.

## Limitations
Eerlijke inventaris van wat dit project niet doet (3-dagen-beperking, simulator-aannames, reward-tuning, overfitting-risico) plus mitigaties en future work: zie [docs/limitations.md](docs/limitations.md).

## Repo structure
```
.
├── data/
│   ├── raw/         # ruwe data
│   └── processed/   # verwerkte data
├── notebooks/       # exploratie en analyse
├── src/             # herbruikbare code
├── models/          # getrainde modellen
├── reports/
│   └── figures/     # figuren voor rapport
├── tests/           # unit tests
├── scripts/         # entrypoints
├── Makefile
├── requirements.txt
├── LICENSE
└── README.md
```
