#!/usr/bin/env python3
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from extract_weather_json import (
    DEFAULT_API_BASE,
    DEFAULT_MODEL,
    EXTRACTION_PROMPT,
    call_gemma,
    extract_json_text,
    load_forecast_text,
    normalize_schema,
)


def output_name_for(xml_file: Path) -> str:
    return xml_file.with_suffix(".json").name


def output_path_for(input_root: Path, output_root: Path, xml_file: Path) -> Path:
    relative = xml_file.relative_to(input_root)
    return output_root / relative.with_suffix(".json")


def process_file(xml_file: Path, output_file: Path, api_base: str, model: str) -> None:
    forecast_text = load_forecast_text(xml_file)
    prompt = EXTRACTION_PROMPT.replace("{forecast_text}", forecast_text)
    response_text = call_gemma(api_base, model, prompt)
    data = json.loads(extract_json_text(response_text))
    normalized = normalize_schema(data)
    normalized["input_file"] = str(xml_file)
    output_file.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process every XML file in a folder into standard weather JSON with local Gemma."
    )
    parser.add_argument("input_folder", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for JSON outputs. Defaults to <input_folder>/gemma_json.",
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, help="Optional max number of files to process")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    input_folder = args.input_folder.resolve()
    output_dir = (args.output_dir or input_folder / "gemma_json").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "process.log"

    xml_files = [
        path
        for path in sorted(input_folder.rglob("*.xml"))
        if output_dir not in path.resolve().parents
    ]
    if args.limit is not None:
        xml_files = xml_files[: args.limit]

    total = len(xml_files)
    ok = 0
    skipped = 0
    failed = 0

    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} total={total} ===\n")
        log.flush()

        for index, xml_file in enumerate(xml_files, start=1):
            output_file = output_path_for(input_folder, output_dir, xml_file)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            if output_file.exists() and not args.overwrite:
                skipped += 1
                line = f"[{index}/{total}] SKIP {xml_file.relative_to(input_folder)}\n"
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
                continue

            rel_path = xml_file.relative_to(input_folder)
            line = f"[{index}/{total}] START {rel_path}\n"
            print(line, end="", flush=True)
            log.write(line)
            log.flush()

            last_exc = None
            for attempt in range(1, args.retries + 2):
                try:
                    process_file(xml_file, output_file, args.api_base, args.model)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    line = (
                        f"[{index}/{total}] RETRY {attempt}/{args.retries + 1} "
                        f"{rel_path}: {type(exc).__name__}: {exc}\n"
                    )
                    print(line, end="", flush=True)
                    log.write(line)
                    log.flush()
                    time.sleep(min(10 * attempt, 60))

            if last_exc is not None:
                failed += 1
                fail_file = output_file.with_suffix(".error.txt")
                fail_file.write_text(
                    "".join(
                        traceback.format_exception(
                            type(last_exc), last_exc, last_exc.__traceback__
                        )
                    ),
                    encoding="utf-8",
                )
                line = f"[{index}/{total}] FAIL {rel_path}: {type(last_exc).__name__}: {last_exc}\n"
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
                continue

            ok += 1
            line = f"[{index}/{total}] OK {output_file.relative_to(output_dir)}\n"
            print(line, end="", flush=True)
            log.write(line)
            log.flush()

        summary = f"=== done ok={ok} skipped={skipped} failed={failed} output={output_dir} ===\n"
        print(summary, end="", flush=True)
        log.write(summary)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
