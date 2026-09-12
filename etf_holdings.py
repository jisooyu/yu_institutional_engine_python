"""Official benchmark ETF holdings retrieval with a resilient local cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
from typing import Any, Callable
import warnings

from lxml import etree
import pandas as pd
import requests


ETF_SOURCES = {
    "Semiconductor": {
        "etf": "SMH", "issuer": "VanEck",
        "url": "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/downloads/holdings/",
        "parser": "vaneck",
    },
    "AI": {
        "etf": "BOTZ", "issuer": "Global X",
        "url": "https://www.globalxetfs.com/funds/botz?download_full_holdings=true",
        "parser": "global_x",
    },
    "Software": {
        "etf": "IGV", "issuer": "iShares",
        "url": "https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/get-fund-document?appSubType=ISHARES&appType=PRODUCT_PAGE&component=fundDownload&locale=en_US&portfolioId=239771&targetSite=us-ishares&userType=individual",
        "parser": "ishares",
    },
    "Cyber Security": {
        "etf": "CIBR", "issuer": "First Trust",
        "url": "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=CIBR",
        "parser": "first_trust",
    },
    "Power": {
        "etf": "GRID", "issuer": "First Trust",
        "url": "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=GRID",
        "parser": "first_trust",
    },
    "Defense": {
        "etf": "ITA", "issuer": "iShares",
        "url": "https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/get-fund-document?appSubType=ISHARES&appType=PRODUCT_PAGE&component=fundDownload&locale=en_US&portfolioId=239502&targetSite=us-ishares&userType=individual",
        "parser": "ishares",
    },
}

FALLBACK_HOLDINGS = {
    "Semiconductor": [
        ("NVDA", "NVIDIA"), ("AVGO", "Broadcom"), ("TSM", "TSMC"), ("MU", "Micron"),
        ("AMD", "AMD"), ("QCOM", "Qualcomm"), ("AMAT", "Applied Materials"), ("LRCX", "Lam Research"),
    ],
    "AI": [
        ("NVDA", "NVIDIA"), ("AVGO", "Broadcom"), ("TSM", "TSMC"), ("MU", "Micron"),
        ("DELL", "Dell Technologies"), ("010120.KS", "LS ELECTRIC"), ("SOXX", "iShares Semiconductor ETF"), ("GEV", "GE Vernova"),
    ],
    "Software": [
        ("MSFT", "Microsoft"), ("ORCL", "Oracle"), ("CRM", "Salesforce"), ("NOW", "ServiceNow"),
        ("ADBE", "Adobe"), ("INTU", "Intuit"), ("SNOW", "Snowflake"), ("DDOG", "Datadog"),
    ],
    "Cyber Security": [
        ("PANW", "Palo Alto Networks"), ("CRWD", "CrowdStrike"), ("FTNT", "Fortinet"), ("ZS", "Zscaler"),
        ("OKTA", "Okta"), ("NET", "Cloudflare"), ("CHKP", "Check Point"), ("GEN", "Gen Digital"),
    ],
    "Power": [
        ("GEV", "GE Vernova"), ("VRT", "Vertiv"), ("CEG", "Constellation Energy"), ("NEE", "NextEra Energy"),
        ("ETN", "Eaton"), ("PWR", "Quanta Services"), ("VST", "Vistra"), ("HUBB", "Hubbell"),
    ],
    "Defense": [
        ("RTX", "RTX"), ("LMT", "Lockheed Martin"), ("NOC", "Northrop Grumman"), ("GD", "General Dynamics"),
        ("LHX", "L3Harris"), ("TDG", "TransDigm"), ("HII", "Huntington Ingalls"), ("BA", "Boeing"),
    ],
}

_CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "etf_holdings.json"
_CACHE_TTL = timedelta(hours=18)
_MEMORY_CACHE: dict[str, Any] | None = None
_HEADERS = {"User-Agent": "Mozilla/5.0 (Institutional Flow Dashboard; holdings research)"}


def _weight(value: Any) -> float:
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _normalize_ticker(value: Any) -> str:
    ticker = str(value).strip().upper().replace(" ", " ")
    if not ticker or ticker in {"NAN", "--", "-", "CASH", "USD"}:
        return ""
    ticker = re.sub(r"\s+", " ", ticker)
    if "$" in ticker or "INDEX" in ticker:
        return ""
    suffixes = {
        "US": "", "JP": ".T", "SW": ".SW", "LN": ".L", "GR": ".DE", "GY": ".DE",
        "FP": ".PA", "IM": ".MI", "CT": ".TO", "CN": ".TO", "AU": ".AX",
        "KS": ".KS", "BZ": ".SA", "NA": ".AS", "HK": ".HK", "SS": ".ST",
        "NO": ".OL", "DC": ".CO", "C2": ".SZ", "C1": ".SS", "TT": ".TW", "SE": ".SW",
        "SM": ".MC", "BB": ".BR", "TI": ".IS", "PL": ".LS", "AV": ".VI",
        "GA": ".AT", "FH": ".HE",
    }
    parts = ticker.split(" ")
    if len(parts) == 2 and parts[1] in suffixes:
        separator = "-" if parts[1] in {"CT", "CN"} else ""
        ticker = parts[0].replace("/", separator) + suffixes[parts[1]]
    elif len(parts) > 1:
        return ""
    else:
        dotted = re.match(r"^(.+?)\.([A-Z]{2})$", ticker)
        if dotted and dotted.group(2) in suffixes:
            separator = "-" if dotted.group(2) in {"CT", "CN"} else ""
            ticker = dotted.group(1).replace("/", separator) + suffixes[dotted.group(2)]
    ticker = ticker.replace("BRK.B", "BRK-B").replace("BF.B", "BF-B")
    ticker = {
        "HEIA": "HEI-A",
        "HEI/A": "HEI-A",
        "MOGA": "MOG-A",
        "MOG/A": "MOG-A",
    }.get(ticker, ticker)
    return ticker


def _renormalize_cached_holdings(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply current Yahoo ticker rules to holdings saved by older releases."""
    for sector in payload.get("sectors", {}).values():
        for holding in sector.get("holdings", []):
            official_ticker = holding.get("official_ticker", holding.get("ticker", ""))
            normalized = _normalize_ticker(official_ticker)
            if normalized:
                holding["ticker"] = normalized
    return payload


def _rows(frame: pd.DataFrame, ticker_col: str, name_col: str, weight_col: str) -> list[dict[str, Any]]:
    holdings = []
    for _, row in frame.iterrows():
        official_ticker = str(row.get(ticker_col, "")).strip()
        ticker = _normalize_ticker(official_ticker)
        name = str(row.get(name_col, "")).strip()
        weight = _weight(row.get(weight_col))
        if not ticker or not name or name.lower() == "nan" or weight <= 0:
            continue
        holdings.append({"ticker": ticker, "official_ticker": official_ticker, "name": name, "weight": weight})
    unique: dict[str, dict[str, Any]] = {}
    for row in holdings:
        if row["ticker"] not in unique or row["weight"] > unique[row["ticker"]]["weight"]:
            unique[row["ticker"]] = row
    return sorted(unique.values(), key=lambda row: row["weight"], reverse=True)


def _fetch_vaneck(source: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    response = requests.get(source["url"], headers=_HEADERS, timeout=45)
    response.raise_for_status()
    # VanEck's generated workbook omits Excel's optional default style.  The
    # values are valid, so suppress only openpyxl's narrowly-scoped warning.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style, apply openpyxl's default",
            category=UserWarning,
            module=r"openpyxl\.styles\.stylesheet",
        )
        frame = pd.read_excel(BytesIO(response.content), header=2)
    if "Asset Class" in frame:
        frame = frame[frame["Asset Class"].astype(str).str.lower().eq("stock")]
    filename = response.headers.get("content-disposition", "")
    match = re.search(r"asof_(\d{8})", filename)
    as_of = datetime.strptime(match.group(1), "%Y%m%d").date().isoformat() if match else "Unknown"
    return _rows(frame, "Ticker", "Holding Name", "% of Net Assets"), as_of


def _fetch_global_x(source: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    page = requests.get(source["url"], headers=_HEADERS, timeout=45)
    page.raise_for_status()
    match = re.search(r'https://assets\.globalxetfs\.com/funds/holdings/[^"\']+\.csv', page.text, re.I)
    if not match:
        raise RuntimeError("Global X official holdings CSV link was not found")
    csv_url = match.group(0)
    response = requests.get(csv_url, headers=_HEADERS, timeout=45)
    response.raise_for_status()
    frame = pd.read_csv(BytesIO(response.content), skiprows=2)
    ticker_col = next(column for column in frame.columns if str(column).strip().lower() == "ticker")
    name_col = next(column for column in frame.columns if str(column).strip().lower() == "name")
    weight_col = next(column for column in frame.columns if "net assets" in str(column).lower() or "weight" in str(column).lower())
    match = re.search(r"_(\d{8})\.csv", csv_url)
    as_of = datetime.strptime(match.group(1), "%Y%m%d").date().isoformat() if match else "Unknown"
    return _rows(frame, ticker_col, name_col, weight_col), as_of


def _fetch_first_trust(source: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    response = requests.get(source["url"], headers=_HEADERS, timeout=45)
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    frame = next(table for table in tables if len(table) > 2 and "Identifier" in set(table.iloc[0].astype(str)))
    frame.columns = frame.iloc[0]
    frame = frame.iloc[1:].copy()
    match = re.search(r"as of\s*(\d{1,2}/\d{1,2}/\d{4})", response.text, re.I)
    as_of = datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat() if match else "Unknown"
    return _rows(frame, "Identifier", "Security Name", "Weighting"), as_of


def _fetch_ishares(source: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    response = requests.get(source["url"], headers=_HEADERS, timeout=60)
    response.raise_for_status()
    root = etree.fromstring(response.content, etree.XMLParser(recover=True))
    namespace = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}
    worksheet = next(
        node for node in root.xpath(".//ss:Worksheet", namespaces=namespace)
        if node.get("{urn:schemas-microsoft-com:office:spreadsheet}Name") == "Holdings"
    )
    rows = [[data.text for data in row.xpath(".//ss:Data", namespaces=namespace)] for row in worksheet.xpath(".//ss:Row", namespaces=namespace)]
    header_index = next(index for index, row in enumerate(rows) if row and row[0] == "Ticker")
    header = rows[header_index]
    records = [dict(zip(header, row)) for row in rows[header_index + 1:] if row and len(row) >= 6]
    frame = pd.DataFrame(records)
    if "Asset Class" in frame:
        frame = frame[frame["Asset Class"].astype(str).str.lower().eq("equity")]
    as_of_row = next((row for row in rows[:header_index] if row and row[0] == "Fund Holdings as of"), None)
    as_of = datetime.strptime(as_of_row[1], "%b %d, %Y").date().isoformat() if as_of_row else "Unknown"
    return _rows(frame, "Ticker", "Name", "Weight (%)"), as_of


_PARSERS: dict[str, Callable[[dict[str, str]], tuple[list[dict[str, Any]], str]]] = {
    "vaneck": _fetch_vaneck,
    "global_x": _fetch_global_x,
    "first_trust": _fetch_first_trust,
    "ishares": _fetch_ishares,
}


def _fallback(sector: str, error: str) -> dict[str, Any]:
    rows = [
        {"ticker": ticker, "official_ticker": ticker, "name": name, "weight": round(100 / len(FALLBACK_HOLDINGS[sector]), 2)}
        for ticker, name in FALLBACK_HOLDINGS[sector]
    ]
    source = ETF_SOURCES[sector]
    return {
        "etf": source["etf"], "issuer": source["issuer"], "source_url": source["url"],
        "as_of": "Fallback", "holdings": rows, "fallback": True, "error": error,
    }


def _read_cache() -> dict[str, Any] | None:
    try:
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at < _CACHE_TTL:
            return _renormalize_cached_holdings(payload)
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        return None
    return None


def fetch_official_holdings(force: bool = False) -> dict[str, Any]:
    """Return official holdings for all benchmark ETFs, cached for 18 hours."""
    global _MEMORY_CACHE
    if not force and _MEMORY_CACHE:
        return _MEMORY_CACHE["sectors"]
    cached = None if force else _read_cache()
    if cached:
        _MEMORY_CACHE = cached
        return cached["sectors"]

    stale: dict[str, Any] = {}
    try:
        if _CACHE_PATH.exists():
            cached_payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            stale = _renormalize_cached_holdings(cached_payload).get("sectors", {})
    except (OSError, ValueError, json.JSONDecodeError):
        stale = {}

    sectors: dict[str, Any] = {}
    for sector, source in ETF_SOURCES.items():
        try:
            holdings, as_of = _PARSERS[source["parser"]](source)
            if len(holdings) < 4:
                raise RuntimeError(f"Only {len(holdings)} equity holdings were returned")
            sectors[sector] = {
                "etf": source["etf"], "issuer": source["issuer"], "source_url": source["url"],
                "as_of": as_of, "holdings": holdings, "fallback": False, "error": "",
            }
        except Exception as exc:
            if sector in stale and stale[sector].get("holdings"):
                sectors[sector] = dict(stale[sector])
                sectors[sector]["error"] = f"Official refresh failed; cached holdings used: {exc}"
            else:
                sectors[sector] = _fallback(sector, str(exc))

    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(), "sectors": sectors}
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _MEMORY_CACHE = payload
    return sectors
