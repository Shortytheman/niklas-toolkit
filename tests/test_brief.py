import json
import sys
from datetime import date

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "packs" / "brief" / "scripts"))
import common  # noqa: E402
import crypto  # noqa: E402
import fx  # noqa: E402
import holidays_dk  # noqa: E402
import news  # noqa: E402
import portfolio  # noqa: E402
import stocks  # noqa: E402
import weather  # noqa: E402
from netfake import install, write_config  # noqa: E402

ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-11-13">
      <Cube currency="USD" rate="1.1052"/><Cube currency="DKK" rate="7.4756"/><Cube currency="SEK" rate="11.10"/>
    </Cube>
    <Cube time="2026-11-12">
      <Cube currency="USD" rate="1.1000"/><Cube currency="DKK" rate="7.4750"/><Cube currency="SEK" rate="11.00"/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""


@pytest.fixture
def net(monkeypatch, tmp_path):
    n = install(monkeypatch, tmp_path)
    n.add("eurofxref", ECB_XML)
    return n


def test_ecb_parse_and_cross_rates(net):
    day, rates, source = fx.latest_rates()
    assert day == "2026-11-13" and source == "ECB euro reference rates"
    assert fx.cross(rates, "USD", "DKK") == pytest.approx(7.4756 / 1.1052)
    assert fx.cross(rates, "EUR", "DKK") == 7.4756
    value, _, _ = fx.convert(100, "usd", "dkk")
    assert value == pytest.approx(100 * 7.4756 / 1.1052)
    with pytest.raises(common.SetupError, match="unknown currency XYZ"):
        fx.cross(rates, "XYZ", "DKK")


def test_fx_falls_back_to_frankfurter(net):
    net.add("eurofxref", (503, {}, b""))
    net.add("frankfurter.dev/v1/latest", {"date": "2026-11-13", "rates": {"DKK": 7.47, "USD": 1.10}})
    day, rates, source = fx.latest_rates()
    assert source.startswith("Frankfurter") and rates["EUR"] == 1.0 and rates["DKK"] == 7.47


def test_crypto_prices_and_kraken_fallback(net, tmp_path):
    net.add("api.coingecko.com/api/v3/simple/price",
            {"bitcoin": {"dkk": 438000.0, "dkk_24h_change": -1.3, "last_updated_at": 1763276520}})
    data, source = crypto.prices(["bitcoin"], "DKK")
    assert source == "CoinGecko" and data["bitcoin"]["price"] == 438000.0
    assert net.calls[-1][3].get("X-cg-demo-api-key") is None
    write_config(tmp_path, {"keys": {"COINGECKO_DEMO_KEY": "demo"}})
    net.add("api.coingecko.com/api/v3/simple/price", (429, {}, b"slow down"))
    net.add("api.kraken.com/0/public/Ticker", {"error": [], "result": {"XXBTZEUR": {"c": ["60000.0", "1"], "o": "61000.0"}}})
    data, source = crypto.prices(["bitcoin"], "EUR")
    assert source == "Kraken (fallback)" and data["bitcoin"]["price"] == 60000.0
    assert any(h.get("X-cg-demo-api-key") == "demo" for _, url, _, h in net.calls if "coingecko" in url)


def test_coin_id_search(net):
    net.add("api.coingecko.com/api/v3/search", {"coins": [{"id": "pepe", "symbol": "PEPE"}]})
    assert crypto.coin_id("btc") == "bitcoin"
    assert crypto.coin_id("pepe") == "pepe"


def test_stocks_need_a_source(net, tmp_path):
    with pytest.raises(common.SetupError, match="no stock data source"):
        stocks.quote("AAPL")
    write_config(tmp_path, {"keys": {"FINNHUB_API_KEY": "k"}})
    assert stocks.providers() == ["finnhub"]


def test_finnhub_then_yahoo(net, tmp_path):
    write_config(tmp_path, {"keys": {"FINNHUB_API_KEY": "k"}, "stocks": {"allow_unofficial_yahoo": True}})
    net.add("finnhub.io/api/v1/quote", {"c": 0, "d": None})           # no data for this symbol
    net.add("query1.finance.yahoo.com/v8/finance/chart/NOVO-B.CO", {"chart": {"result": [{
        "meta": {"regularMarketPrice": 286.4, "chartPreviousClose": 250.0, "currency": "DKK",
                 "regularMarketTime": 1763276580, "exchangeName": "CPH"},
        "timestamp": [1, 2, 3], "indicators": {"quote": [{"close": [270.0, 278.45, 286.4]}]}}]}})
    q = stocks.quote("NOVO-B.CO")
    assert q["source"].startswith("Yahoo, unofficial") and q["currency"] == "DKK"
    assert q["change_pct"] == pytest.approx((286.4 / 278.45 - 1) * 100)  # vs the previous day, not the range start
    assert "token=k" in next(url for _, url, _, _ in net.calls if "finnhub" in url)


def test_describe_and_sparkline():
    st = common.describe([100, 110, 99, 120])
    assert st["change_pct"] == pytest.approx(20.0)
    assert st["max_drawdown_pct"] == pytest.approx((99 / 110 - 1) * 100)
    assert st["low"] == 99 and st["high"] == 120 and "volatility_annual_pct" in st
    line = common.sparkline(list(range(100)), width=10)
    assert len(line) == 10 and line[0] == "▁" and line[-1] == "█"


def test_portfolio(net, tmp_path):
    write_config(tmp_path, {"stocks": {"allow_unofficial_yahoo": True}})
    net.add("query1.finance.yahoo.com/v8/finance/chart/AAPL", {"chart": {"result": [{
        "meta": {"regularMarketPrice": 200.0, "currency": "USD"}, "indicators": {"quote": [{"close": [190, 200]}]}}]}})
    net.add("query1.finance.yahoo.com/v8/finance/chart/GONE", {"chart": {"result": None, "error": {"description": "Not found"}}})
    net.add("api.coingecko.com/api/v3/simple/price", {"bitcoin": {"dkk": 400000.0}})
    csv_file = tmp_path / "h.csv"
    csv_file.write_text("symbol,type,quantity,avg_price,currency\nAAPL,stock,10,100,USD\nbtc,crypto,0.5,300000,DKK\n"
                        "EUR,cash,100,,EUR\nGONE,stock,1,1,USD\n", encoding="utf-8")
    rows = portfolio.read_csv(csv_file)
    valued = {v.row.symbol: v for v in portfolio.value_rows(rows, "DKK")}
    usd_dkk = 7.4756 / 1.1052
    assert valued["AAPL"].value == pytest.approx(2000 * usd_dkk)
    assert valued["AAPL"].cost == pytest.approx(1000 * usd_dkk)
    assert valued["btc"].value == pytest.approx(200000.0)
    assert valued["EUR"].value == pytest.approx(747.56)
    assert valued["GONE"].value is None and "Not found" in valued["GONE"].error


def test_portfolio_csv_errors(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("symbol,type,quantity,currency\nAAPL,bond,1,USD\n", encoding="utf-8")
    with pytest.raises(common.SetupError, match="type must be stock, crypto or cash"):
        portfolio.read_csv(bad)
    with pytest.raises(common.SetupError, match="not found"):
        portfolio.read_csv(tmp_path / "missing.csv")


@pytest.mark.parametrize("year,easter", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
                                         (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)),
                                         (2038, date(2038, 4, 25))])
def test_easter(year, easter):
    assert holidays_dk.easter(year) == easter


def test_danish_holidays():
    names_2023 = [n for _, n, _ in holidays_dk.holidays(2023)]
    names_2024 = [n for _, n, _ in holidays_dk.holidays(2024)]
    assert any("Store bededag" in n for n in names_2023)
    assert not any("Store bededag" in n for n in names_2024)   # abolished from 2024
    official = {d for d, _, o in holidays_dk.holidays(2026) if o}
    assert date(2026, 5, 14) in official                       # Ascension: Easter + 39
    assert date(2026, 12, 24) not in official                  # Christmas Eve is customary
    assert holidays_dk.workdays(date(2026, 12, 1), date(2026, 12, 31)) == 22
    assert holidays_dk.workdays(date(2026, 12, 1), date(2026, 12, 31), customary=True) == 20


RSS = """<rss version="2.0"><channel><title>t</title>
<item><title>Old &amp; boring</title><link>https://x/1</link><pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title><![CDATA[New <b>thing</b>]]></title><link>https://x/2</link><pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><title>r</title>
<entry><title>v2.0</title><link rel="alternate" href="https://gh/v2"/><updated>2026-11-14T08:00:00Z</updated></entry>
<entry><title>v1.0</title><link href="https://gh/v1"/><updated>2026-01-01T08:00:00Z</updated></entry>
</feed>"""


def test_feeds():
    rss = news.parse_feed(RSS)
    assert [e["title"] for e in rss] == ["New thing", "Old & boring"]
    atom = news.parse_feed(ATOM)
    assert atom[0]["title"] == "v2.0" and atom[0]["link"] == "https://gh/v2" and atom[1]["link"] == "https://gh/v1"


def test_hn_top(net):
    net.add("hacker-news.firebaseio.com/v0/topstories.json", [11, 22])
    net.add("v0/item/11.json", {"id": 11, "title": "A", "url": "https://a", "score": 50})
    net.add("v0/item/22.json", {"id": 22, "title": "Ask HN", "score": 9})
    top = news.hn_top(2)
    assert [s["title"] for s in top] == ["A", "Ask HN"]
    assert top[1]["url"] == "https://news.ycombinator.com/item?id=22"


def test_weather_summary(net, tmp_path):
    write_config(tmp_path, {"location": {"name": "Home", "lat": 55.67612345, "lon": 12.5683}})
    net.add("api.open-meteo.com/v1/forecast", {
        "current": {"temperature_2m": 8.9, "apparent_temperature": 6.5, "weather_code": 51, "wind_speed_10m": 3.7,
                    "wind_gusts_10m": 7.2},
        "daily": {"time": ["2026-11-16"], "weather_code": [61], "temperature_2m_max": [9.2],
                  "temperature_2m_min": [6.3], "precipitation_sum": [9.6], "precipitation_probability_max": [100],
                  "wind_speed_10m_max": [6.0], "sunrise": ["2026-11-16T07:46"], "sunset": ["2026-11-16T16:01"]}})
    lines = weather.summary(None, 1)
    assert lines[0].startswith("Home: 8.9°C") and "light drizzle" in lines[0]
    assert "light rain" in lines[1] and "07:46-16:01" in lines[1]
    url = next(u for _, u, _, _ in net.calls if "forecast" in u)
    assert "latitude=55.6761&" in url   # 4 decimals, as weather services ask


def test_brief_survives_a_failing_section(net, tmp_path, capsys, monkeypatch):
    import brief
    write_config(tmp_path, {"brief": {"sections": ["holidays", "fx", "crypto"]}, "watchlist": {"crypto": ["btc"]}})
    net.add("api.coingecko.com", (500, {}, b"boom"))
    monkeypatch.setattr(sys, "argv", ["brief.py"])
    assert brief.main() == 0
    out = capsys.readouterr().out
    assert "Next holiday:" in out and "DKK: EUR 7.4756" in out
    assert "crypto: unavailable" in out
    assert common.DISCLAIMER in out


PRIS01_INFO = {"id": "PRIS01", "text": "Consumer price index", "unit": "-", "updated": "2026-11-10T08:00:00",
               "active": True, "variables": [
                   {"id": "VAREGR", "text": "commodity group", "elimination": True, "time": False,
                    "values": [{"id": "000000", "text": "00 Consumer price index, total"}]},
                   {"id": "ENHED", "text": "unit", "elimination": False, "time": False,
                    "values": [{"id": "100", "text": "Index"}, {"id": "300", "text": "Percentage change y/y"}]},
                   {"id": "Tid", "text": "time", "elimination": False, "time": True,
                    "values": [{"id": "2026M08", "text": "2026M08"}]}]}
PRIS01_CSV = ("﻿VAREGR;ENHED;TID;INDHOLD\n"
              "00 total;Percentage change y/y;2026M07;1.70\n00 total;Percentage change y/y;2026M08;2.00\n"
              "00 total;Percentage change y/y;2026M09;..\n00 total;Percentage change y/y;2026M10;2.20\n")


@pytest.fixture
def statbank(net):
    net.add("api.statbank.dk/v1/tableinfo/PRIS01", PRIS01_INFO)
    net.add("api.statbank.dk/v1/tableinfo/NOPE", (400, {}, b'{"message":"table not found"}'))
    net.add("api.statbank.dk/v1/data", lambda req: (200, {}, PRIS01_CSV.encode()))
    net.add("api.statbank.dk/v1/tables", [{"id": "AUF01", "text": "Unemployed persons (provisional)", "active": True,
                                           "variables": ["region", "time"]},
                                          {"id": "PRIS113", "text": "Consumer price index", "active": False,
                                           "variables": ["type", "time"]}])
    return net


def test_dk_stats_fetch(statbank):
    import dk_stats
    meta, rows = dk_stats.fetch("PRIS01", {"VAREGR": "000000", "ENHED": "300"}, 3)
    assert [r["TID"] for r in rows] == ["2026M08", "2026M09", "2026M10"]
    assert [dk_stats.number(r["INDHOLD"]) for r in rows] == [2.0, None, 2.2]   # ".." is missing
    body = json.loads(next(d for m, u, d, h in statbank.calls if u.endswith("/v1/data")))
    assert {"code": "Tid", "values": ["*"]} in body["variables"]


def test_dk_stats_errors(statbank):
    import dk_stats
    with pytest.raises(common.SetupError, match="needs a value for ENHED"):
        dk_stats.fetch("PRIS01", {}, 3)
    with pytest.raises(common.SetupError, match="unknown code"):
        dk_stats.fetch("PRIS01", {"ENHED": "999"}, 3)
    with pytest.raises(common.SetupError, match="no table called NOPE"):
        dk_stats.fetch("NOPE", {}, 3)


def test_dk_stats_search(statbank, capsys, monkeypatch):
    import dk_stats
    monkeypatch.setattr(sys, "argv", ["dk_stats.py", "search", "consumer"])
    assert dk_stats.main() == 0
    out = capsys.readouterr().out
    assert "PRIS113" in out and "no longer updated" in out and "AUF01" not in out


def test_brief_inflation_section(statbank, tmp_path, capsys, monkeypatch):
    import brief
    monkeypatch.setattr(sys, "argv", ["brief.py", "--only", "inflation"])
    assert brief.main() == 0
    assert "Danish inflation: 2.2% in 2026M10" in capsys.readouterr().out


DMI_STATIONS = {"features": [
    {"geometry": {"coordinates": [12.5683, 55.6800]}, "properties": {"stationId": "06186", "name": "Near", "validTo": None,
                                                                    "parameterId": ["temp_dry", "humidity"]}},
    {"geometry": {"coordinates": [12.6454, 55.6140]}, "properties": {"stationId": "06180", "name": "Airport", "validTo": None,
                                                                    "parameterId": ["temp_dry", "wind_speed", "precip_past1h"]}},
    {"geometry": {"coordinates": [12.6454, 55.6140]}, "properties": {"stationId": "06180", "name": "Old", "validTo": "2020-01-01",
                                                                    "parameterId": ["temp_dry"]}},
    {"geometry": {"coordinates": [9.0, 56.0]}, "properties": {"stationId": "06060", "name": "Far full", "validTo": None,
                                                             "parameterId": ["temp_dry", "wind_speed", "precip_past1h"]}},
]}
DMI_OBS = {"features": [
    {"properties": {"parameterId": "temp_dry", "value": 9.43, "observed": "2026-11-16T14:00:00Z"}},
    {"properties": {"parameterId": "temp_dry", "value": 9.38, "observed": "2026-11-16T14:10:00Z"}},
    {"properties": {"parameterId": "wind_speed", "value": 4.06, "observed": "2026-11-16T14:10:00Z"}},
    {"properties": {"parameterId": "humidity", "value": 95.6, "observed": "2026-11-16T14:10:00Z"}},
]}


def test_dmi_prefers_full_station_and_newest_values(net, tmp_path):
    import dmi
    write_config(tmp_path, {"location": {"name": "Home", "lat": 55.6761, "lon": 12.5683}})
    net.add("opendataapi.dmi.dk/v2/metObs/collections/station/items", DMI_STATIONS)
    net.add("opendataapi.dmi.dk/v2/metObs/collections/observation/items", DMI_OBS)
    station, dist = dmi.nearest(55.6761, 12.5683)
    assert station["id"] == "06180" and 7 < dist < 10       # full station within the detour beats the nearest one
    lines = dmi.summary()
    assert lines[0].startswith("DMI Airport (06180,")
    assert "temperature 9.4°C" in lines[1] and "humidity 96%" in lines[1] and "wind 4.1 m/s" in lines[1]
    by_id = dmi.summary(station_id="06180")[0]
    assert by_id.startswith("DMI Airport (06180)") and "km away" not in by_id


def test_dmi_outside_denmark(net, tmp_path):
    import dmi
    write_config(tmp_path, {"location": {"name": "Berlin", "lat": 52.52, "lon": 13.40}})
    net.add("opendataapi.dmi.dk/v2/metObs/collections/station/items", DMI_STATIONS)
    with pytest.raises(common.SetupError, match="DMI covers Denmark"):
        dmi.summary()


def test_dmi_forecast(net, tmp_path):
    import dmi
    from datetime import datetime, timedelta, timezone
    write_config(tmp_path, {"location": {"name": "Home", "lat": 55.6761, "lon": 12.5683}})
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    steps = [now + timedelta(hours=h) for h in range(-3, 30)]
    features = [{"properties": {"step": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "temperature-2m": 273.15 + i,
                                "wind-speed": 2.0, "total-precipitation": 0.5 * i}} for i, t in enumerate(steps)]
    net.add("forecastedr/collections/harmonie_dini_sf/position", {"type": "FeatureCollection", "features": features})
    rows = dmi.forecast(55.6761, 12.5683)
    assert rows[0]["temp_c"] == pytest.approx(0.0) and rows[1]["precip_mm"] == pytest.approx(0.5)  # Kelvin, per hour
    lines = dmi.forecast_lines()
    assert lines[0] == "DMI HARMONIE forecast for Home:"
    first_hour = float(lines[1].split("°C")[0].split()[-1])
    assert first_hour >= 2.0          # the hours before now - 1 h are skipped
    url = next(u for _, u, _, _ in net.calls if "forecastedr" in u)
    assert "POINT%2812.5683+55.6761%29" in url or "POINT(12.5683 55.6761)" in urllib_unquote(url)


def urllib_unquote(url):
    import urllib.parse
    return urllib.parse.unquote_plus(url)
