#!/usr/bin/env python3
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path


DEFAULT_API_BASE = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = "Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q6_K_P.gguf"


EXTRACTION_PROMPT = """You are an information extraction engine for Hong Kong Observatory weather XML text.

Extract daily forecast records from the input and return ONLY valid JSON.
Do not include markdown, comments, explanation, or extra text.
All returned values must be in English, except numeric fields.

Important date rules:
- The input forecast dates are written in Chinese, for example "四月二日 ( 星期二 )".
- Convert each forecast date to ISO format: YYYY-MM-DD.
- Infer the year from the report title or publication date in the input.
- If the report title says "2024年04月02日", use year 2024 for all forecast dates unless the forecast crosses into the next year.
- Convert Chinese weekday names to English:
  - 星期一 = Monday
  - 星期二 = Tuesday
  - 星期三 = Wednesday
  - 星期四 = Thursday
  - 星期五 = Friday
  - 星期六 = Saturday
  - 星期日 / 星期天 = Sunday
- Return weekday as exactly one of:
  - "Monday"
  - "Tuesday"
  - "Wednesday"
  - "Thursday"
  - "Friday"
  - "Saturday"
  - "Sunday"
  - null
- If a date cannot be confidently parsed, use null for date_iso and weekday.

For each forecast day, extract:
- date_iso: ISO date string, for example "2024-04-02", or null
- weekday: one of "Monday" | "Tuesday" | "Wednesday" | "Thursday" | "Friday" | "Saturday" | "Sunday" | null
- wind: English translation of the wind description
- weather_text: English translation of the weather description
- min_temperature_c: lowest temperature as integer, or null
- max_temperature_c: highest temperature as integer, or null
- humidity_min_percent: lowest relative humidity as integer, or null
- humidity_max_percent: highest relative humidity as integer, or null
- rain_probability: English translation of significant rainfall probability, for example "Low", "Medium Low", "Medium High", or ""
- weather_type: one of "Sunny" | "Cloudy" | "Rain" | "Thunderstorm" | "Fog" | "Mixed" | "Unknown"

Rules for weather_type:
- Use "Sunny" if the weather is mainly sunny or partly sunny and no rain is mentioned.
- Use "Cloudy" if mainly cloudy or overcast and no rain/thunderstorm is mentioned.
- Use "Rain" if showers, rain, or drizzle are mentioned.
- Use "Thunderstorm" if thunderstorm is mentioned.
- Use "Fog" if fog, mist, haze, or low visibility is the main condition.
- Use "Mixed" if multiple important conditions appear, such as sunny with showers, cloudy with thunderstorms, or fog followed by sunny periods.
- Use "Unknown" only if the text is unclear.

Return this exact JSON shape:

{
  "source": "hko_nine_day_forecast",
  "report_datetime": "YYYY-MM-DDTHH:mm:ssZ or null",
  "records": [
    {
      "date_iso": "YYYY-MM-DD or null",
      "weekday": "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|null",
      "wind": "",
      "weather_text": "",
      "min_temperature_c": null,
      "max_temperature_c": null,
      "humidity_min_percent": null,
      "humidity_max_percent": null,
      "rain_probability": "",
      "weather_type": "Sunny|Cloudy|Rain|Thunderstorm|Fog|Mixed|Unknown"
    }
  ]
}

Validation rules:
- Return valid JSON only.
- Return compact JSON on one line.
- Do not wrap the JSON in markdown.
- Do not add fields outside the specified schema.
- Use integers for temperature and humidity values.
- Use null for unknown numeric/date values.
- Use empty string "" for unknown text values.
- Preserve one record per forecast day.
- Do not summarize multiple days into one record.
- Do not invent missing values.

Input:
<<<
{forecast_text}
>>>"""


def clean_forecast_html(value: str) -> str:
    value = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.I)
    value = re.sub(r"<\s*p\s*/?\s*>", "\n\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def load_forecast_text(path: Path) -> str:
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
    return f"{title}\nPublished: {pub_date}\n\n{description}"


def extract_json_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    raise ValueError("Gemma response did not contain a JSON object")


def call_gemma(api_base: str, model: str, prompt: str) -> str:
    url = f"{api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 6000,
        "stream": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not call {url}. Start Gemma with: wsl -d Ubuntu -- bash -lc '~/start_gemma4.sh'"
        ) from exc

    message = result["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if content:
        return content

    completion_url = api_base.rstrip().removesuffix("/v1") + "/completion"
    completion_payload = {
        "model": model,
        "prompt": prompt,
        "temperature": 0.0,
        "n_predict": 6000,
        "stream": False,
    }
    completion_request = urllib.request.Request(
        completion_url,
        data=json.dumps(completion_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(completion_request, timeout=300) as response:
        completion = json.loads(response.read().decode("utf-8"))
    return (completion.get("content") or "").strip()


def normalize_schema(data: dict) -> dict:
    weekdays = {None, "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
    weather_types = {"Sunny", "Cloudy", "Rain", "Thunderstorm", "Fog", "Mixed", "Unknown"}

    normalized = {
        "source": "hko_nine_day_forecast",
        "report_datetime": data.get("report_datetime"),
        "records": [],
    }

    for record in data.get("records", []):
        item = {
            "date_iso": record.get("date_iso"),
            "weekday": record.get("weekday") if record.get("weekday") in weekdays else None,
            "wind": record.get("wind") or "",
            "weather_text": record.get("weather_text") or "",
            "min_temperature_c": record.get("min_temperature_c"),
            "max_temperature_c": record.get("max_temperature_c"),
            "humidity_min_percent": record.get("humidity_min_percent"),
            "humidity_max_percent": record.get("humidity_max_percent"),
            "rain_probability": record.get("rain_probability") or "",
            "weather_type": record.get("weather_type")
            if record.get("weather_type") in weather_types
            else "Unknown",
        }
        normalized["records"].append(item)

    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract standard JSON records from an HKO weather RSS XML file using local Gemma."
    )
    parser.add_argument("xml_file", type=Path)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, help="Optional JSON output file")
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Print the final prompt instead of calling Gemma",
    )
    args = parser.parse_args()

    forecast_text = load_forecast_text(args.xml_file)
    prompt = EXTRACTION_PROMPT.replace("{forecast_text}", forecast_text)

    if args.print_prompt:
        print(prompt)
        return 0

    response_text = call_gemma(args.api_base, args.model, prompt)
    data = json.loads(extract_json_text(response_text))
    normalized = normalize_schema(data)
    output_text = json.dumps(normalized, ensure_ascii=False, indent=2)

    if args.output:
        args.output.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
