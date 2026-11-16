---
name: brief
description: Morning brief and everyday lookups - weather, Hacker News and RSS headlines, new GitHub releases, Danish public holidays and working days. Use when the user asks for a brief, a summary of the day, the weather, news, what's new in a project's releases, the next holiday, or how many working days are in a period.
---

# Brief and everyday lookups

All scripts are in `${CLAUDE_PLUGIN_ROOT}/scripts/` and need no API keys:

| Ask | Command |
| --- | --- |
| Morning brief (everything configured) | `python brief.py` (`--only weather news` for parts) |
| Weather now and next days (forecast) | `python weather.py [place] [--days N]` |
| Measured right now at the nearest DMI station (Denmark) | `python dmi.py [place] [--station ID]` |
| DMI's own forecast (HARMONIE, about 2.5 days) | `python dmi.py --forecast [place]` |
| Hacker News, feeds, GitHub releases | `python news.py [--hn 10] [--feeds] [--releases]` |
| Danish holidays | `python holidays_dk.py [year]` |
| Working days in a period | `python holidays_dk.py --workdays 2026-12-01 2026-12-31` |
| Danish statistics (inflation, population, any table) | `python dk_stats.py inflation`, `search <words>`, `info <TABLE>`, `get <TABLE> VAR=code` |
| See or create the settings | `python brief_config.py [--init]` |

Settings live in one personal file outside any project (`brief_config.py` prints where): location, base
currency, watchlists, feeds, GitHub repos, brief sections, and any API keys. When something is not configured,
the script says what to add; offer to add it with the user's values, and never invent a location or feed.

## Presenting the results

- Give the brief as the script prints it, lightly tidied: do not drop the source and attribution lines (Open-Meteo,
  DMI and Statistics Denmark require credit, CC BY 4.0).
- Forecasts (weather.py, dmi.py --forecast) and measurements (dmi.py) are different things: say which one a
  number is. Two models can disagree, especially on rain; when they do, say so instead of picking one.
- Headlines: show title, link and age; do not summarize articles you have not read. If the user wants a summary,
  fetch the article first.
- Holidays marked "customary" (Christmas Eve, New Year's Eve, Constitution Day) are not official days off; say so
  when it matters for the answer.
- For a daily brief at a fixed time, the user can schedule `python brief.py` with Windows Task Scheduler or cron,
  or with a scheduled task in Claude if they ask for one.

Market sections (currencies, crypto, stocks, portfolio) follow the markets skill's rules.
