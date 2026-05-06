from __future__ import annotations

import json
from io import StringIO
import re
import sys
from datetime import timezone
from datetime import datetime
from urllib.parse import urljoin
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup


SOURCE_URL = (
    "https://goodinfo.tw/tw/StockList.asp?"
    "INDUSTRY_CAT=%E6%88%90%E4%BA%A4%E5%BC%B5%E6%95%B8+%28%E9%AB%98%E2%86%92%E4%BD%8E%29"
    "%40%40%E6%88%90%E4%BA%A4%E5%BC%B5%E6%95%B8%40%40%E7%94%B1%E9%AB%98%E2%86%92%E4%BD%8E&"
    "MARKET_CAT=%E7%86%B1%E9%96%80%E6%8E%92%E8%A1%8C"
)
DATA_QUERY = (
    "MARKET_CAT=%E7%86%B1%E9%96%80%E6%8E%92%E8%A1%8C&"
    "INDUSTRY_CAT=%E6%88%90%E4%BA%A4%E5%BC%B5%E6%95%B8+%28%E9%AB%98%E2%86%92%E4%BD%8E%29"
    "%40%40%E6%88%90%E4%BA%A4%E5%BC%B5%E6%95%B8%40%40%E7%94%B1%E9%AB%98%E2%86%92%E4%BD%8E&"
    "SHEET=%E4%BA%A4%E6%98%93%E7%8B%80%E6%B3%81&"
    "SHEET2=%E6%97%A5&"
    "RPT_TIME=%E6%9C%80%E6%96%B0%E8%B3%87%E6%96%99&"
    "RANK_RANGE=300"
)
DATA_URL = f"https://goodinfo.tw/tw/StockList.asp?STEP=DATA&{DATA_QUERY}"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"
JSON_PATH = OUTPUT_DIR / "goodinfo_top_volume.json"
ERROR_PATH = OUTPUT_DIR / "goodinfo_top_volume_error.txt"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

EXCLUDE_KEYWORDS = [
    "ETF",
    "ETN",
    "基金",
    "債",
    "主動",
    "高息",
    "高股息",
    "投資級債",
    "公司債",
    "金融債",
    "臺灣高息",
    "台灣高息",
    "權證",
    "購",
    "售",
    "特別股",
]
REQUIRED_KEYS = {"stock_id", "stock_name", "close", "change", "change_pct", "volume"}


def decode_response_content(response: requests.Response) -> str:
    encodings: list[str] = []
    if response.apparent_encoding:
        encodings.append(response.apparent_encoding)
    encodings.extend(["big5", "cp950", "utf-8"])

    raw = response.content
    html = ""
    for encoding in encodings:
        try:
            html = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    return html or response.text


def fetch_html() -> str:
    session = requests.Session()
    response = session.get(SOURCE_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    html = decode_response_content(response)

    match = re.search(r"window\.location\.replace\('([^']+)'\)", html)
    if match:
        seed_match = re.search(
            r"'([0-9.]+\|[0-9.]+\|[0-9.]+\|)'\s*\+\s*String\(GetTimezoneOffset\(\)\)\s*\+",
            html,
        )
        if seed_match:
            offset_minutes = int(
                -(datetime.now().astimezone().utcoffset() or timezone.utc.utcoffset(None)).total_seconds()
                / 60
            )
            excel_days = (
                datetime.now().astimezone().timestamp() / 86400
                - offset_minutes / 1440
                + 25569
            )
            client_key = (
                f"{seed_match.group(1)}{offset_minutes}|"
                f"{excel_days}|{excel_days}|0"
            )
            session.cookies.set("CLIENT_KEY", client_key, domain="goodinfo.tw", path="/")

        redirect_url = urljoin(response.url, match.group(1))
        session.get(
            redirect_url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": response.url,
            },
            timeout=30,
        ).raise_for_status()

    data_response = session.get(
        DATA_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": f"https://goodinfo.tw/tw/StockList.asp?{DATA_QUERY}",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    data_response.raise_for_status()
    return decode_response_content(data_response)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(part).strip() for part in col if str(part).strip())
            for col in df.columns.to_flat_index()
        ]
    else:
        df.columns = [str(col).strip() for col in df.columns]
    return df


def strip_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def parse_stock_cell(value: Any) -> tuple[str, str]:
    text = strip_text(value)
    match = re.search(r"(\d{4})\s+(.+)", text)
    if match:
        return match.group(1), match.group(2).strip()
    return "", text


def find_column(columns: list[str], keywords: list[str]) -> str | None:
    lowered = [(col, col.lower()) for col in columns]
    for col, lowered_col in lowered:
        if all(keyword in lowered_col for keyword in keywords):
            return col
    return None


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    df = normalize_columns(df.copy())
    columns = list(df.columns)

    stock_id_col = find_column(columns, ["代號"])
    stock_name_col = find_column(columns, ["名稱"])
    volume_col = find_column(columns, ["成交", "張"])
    close_col = find_column(columns, ["成交"]) or find_column(columns, ["收盤"])
    change_col = find_column(columns, ["漲跌", "價"]) or find_column(columns, ["漲跌"])
    change_pct_col = find_column(columns, ["漲跌", "幅"])
    market_col = find_column(columns, ["市場"]) or find_column(columns, ["市", "場"])
    rank_col = find_column(columns, ["排名"])

    if not stock_id_col or not stock_name_col or not volume_col or not close_col or not change_col:
        return []

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        stock_id = strip_text(row.get(stock_id_col))
        stock_name = strip_text(row.get(stock_name_col))
        if not stock_id or not stock_name:
            continue

        record = {
            "rank": strip_text(row.get(rank_col)) if rank_col else "",
            "stock_id": stock_id,
            "stock_name": stock_name,
            "market": strip_text(row.get(market_col)) if market_col else "",
            "close": strip_text(row.get(close_col)),
            "change": strip_text(row.get(change_col)),
            "change_pct": strip_text(row.get(change_pct_col)) if change_pct_col else "",
            "volume": strip_text(row.get(volume_col)),
            "raw": {col: strip_text(row.get(col)) for col in columns},
        }
        if REQUIRED_KEYS.issubset(record):
            records.append(record)
    return records


def parse_with_pandas(html: str) -> list[dict[str, Any]]:
    frames = pd.read_html(StringIO(html), flavor=["lxml"])
    best: list[dict[str, Any]] = []
    for frame in frames:
        records = dataframe_to_records(frame)
        if len(records) > len(best):
            best = records
    return best


def parse_table_rows(table: Any) -> list[dict[str, Any]]:
    headers = [cell.get_text(" ", strip=True) for cell in table.select("tr th")]
    if not headers:
        first_row = table.select_one("tr")
        if not first_row:
            return []
        headers = [cell.get_text(" ", strip=True) for cell in first_row.select("th, td")]

    rows: list[list[str]] = []
    for tr in table.select("tr"):
        cells = tr.select("td")
        if not cells:
            continue
        row = [cell.get_text(" ", strip=True) for cell in cells]
        if len(row) == len(headers):
            rows.append(row)

    if not rows:
        return []

    frame = pd.DataFrame(rows, columns=headers)
    return dataframe_to_records(frame)


def parse_with_bs4(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    best: list[dict[str, Any]] = []
    for table in soup.select("table"):
        records = parse_table_rows(table)
        if len(records) > len(best):
            best = records
    return best


def should_exclude(stock_id: str, stock_name: str) -> bool:
    if stock_id.startswith("00"):
        return True
    normalized_name = stock_name.upper()
    return any(keyword.upper() in normalized_name for keyword in EXCLUDE_KEYWORDS)


def build_output(stocks: list[dict[str, Any]]) -> dict[str, Any]:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload_stocks = []
    for index, stock in enumerate(stocks[:10], start=1):
        payload_stocks.append(
            {
                "rank": index,
                "stock_id": stock["stock_id"],
                "stock_name": stock["stock_name"],
                "market": stock["market"],
                "close": format_number_text(stock["close"]),
                "change": format_signed_number_text(stock["change"]),
                "change_pct": format_percent_text(stock["change_pct"]),
                "volume": format_integer_text(stock["volume"]),
                "raw": stock["raw"],
            }
        )

    return {
        "source": "goodinfo",
        "ranking": "top_volume_ex_etf",
        "generated_at": generated_at,
        "count": len(payload_stocks),
        "stocks": payload_stocks,
    }


def parse_float(value: str) -> float:
    cleaned = value.replace(",", "").replace("%", "").strip()
    if cleaned in {"", "nan", "None"}:
        return 0.0
    return float(cleaned)


def format_number_text(value: str) -> str:
    if value == "":
        return ""
    return f"{parse_float(value):.2f}"


def format_signed_number_text(value: str) -> str:
    if value == "":
        return ""
    number = parse_float(value)
    return f"{number:.2f}".rstrip("0").rstrip(".") if number % 1 else f"{int(number)}"


def format_percent_text(value: str) -> str:
    if value == "":
        return ""
    return f"{parse_float(value):.2f}%"


def format_integer_text(value: str) -> str:
    return f"{int(parse_float(value)):,}"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if ERROR_PATH.exists():
        ERROR_PATH.unlink()

    try:
        html = fetch_html()
        try:
            records = parse_with_pandas(html)
        except ValueError:
            records = []

        if not records:
            records = parse_with_bs4(html)

        filtered = [
            stock
            for stock in records
            if not should_exclude(stock["stock_id"], stock["stock_name"])
        ]
        if not filtered:
            raise RuntimeError("No eligible stocks found after filtering.")

        filtered.sort(key=lambda stock: parse_float(stock["volume"]), reverse=True)

        payload = build_output(filtered)
        JSON_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("Top volume stocks:")
        for stock in payload["stocks"]:
            print(
                f"{stock['rank']}. {stock['stock_id']} {stock['stock_name']} "
                f"vol={stock['volume']} close={stock['close']} pct={stock['change_pct']}"
            )
        return 0
    except Exception as error:
        ERROR_PATH.write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
        print(f"Fetch failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
