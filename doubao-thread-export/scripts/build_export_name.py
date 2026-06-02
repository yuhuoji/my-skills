#!/usr/bin/env python3
"""Build deterministic export names for Doubao thread exports."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata


def sanitize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = value.replace("/", "-")
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]", "", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "untitled-thread"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Export date, e.g. 2026-06-02")
    parser.add_argument("--title", default="", help="Thread title")
    parser.add_argument("--thread-id", default="", help="Fallback thread id")
    parser.add_argument("--prefix", default="", help="Optional custom prefix")
    args = parser.parse_args()

    title_part = sanitize(args.title) if args.title else ""
    fallback_part = sanitize(args.thread_id) if args.thread_id else "doubao-thread"

    stem_parts = [args.date]
    if args.prefix:
        stem_parts.append(sanitize(args.prefix))
    stem_parts.append(title_part or fallback_part)
    base_name = "_".join(part for part in stem_parts if part)

    print(
        json.dumps(
            {
                "base_name": base_name,
                "md_name": f"{base_name}.md",
                "zip_name": f"{base_name}.zip",
                "assets_dir": f"{base_name}_assets",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
