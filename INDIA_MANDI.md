# India Mandi Commodity Prices

India deploy uses **mandi modal prices** (₹/quintal) instead of US CBOT/CME futures.

## Source

- Default feed: `https://farmer.in/api/open/prices.json` (Agmarknet / GoI attribution)
- Override with env `INDIA_MANDI_PRICES_URL`
- Market mode: `COMMODITY_MARKET=india` (default) or `us` for legacy USDA/Yahoo

## API

| Method | Path | Notes |
|--------|------|--------|
| `GET` | `/api/commodity-prices/quotes` | Dict of live quotes keyed by commodity id (`wheat`, `rice`, …) |
| `GET` | `/api/commodity-prices/mandi` | Rich catalog (`?category=&q=&limit=`) with MSP, Hindi, season |
| `GET` | `/api/commodity-prices/history` | History from `CommodityPriceHistory` (INR stored in `PriceUSD`) |
| `POST` | `/api/commodity-prices/fetch` | Queue refresh + history insert (Cloud Scheduler) |

## Frontend

- `/commodity-prices` — India mandi UI (₹, MSP, search/filter)
- News **Mandi Snapshot** — wheat / rice / soybean
- Cache key: `ofn_india_mandi_quotes_v1` (no Yahoo fallback)

## Smoke test

```bash
curl -sS "$BACKEND/api/commodity-prices/quotes" | head
curl -sS "$BACKEND/api/commodity-prices/mandi?limit=5"
curl -sS -X POST "$BACKEND/api/commodity-prices/fetch"
```
