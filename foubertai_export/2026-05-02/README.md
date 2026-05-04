# Foubert AI — Sample dataset 2 mei 2026

**Versie:** export van 3 mei 2026
**Bron:** Foubert ijs productie database (`icecorpapi_productiondb`)
**Bedrijf:** Foubert ijs (company_id = 2)
**Periode:** 1 dag — zaterdag 2 mei 2026, 00:00–23:59 UTC
**Karren:** 13 ijskarren met 1 medewerker op die dag (ID 5, 6, 8, 9, 10, 11, 13, 14, 15, 34, 35, 101, 102, 103)

---

## Inhoud

| Bestand | Beschrijving | Rijen |
|---------|--------------|-------|
| `01_shifts.tsv` | Werkdagen + shifts per kar (welke pseudo-medewerker, op welke kar, wanneer) | 29 |
| `02_sales.tsv` | Individuele verkopen (één rij per transactie aan kassa) | 607 |
| `03_sale_orders.tsv` | Wat er per verkoop gekocht werd (lijntjes per product, bv. "2 bol", "1 slagroom") | 2.411 |
| `04_menu_items.tsv` | Productlijst (alleen items die die dag verkocht zijn) | 65 |
| `06_reservations.tsv` | Reservaties (private feestjes + georganiseerde events) | 22 |
| `07_calls.tsv` | Klantoproepen via app — vraag naar de kar op een locatie | 435 |
| `08_vans.tsv` | Karren-metadata (nummer + kleurcode, geen naam) | 13 |
| `gps/van_*.tsv` | GPS-tracking per kar (1 punt per ~3-5s) | 237.150 |

**Totaal:** ~24 MB, alles in TAB-separated values (`.tsv`).

---

## Sanering omwille van privacy (GDPR)

Voor het delen van deze dataset zijn alle persoonlijk identificeerbare gegevens (PII) verwijderd of geanonimiseerd. Dit document beschrijft exact welke transformaties zijn toegepast.

### 1. Volledig weggelaten kolommen

Deze velden bestaan in de productie-database maar zitten **niet** in de export:

#### Klantdata (uit `orders`, `icecream_van_calls`, `icecream_van_reservations`)
- `name`, `first_name`, `last_name` — klantnamen
- `email` — e-mailadressen
- `cellphone_nr`, `backup_cellphone_nr` — telefoonnummers
- `address_street`, `address_nr`, `address_bus` — exacte straatadressen
- `extra_info`, `note_from_customer`, `internal_note` — vrije-tekst velden die context kunnen lekken (bv. _"klein kindje, ophouden om 20u30"_)

De **volledige `orders` tabel** is niet meegenomen; deze koppelt klantdata aan reservaties.

#### Device-/sessie-fingerprinting (uit `icecream_van_calls`)
- `udid` — device ID
- `ip` — IP-adres
- `token` — sessie token
- `useragent` — browser identificatie
- `version_info` — app-versie

#### Branding-/locatie-leakage
- `icecream_vans.name` — sommige karnamen bevatten gemeentenamen ("Lokeren") of mascotte-namen die het bedrijf herkenbaar maken; alleen `nr` (1, 2, 3, …) en de kleurcodes blijven over

### 2. Pseudonimisering (consistent maar niet herleidbaar)

| Origineel | Vervangen door | Methode |
|-----------|----------------|---------|
| `working_days.employee_id` | `emp_hash` in `01_shifts.tsv` | `SHA2(CONCAT('<salt>', employee_id), 256)` |

**Doel:** dezelfde medewerker is herkenbaar over verschillende shifts heen (om patronen per persoon te kunnen modelleren), maar zonder de salt is de echte ID niet recupereerbaar. De salt wordt nooit gedeeld.

**Niet gepseudonimiseerd:** klanten. Een klant die meerdere keren een oproep deed of meerdere reservaties had op die dag is in de export _niet_ koppelbaar tussen records — bewust, om tracking onmogelijk te maken.

### 3. Locatie-precisie verlaagd

GPS-coördinaten worden in de DB op ~6 decimalen opgeslagen (~10 cm precisie). Voor de export is dat verlaagd:

| Bron | Origineel | In export | ≈ Precisie | Reden |
|------|-----------|-----------|------------|-------|
| `sales.latitude/longitude_start/stop` | 6 decimalen | **4 decimalen** | ~10 m | Sales gebeuren op publieke straat — geen privé locatie |
| `icecream_van_reservations.latitude/longitude` | 6 decimalen | **3 decimalen** | ~110 m | Privé woonadres — niet huisniveau |
| `icecream_van_calls.latitude/longitude` (en `_gps`) | 6 decimalen | **3 decimalen** | ~110 m | Idem |
| `datapoints.latitude/longitude` (GPS van kar) | 6 decimalen | **6 decimalen** | ~10 cm | De kar zelf rijdt op publieke wegen — geen privacy issue |

### 4. Locatie-velden die WEL behouden zijn

- **`address_zipcode`** (Belgische postcode, 4 cijfers, ~stad-niveau) — GDPR-aanvaardbaar
- **`address_city`** — gemeentenaam
- **`address_country`** — land

Deze drie samen geven dezelfde info als een postzegel op een brief: voldoende om geografische clustering te doen, te weinig om iemand te identificeren.

### 5. Encoding

Tekstuele export werd opnieuw gedraaid met `--default-character-set=utf8mb4` om correcte weergave van diakritische tekens te garanderen (bv. _België_ in plaats van _Belgi�_).

---

## Velden die zijn behouden (geen privacy-risico)

- **Tijdstempels** — `datetime_start`, `datetime_stop`, `created_at`, `updated_at`
- **Financiële cijfers** — prijs vati/vate, BTW, kortingen, kilometervergoeding
- **Productnamen** in `sale_orders.name` — generieke producten zoals _"1 bol"_, _"slagroom"_, _"brownie medium"_; geen klantnamen
- **Aantal personen** in calls/reservations — opgegeven als ranges (_1-2_, _3-4_, _5-9_, …)
- **Status enums** — bv. `EXECUTED`, `APPROVED`, `CANCELED`
- **Reservatie-classificatie** in `06_reservations.tsv`:
  - `EVENT_PAID_BY_HOST` — gastheer betaalt callout charge / minimum consumption
  - `EVENT_PAY_PER_PERSON` — bv. opening, schoolfeest, betaald per stuk
  - `PRIVATE_RESERVATION` — verjaardag/communie aan huis
- **`was_close`** boolean in calls — _was er op moment van oproep een kar in de buurt?_

---

## Datamodel — kort schema

```
shifts (01_shifts)
  ├── icecream_van_id ──────────┐
  ├── emp_hash (gepseudonimiseerd)
  └── shift_id ──┐              │
                 │              │
sales (02_sales) │              │
  ├── shift_id ──┘              │
  ├── icecream_van_id ──────────┤
  ├── latitude/longitude_start  │      icecream_vans (08_vans)
  ├── latitude/longitude_stop   │              ├── id ─────────────────┐
  ├── total_price_vati          │              ├── nr (1, 2, 3, …)
  └── sale_id ──┐               │              └── color_text/background
                │               │                                       │
sale_orders (03_sale_orders)    │      datapoints (gps/van_*.tsv)       │
  ├── sale_id ──┘               │              ├── icecream_van_id ─────┤
  ├── menu_item_id ──┐          │              ├── latitude/longitude   │
  ├── name           │          │              ├── velocity             │
  └── price_vati     │          │              └── created_at           │
                     │          │                                       │
menu_items (04_menu_items)      │      icecream_van_calls (07_calls)    │
  ├── id ────────────┘          │              ├── shift_id (nullable)  │
  ├── menu_id                   │              ├── icecream_van_id ─────┤
  ├── name                      │              ├── latitude/longitude   │
  └── price_vati                │              ├── nr_of_people         │
                                │              ├── address_zipcode/city │
icecream_van_reservations (06_reservations)    └── was_close            │
  ├── icecream_van_id ──────────┴──────────────────────────────────────┘
  ├── status, datetime_start/stop
  ├── address_zipcode/city/country
  ├── latitude/longitude (3 decimalen)
  └── reservation_type (EVENT_PAID_BY_HOST / EVENT_PAY_PER_PERSON / PRIVATE_RESERVATION)
```

### Belangrijke joins voor het AI-model

```python
# Welke kar heeft welke sale gedaan?
sales.merge(shifts, on='shift_id')

# Welke producten in welke sale (= bolletjes per ticket)?
sale_orders.groupby('sale_id').agg({'name': list, 'price_vati': 'sum'})

# Werd een call beantwoord door een kar?
calls['was_assigned'] = calls['shift_id'].notna()
# 302 van 435 calls (= 69%) hadden GEEN kar → vraag-aanbod gap

# GPS van een specifieke kar
gps_van_11 = pd.read_csv('gps/van_11.tsv', sep='\t', parse_dates=['created_at'])
```

---

## Wat is wél mogelijk met deze dataset?

- **Voorraadvoorspelling** — hoeveel bolletjes per uur per locatietype
- **Route-optimalisatie** — GPS + sales locaties + call locaties
- **Vraag-aanbod analyse** — calls zonder kar (302 stuks) tonen waar tekort was
- **Event vs gewone rondrit performance** — `reservation_type` veld
- **Effect van weer/dag op verkoop** — kun je correleren met externe weerdata
- **Pad-efficiëntie** — verhouding GPS-afstand vs sales-omzet
- **Stop-pattern detectie** — clusters in GPS waar velocity ≈ 0

## Wat is NIET mogelijk?

- Identificeren van individuele klanten of medewerkers
- Herleiden naar specifieke huisadressen (locatie-precisie van calls/reservations is bewust 110 m)
- Linken van twee calls naar dezelfde persoon (caller-hash bewust verwijderd)

---

## Volgende stappen

1. Open de TSV-bestanden in pandas / Excel / R
2. Bij vragen over kolomstructuur of extra dagen / event-dagen / feestdagen: contacteer Jan Foubert
3. Voor productie zou een **read-only replica** worden opgezet zodat queries de hoofd-DB nooit belasten

**Contact:** Jan Foubert — jan@foubert.eu
