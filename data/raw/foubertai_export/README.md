# Foubert AI — Sample dataset (3 dagen)

**Versie:** 3 mei 2026
**Bron:** Foubert ijs productie database
**Bedrijf:** Foubert ijs

Deze map bevat data van **3 opeenvolgende dagen** met verschillende karakteristieken, om het AI-model in staat te stellen patronen te herkennen tussen feestdagen en gewone dagen, en tussen weekdagen en weekend.

---

## Drie dagen overzicht

| | **30 april** | **1 mei** | **2 mei** |
|---|---|---|---|
| Dag | donderdag | **vrijdag (feestdag)** | zaterdag |
| Type | gewone werkdag | Dag van de Arbeid | weekend |
| Karren actief | 15 | 15 | 13 |
| Sales | 616 | **996** ↑ | 607 |
| Sale items | 1.815 | **3.047** ↑ | 2.411 |
| Reservaties | 5 | 11 | **22** ↑ |
| Calls | 363 | **968** ↑↑ | 435 |
| GPS-punten | 229.716 | 203.501 | 237.150 |

**Belangrijke vergelijking:**
- **30 april (do)** = baseline gewone werkdag
- **1 mei (vr feestdag)** = ~2× zoveel sales, ~3× zoveel calls vs baseline. Méér vraag dan aanbod (zichtbaar in kar-loze calls)
- **2 mei (za)** = weekend met meer reservaties (verjaardagsfeestjes etc) maar minder spontane verkoop

---

## Mapstructuur

```
foubertai_export/
├── README.md                    ← dit bestand (overzicht)
├── 2026-05-02_README_full.md    ← uitgebreid privacy- & datamodel-document (zelfde voor alle dagen)
├── 2026-04-30/
│   ├── README.md                ← korte dag-specifieke samenvatting
│   ├── 01_shifts.tsv .. 08_vans.tsv
│   └── gps/van_*.tsv
├── 2026-05-01/
│   ├── README.md
│   ├── 01_shifts.tsv .. 08_vans.tsv
│   └── gps/van_*.tsv
└── 2026-05-02/
    ├── README.md                ← bevat ook het uitgebreide privacy-document
    ├── 01_shifts.tsv .. 08_vans.tsv
    └── gps/van_*.tsv
```

**Voor uitgebreide privacy-info, datamodel en sample-code:** zie [`2026-05-02_README_full.md`](./2026-05-02_README_full.md) (geldt voor alle 3 dagen — dezelfde sanering, hetzelfde schema).

---

## Snelle start in pandas

```python
import pandas as pd

# Eén dag inladen
sales_30 = pd.read_csv('2026-04-30/02_sales.tsv', sep='\t', parse_dates=['datetime_start','datetime_stop'])
sales_01 = pd.read_csv('2026-05-01/02_sales.tsv', sep='\t', parse_dates=['datetime_start','datetime_stop'])
sales_02 = pd.read_csv('2026-05-02/02_sales.tsv', sep='\t', parse_dates=['datetime_start','datetime_stop'])

# Alle 3 dagen samen
sales_all = pd.concat([sales_30, sales_01, sales_02], ignore_index=True)
print(sales_all.groupby(sales_all['datetime_start'].dt.date)['total_price_vati'].agg(['count','sum']))
```

---

## Sanering (samenvatting)

Alle persoonlijk identificeerbare gegevens zijn verwijderd of geanonimiseerd:

- ✗ Geen klantnamen, e-mails, telefoonnummers
- ✗ Geen straat/huisnr/bus van klanten of reservaties
- ✗ Geen vrije-tekst notities (note_from_customer, internal_note, extra_info)
- ✗ Geen device fingerprinting (udid, ip, useragent)
- ✗ Geen karnamen ("Brownie", "Aardbei", …)
- ✓ Postcode + stad behouden (GDPR-aanvaardbaar locatieniveau)
- ✓ Lat/lng van privé adressen afgerond op 3 decimalen (~110 m)
- ✓ Lat/lng van publieke straat-sales op 4 decimalen (~10 m)
- ✓ GPS-tracking van karren behouden op volle precisie (kar rijdt op publieke wegen)
- ✓ Medewerker-IDs vervangen door SHA2 hash met geheime salt

Voor exacte details per kolom en datamodel: zie [`2026-05-02_README_full.md`](./2026-05-02_README_full.md).

---

**Contact:** Jan Foubert — jan@foubert.eu
