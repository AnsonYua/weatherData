#!/usr/bin/env python3
import argparse
import json
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

from extract_weather_json import clean_forecast_html, normalize_schema


CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

WEEKDAYS = {
    "一": "Monday",
    "二": "Tuesday",
    "三": "Wednesday",
    "四": "Thursday",
    "五": "Friday",
    "六": "Saturday",
    "日": "Sunday",
    "天": "Sunday",
}

ENGLISH_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}

ENGLISH_WEEKDAYS = {
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
}

RAIN_PROBABILITY = {
    "低": "Low",
    "中低": "Medium Low",
    "中": "Medium",
    "中高": "Medium High",
    "高": "High",
}

DATE_HEADER_RE = re.compile(
    r"(?P<month>[一二三四五六七八九十]+)月(?P<day>[一二三四五六七八九十]+)日\s*"
    r"\(\s*星期(?P<weekday>[一二三四五六日天])\s*\)"
)

ENGLISH_DATE_HEADER_RE = re.compile(
    r"(?P<day>\d{1,2})/(?P<month>\d{1,2})\s*\((?P<weekday>[A-Za-z]+)\)"
)


def chinese_number_to_int(value: str) -> int:
    if value in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[value]
    if value.startswith("十"):
        return 10 + CHINESE_NUMBERS.get(value[1:], 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return CHINESE_NUMBERS[left] * 10 + CHINESE_NUMBERS.get(right, 0)
    raise ValueError(f"Unsupported Chinese number: {value}")


def compact_text(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", value)
    value = re.sub(r"\s+([，。；：、])", r"\1", value)
    value = re.sub(r"([，。；：、])\s+", r"\1", value)
    return value.strip()


def parse_report_datetime(pub_date: str) -> str | None:
    if not pub_date:
        return None
    dt = parsedate_to_datetime(pub_date)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_rss_item(path: Path) -> tuple[str, str, str]:
    xml_text = path.read_text(encoding="utf-8")
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS channel not found")
    item = channel.find("item")
    if item is None:
        raise ValueError("RSS item not found")

    title = item.findtext("title", "").strip()
    pub_date = item.findtext("pubDate", "").strip()
    description = clean_forecast_html(item.findtext("description", ""))
    return title, pub_date, description


def infer_report_year_month(title: str, report_datetime: str | None) -> tuple[int, int]:
    match = re.search(r"(\d{4})年(\d{1,2})月", title)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d{1,2})/([A-Za-z]{3})/(\d{4})", title)
    if match:
        month = parsedate_to_datetime(f"01 {match.group(2)} {match.group(3)} 00:00 GMT").month
        return int(match.group(3)), month
    if report_datetime:
        return int(report_datetime[:4]), int(report_datetime[5:7])
    raise ValueError("Could not infer report year/month")


def infer_chinese_weather_type(weather_text: str) -> str:
    text = weather_text
    has_thunder = "雷暴" in text
    has_rain = any(token in text for token in ("雨", "驟雨", "毛毛雨"))
    has_fog = any(token in text for token in ("霧", "薄霧", "煙霞", "能見度低"))
    has_sun = any(token in text for token in ("陽光", "天晴", "晴朗", "普遍晴朗"))
    has_cloud = any(token in text for token in ("多雲", "密雲", "陰天", "大致多雲"))

    if has_thunder:
        return "Mixed" if has_sun or has_cloud or has_rain else "Thunderstorm"
    if has_fog:
        return "Mixed" if has_sun or has_cloud or has_rain else "Fog"
    if has_rain:
        return "Mixed" if has_sun or has_cloud else "Rain"
    if has_sun:
        return "Sunny"
    if has_cloud:
        return "Cloudy"
    return "Unknown"


def infer_english_weather_type(weather_text: str) -> str:
    text = weather_text.lower()
    has_thunder = "thunder" in text
    has_rain = any(token in text for token in ("rain", "shower", "drizzle"))
    has_fog = any(token in text for token in ("fog", "mist", "haze", "low visibility"))
    has_sun = any(token in text for token in ("sunny", "sunshine", "bright", "fine"))
    has_cloud = any(token in text for token in ("cloud", "overcast"))

    if has_thunder:
        return "Mixed" if has_sun or has_cloud or has_rain else "Thunderstorm"
    if has_fog:
        return "Mixed" if has_sun or has_cloud or has_rain else "Fog"
    if has_rain:
        return "Mixed" if has_sun or has_cloud else "Rain"
    if has_sun:
        return "Sunny"
    if has_cloud:
        return "Cloudy"
    return "Unknown"


def extract_between(block: str, start_label: str, end_label: str | None = None) -> str:
    start_match = re.search(start_label + r"\s*[：:]", block)
    if not start_match:
        return ""
    start = start_match.end()
    if end_label is None:
        return block[start:]
    end_match = re.search(end_label + r"\s*[：:]", block[start:])
    if not end_match:
        return block[start:]
    return block[start : start + end_match.start()]


def parse_forecast_records(title: str, pub_date: str, description: str) -> dict:
    if "Date/Month:" in description:
        return parse_english_forecast_records(title, pub_date, description)

    report_datetime = parse_report_datetime(pub_date)
    report_year, report_month = infer_report_year_month(title, report_datetime)

    matches = list(DATE_HEADER_RE.finditer(description))
    records = []
    for index, match in enumerate(matches):
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(description)
        block = description[block_start:block_end]
        if "氣溫" not in block or "相對濕度" not in block:
            continue

        month = chinese_number_to_int(match.group("month"))
        day = chinese_number_to_int(match.group("day"))
        year = report_year + 1 if report_month == 12 and month == 1 else report_year

        wind = compact_text(extract_between(block, "風", "天氣"))
        weather_text = compact_text(extract_between(block, "天氣", "氣溫"))
        temperature_text = compact_text(extract_between(block, "氣溫", "相對濕度"))
        humidity_text = compact_text(extract_between(block, "相對濕度", "顯著降雨概率"))
        rain_raw = compact_text(extract_between(block, "顯著降雨概率", None))
        rain_match = re.search(r"(中低|中高|低|中|高)", rain_raw)
        rain_text = rain_match.group(1) if rain_match else rain_raw.strip(" 。")

        temperature_match = re.search(r"(\d+)\s*至\s*(\d+)\s*度", temperature_text)
        humidity_match = re.search(r"百分之\s*(\d+)\s*至\s*(\d+)", humidity_text)

        records.append(
            {
                "date_iso": f"{year:04d}-{month:02d}-{day:02d}",
                "weekday": WEEKDAYS.get(match.group("weekday")),
                "wind": wind,
                "weather_text": weather_text,
                "min_temperature_c": int(temperature_match.group(1)) if temperature_match else None,
                "max_temperature_c": int(temperature_match.group(2)) if temperature_match else None,
                "humidity_min_percent": int(humidity_match.group(1)) if humidity_match else None,
                "humidity_max_percent": int(humidity_match.group(2)) if humidity_match else None,
                "rain_probability": RAIN_PROBABILITY.get(rain_text, rain_text),
                "weather_type": infer_chinese_weather_type(weather_text),
            }
        )

    return normalize_schema(
        {
            "source": "hko_nine_day_forecast",
            "report_datetime": report_datetime,
            "records": records,
        }
    )


def parse_english_forecast_records(title: str, pub_date: str, description: str) -> dict:
    report_datetime = parse_report_datetime(pub_date)
    report_year, report_month = infer_report_year_month(title, report_datetime)

    blocks = re.split(r"\nDate/Month:\n", description)[1:]
    records = []
    for block in blocks:
        date_match = ENGLISH_DATE_HEADER_RE.search(block)
        if not date_match:
            continue
        day = int(date_match.group("day"))
        month = int(date_match.group("month"))
        year = report_year + 1 if report_month == 12 and month == 1 else report_year
        weekday = date_match.group("weekday")
        weekday = weekday if weekday in ENGLISH_WEEKDAYS else None

        wind = compact_text(extract_between(block, "Wind", "Weather"))
        weather_text = compact_text(extract_between(block, "Weather", "Temp range"))
        temperature_text = compact_text(extract_between(block, "Temp range", "R\\.H\\. range"))
        humidity_text = compact_text(extract_between(block, "R\\.H\\. range", "PSR"))
        psr_text = compact_text(extract_between(block, "PSR", None))
        psr_match = re.search(r"(Medium Low|Medium High|Low|Medium|High)", psr_text)

        temperature_match = re.search(r"(\d+)\s*-\s*(\d+)\s*C", temperature_text, flags=re.I)
        humidity_match = re.search(r"(\d+)\s*-\s*(\d+)\s*per\s*Cent", humidity_text, flags=re.I)

        records.append(
            {
                "date_iso": f"{year:04d}-{month:02d}-{day:02d}",
                "weekday": weekday,
                "wind": wind,
                "weather_text": weather_text,
                "min_temperature_c": int(temperature_match.group(1)) if temperature_match else None,
                "max_temperature_c": int(temperature_match.group(2)) if temperature_match else None,
                "humidity_min_percent": int(humidity_match.group(1)) if humidity_match else None,
                "humidity_max_percent": int(humidity_match.group(2)) if humidity_match else None,
                "rain_probability": psr_match.group(1) if psr_match else "",
                "weather_type": infer_english_weather_type(weather_text),
            }
        )

    return normalize_schema(
        {
            "source": "hko_nine_day_forecast",
            "report_datetime": report_datetime,
            "records": records,
        }
    )


def output_path_for(input_root: Path, output_root: Path, xml_file: Path) -> Path:
    relative = xml_file.relative_to(input_root)
    return output_root / relative.with_suffix(".json")


def process_file(xml_file: Path, output_file: Path) -> None:
    title, pub_date, description = load_rss_item(xml_file)
    data = parse_forecast_records(title, pub_date, description)
    if len(data["records"]) != 9:
        raise ValueError(f"Expected 9 forecast records, got {len(data['records'])}")
    data["input_file"] = str(xml_file)
    output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process HKO weather RSS XML files into standard JSON without a local LLM."
    )
    parser.add_argument("input_folder", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for JSON outputs. Defaults to <input_folder>/direct_json.",
    )
    parser.add_argument("--limit", type=int, help="Optional max number of files to process")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    input_folder = args.input_folder.resolve()
    output_dir = (args.output_dir or input_folder / "direct_json").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "process_direct.log"

    xml_files = sorted(input_folder.rglob("*.xml"))
    if args.limit is not None:
        xml_files = xml_files[: args.limit]

    ok = 0
    skipped = 0
    failed = 0
    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} total={len(xml_files)} ===\n")
        for index, xml_file in enumerate(xml_files, start=1):
            output_file = output_path_for(input_folder, output_dir, xml_file)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            rel_path = xml_file.relative_to(input_folder)
            if output_file.exists() and not args.overwrite:
                skipped += 1
                line = f"[{index}/{len(xml_files)}] SKIP {rel_path}\n"
                print(line, end="")
                log.write(line)
                continue
            try:
                process_file(xml_file, output_file)
            except Exception as exc:
                failed += 1
                output_file.with_suffix(".error.txt").write_text(
                    "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                    encoding="utf-8",
                )
                line = f"[{index}/{len(xml_files)}] FAIL {rel_path}: {type(exc).__name__}: {exc}\n"
                print(line, end="")
                log.write(line)
                continue
            ok += 1
            line = f"[{index}/{len(xml_files)}] OK {output_file.relative_to(output_dir)}\n"
            print(line, end="")
            log.write(line)

        summary = f"=== done ok={ok} skipped={skipped} failed={failed} output={output_dir} ===\n"
        print(summary, end="")
        log.write(summary)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
