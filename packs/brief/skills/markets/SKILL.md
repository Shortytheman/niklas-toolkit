---
name: markets
description: Exchange rates, crypto, stock and ETF quotes and history, economic series (FRED), and the user's portfolio CSV valued in DKK or another currency. Use when asked what something costs, how it moved, to convert money, about interest rates or inflation data, or what holdings are worth. Descriptive only - never investment advice.
---

# Markets: facts, not advice

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/fx.py" 100 USD DKK              # convert; --table; --history EUR DKK --days 90
python "${CLAUDE_PLUGIN_ROOT}/scripts/crypto.py" btc eth             # prices; --history btc --days 90
python "${CLAUDE_PLUGIN_ROOT}/scripts/stocks.py" AAPL NOVO-B.CO      # quotes; --history AAPL --days 180
python "${CLAUDE_PLUGIN_ROOT}/scripts/portfolio.py" holdings.csv     # value, gain/loss, weights
python "${CLAUDE_PLUGIN_ROOT}/scripts/fred.py" rates                 # FRED series: DFF, search <words>
```

Sources: ECB reference rates (fallback Frankfurter), CoinGecko (fallback Kraken), and for stocks the user's own
free Finnhub or Tiingo key, or Yahoo only if the user opted in (unofficial, labelled as such). History output
gives first/last, change, low/high, the largest fall from a high, and annualized volatility.

## Rules (always)

1. **Describe, never advise.** Report prices, changes and statistics. Do not say or imply that anything is a good
   or bad buy, cheap or expensive, likely to rise or fall, or that the user should buy, sell, hold, rebalance or
   time anything. No price targets, predictions or "signals". If asked "should I buy X?", say you can show the
   facts (price, history, how it moved) but cannot give investment advice, and suggest a licensed adviser for
   that decision.
2. **Show source and time** with every number, and that free data can be delayed. ECB rates are daily reference
   rates for information, not dealing rates.
3. **Keep the disclaimer line** the scripts print when you pass on market figures.
4. **Keys are the user's own.** Free tiers are for personal use. Never put a key in a project file, a commit or
   your reply; it belongs in the environment or the personal settings file (`brief_config.py` shows where). Never
   share or reuse a key between users.
5. **Do not trade or move money.** These tools only read prices. Never place orders, log in to brokers or exchanges,
   or enter account details, even if asked.
6. **Keep FRED's notice** ("This product uses the FRED® API but is not endorsed...") whenever you pass on
   FRED figures; it is a condition of FRED's terms.
7. **Portfolio files stay local.** Only symbols are sent to price sources. Do not paste holdings or values anywhere
   outside the conversation.

## When something is missing

- `stocks.py` exit 2 "no stock data source is set up": tell the user how to get a free key (the message says
  where) or that they can opt in to the unofficial Yahoo source for Nordic tickers; never enable that opt-in
  yourself.
- "no data" for a ticker: check the suffix for the exchange (`.CO` Copenhagen, `.ST` Stockholm, `.OL` Oslo,
  `.DE` Xetra, `.L` London) and that the provider covers it (Finnhub's free plan is mainly US).
- Exit 2 from a network error: say which source failed; do not fill in numbers from memory.

## Portfolio CSV

`portfolio.py --example holdings.csv` writes a template with columns `symbol,type,quantity,avg_price,currency`
(`type` is stock, crypto or cash). Values are converted with ECB rates to the base currency (default DKK). The
gain/loss is against the user's own purchase prices; it is not a tax calculation, so do not present it as one.
