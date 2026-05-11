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


def load_weather_text(path: Path) -> str:
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


def chat_completion(api_base: str, model: str, text: str, language: str) -> str:
    url = f"{api_base.rstrip('/')}/chat/completions"
    prompt = (
        f"Summarize this Hong Kong Observatory nine-day weather forecast in {language}. "
        "Keep it concise, focus on weather trend, rain/thunderstorm risk, wind, "
        "temperature range, and any important change over the forecast period. "
        "Do not use emoji. Write only the final summary, with no thinking, analysis notes, "
        "or parenthetical process comments.\n\n"
        f"{text}"
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 700,
        "stream": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not call {url}. Start Gemma first with: wsl -d Ubuntu -- bash -lc '~/start_gemma4.sh'"
        ) from exc

    message = result["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if content:
        return content

    # Some reasoning-enabled llama.cpp builds can return only reasoning_content
    # for chat completions. Retry with the plain completion endpoint and ask for
    # final output only.
    completion_url = api_base.rstrip().removesuffix("/v1") + "/completion"
    completion_payload = {
        "model": model,
        "prompt": prompt,
        "temperature": 0.2,
        "n_predict": 700,
        "stream": False,
    }
    completion_request = urllib.request.Request(
        completion_url,
        data=json.dumps(completion_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(completion_request, timeout=180) as response:
        completion = json.loads(response.read().decode("utf-8"))

    return (completion.get("content") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize an HKO RSS weather XML file through local Gemma/llama.cpp."
    )
    parser.add_argument("xml_file", type=Path)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--language", default="English")
    parser.add_argument(
        "--print-extracted",
        action="store_true",
        help="Print the parsed forecast text instead of calling the model.",
    )
    args = parser.parse_args()

    forecast_text = load_weather_text(args.xml_file)
    if args.print_extracted:
        print(forecast_text)
        return 0

    print(chat_completion(args.api_base, args.model, forecast_text, args.language))
    return 0


if __name__ == "__main__":
    sys.exit(main())
