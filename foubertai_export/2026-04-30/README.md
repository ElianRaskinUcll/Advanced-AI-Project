# Foubert AI — Sample dataset 30 april 2026

**Versie:** export van 3 mei 2026
**Bron:** Foubert ijs productie database (`icecorpapi_productiondb`)
**Bedrijf:** Foubert ijs (company_id = 2)
**Periode:** 1 dag — **donderdag 30 april 2026 (gewone werkdag)**, 00:00–23:59 UTC
**Karren:** 15 ijskarren met 1 medewerker op die dag (ID 1, 3, 5, 6, 7, 8, 9, 10, 11, 13, 14, 34, 35, 91, 103)

> ℹ **Baseline-dag:** gewone donderdag, geen feestdag, dient als baseline voor vergelijking met vrijdag 1 mei (Dag van de Arbeid) en zaterdag 2 mei.

---

## Inhoud

| Bestand | Beschrijving | Rijen |
|---------|--------------|-------|
| `01_shifts.tsv` | Werkdagen + shifts per kar (welke pseudo-medewerker, op welke kar, wanneer) | 29 |
| `02_sales.tsv` | Individuele verkopen (één rij per transactie aan kassa) | 616 |
| `03_sale_orders.tsv` | Wat er per verkoop gekocht werd (lijntjes per product, bv. "2 bol", "1 slagroom") | 1.815 |
| `04_menu_items.tsv` | Productlijst (alleen items die die dag verkocht zijn) | 51 |
| `06_reservations.tsv` | Reservaties (private feestjes + georganiseerde events) | 5 |
| `07_calls.tsv` | Klantoproepen via app — vraag naar de kar op een locatie | 363 |
| `08_vans.tsv` | Karren-metadata (nummer + kleurcode, geen naam) | 15 |
| `gps/van_*.tsv` | GPS-tracking per kar (1 punt per ~3-5s) | 229.716 |

**Totaal:** ~19 MB.

Voor het volledige saneringsbeleid en datamodel: zie [`../README.md`](../README.md).
