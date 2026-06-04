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


def normalize_zip_base_name(value: str, export_date: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    if value.lower().endswith(".zip"):
        value = value[:-4]
    sanitized = sanitize(value)
    date_prefix = f"{export_date}_"
    if sanitized.startswith(date_prefix):
        return sanitized
    return f"{date_prefix}{sanitized}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Export date, e.g. 2026-06-02")
    parser.add_argument("--title", default="", help="Thread title")
    parser.add_argument("--thread-id", default="", help="Fallback thread id")
    parser.add_argument("--prefix", default="", help="Optional custom prefix")
    parser.add_argument(
        "--zip-name",
        default="",
        help="Optional final zip filename, with or without .zip suffix",
    )
    args = parser.parse_args()

    title_part = sanitize(args.title) if args.title else ""
    fallback_part = sanitize(args.thread_id) if args.thread_id else "doubao-thread"

    stem_parts = [args.date]
    if args.prefix:
        stem_parts.append(sanitize(args.prefix))
    stem_parts.append(title_part or fallback_part)
    default_base_name = "_".join(part for part in stem_parts if part)
    final_base_name = normalize_zip_base_name(args.zip_name, args.date) if args.zip_name else default_base_name

    print(
        json.dumps(
            {
                "default_base_name": default_base_name,
                "default_zip_name": f"{default_base_name}.zip",
                "final_base_name": final_base_name,
                "zip_name": f"{final_base_name}.zip",
                "md_name": f"{final_base_name}.md",
                "assets_dir": f"{final_base_name}_assets",
                "user_choice_required": not bool(args.zip_name),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
