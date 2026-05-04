# Foubert AI — Sample dataset 1 mei 2026

**Versie:** export van 3 mei 2026
**Bron:** Foubert ijs productie database (`icecorpapi_productiondb`)
**Bedrijf:** Foubert ijs (company_id = 2)
**Periode:** 1 dag — **vrijdag 1 mei 2026 (Dag van de Arbeid — wettelijke feestdag)**, 00:00–23:59 UTC
**Karren:** 15 ijskarren met 1 medewerker op die dag (ID 5, 6, 7, 8, 9, 10, 11, 13, 14, 34, 35, 91, 101, 102, 103)

> ⚠ **Speciale dag:** 1 mei is een wettelijke feestdag in België — ijsverkopen en oproepen liggen ~2× hoger dan op een normale weekdag (vergelijk met `2026-04-30` voor baseline).

---

## Inhoud

| Bestand | Beschrijving | Rijen |
|---------|--------------|-------|
| `01_shifts.tsv` | Werkdagen + shifts per kar (welke pseudo-medewerker, op welke kar, wanneer) | 30 |
| `02_sales.tsv` | Individuele verkopen (één rij per transactie aan kassa) | 996 |
| `03_sale_orders.tsv` | Wat er per verkoop gekocht werd (lijntjes per product, bv. "2 bol", "1 slagroom") | 3.047 |
| `04_menu_items.tsv` | Productlijst (alleen items die die dag verkocht zijn) | 54 |
| `06_reservations.tsv` | Reservaties (private feestjes + georganiseerde events) | 11 |
| `07_calls.tsv` | Klantoproepen via app — vraag naar de kar op een locatie | 968 |
| `08_vans.tsv` | Karren-metadata (nummer + kleurcode, geen naam) | 15 |
| `gps/van_*.tsv` | GPS-tracking per kar (1 punt per ~3-5s) | 203.501 |

**Totaal:** ~20 MB.

Voor het volledige saneringsbeleid en datamodel: zie [`../README.md`](../README.md).
