#!/usr/bin/env python3
"""Render extracted Doubao message blocks into deterministic Markdown."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _clean_text(value: str) -> str:
    value = str(value).replace("\u00a0", " ").replace("\r\n", "\n")
    parts = []
    for line in value.split("\n"):
        parts.append(" ".join(line.split()))
    text = "\n".join(parts)
    text = "\n\n".join(part.strip() for part in text.split("\n\n"))
    return text.strip()


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line if line else prefix.rstrip() for line in text.splitlines())


@dataclass
class Renderer:
    lines: list[str]
    min_heading_level: int

    def __init__(self, min_heading_level: int = 1) -> None:
        self.lines = []
        self.min_heading_level = min_heading_level

    def blank(self) -> None:
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def line(self, value: str = "") -> None:
        self.lines.append(value)

    def render_blocks(self, blocks: list[dict[str, Any]], list_prefix: str | None = None) -> str:
        nested = Renderer(min_heading_level=self.min_heading_level)
        for block in blocks:
            nested.render_block(block, list_prefix=list_prefix)
        while nested.lines and nested.lines[-1] == "":
            nested.lines.pop()
        return "\n".join(nested.lines)

    def render_block(self, block: dict[str, Any], list_prefix: str | None = None) -> None:
        block_type = block.get("type", "paragraph")
        if block_type == "heading":
            self.blank()
            level = int(block.get("level", 2))
            level = max(self.min_heading_level, min(level, 6))
            self.line(f"{'#' * level} {_clean_text(block.get('text', ''))}")
            self.blank()
            return
        if block_type == "paragraph":
            text = _clean_text(block.get("text", ""))
            if not text:
                return
            self.blank()
            if list_prefix:
                self.line(f"{list_prefix}{text}")
            else:
                self.line(text)
            self.blank()
            return
        if block_type == "separator":
            self.blank()
            self.line("---")
            self.blank()
            return
        if block_type == "image":
            alt = _clean_text(block.get("alt", "image")) or "image"
            path = block.get("path", "")
            if path:
                self.blank()
                self.line(f"![{alt}]({path})")
                self.blank()
            return
        if block_type == "attachment":
            label = _clean_text(block.get("label", "附件"))
            path = block.get("path", "")
            note = _clean_text(block.get("note", ""))
            self.blank()
            self.line(label)
            if path:
                self.line(f"![{label}]({path})")
            if note:
                self.line("")
                self.line(note)
            self.blank()
            return
        if block_type == "list":
            self.blank()
            ordered = bool(block.get("ordered", False))
            items = block.get("items", [])
            for idx, item in enumerate(items, start=1):
                prefix = f"{idx}. " if ordered else "- "
                item_blocks = item.get("blocks", [])
                rendered = self.render_blocks(item_blocks, list_prefix=prefix)
                if not rendered:
                    text = _clean_text(item.get("text", ""))
                    if text:
                        self.line(f"{prefix}{text}")
                    continue
                rendered_lines = rendered.splitlines()
                first = rendered_lines[0]
                self.line(first)
                for extra in rendered_lines[1:]:
                    self.line(_indent(extra, "  "))
            self.blank()
            return
        text = _clean_text(block.get("text", ""))
        if text:
            self.blank()
            self.line(text)
            self.blank()


def render_messages(payload: dict[str, Any]) -> str:
    title = _clean_text(payload.get("title", "豆包对话导出")) or "豆包对话导出"
    source = payload.get("source_url", "")
    export_date = payload.get("export_date", "")
    messages = payload.get("messages", [])

    r = Renderer()
    r.line("# 豆包对话导出")
    r.line("")
    if source:
        r.line(f"- 来源：<{source}>")
    if export_date:
        r.line(f"- 导出时间：{export_date}")
    r.line(f"- 对话标题：{title}")
    r.line("")
    r.line("---")
    r.line("")

    for idx, message in enumerate(messages, start=1):
        role = "用户" if message.get("role") == "user" else "豆包"
        r.line(f"## {idx}. {role}")
        r.line("")
        blocks = message.get("blocks", [])
        rendered = Renderer(min_heading_level=3).render_blocks(blocks)
        if rendered:
            r.line(rendered)
            r.line("")

    while r.lines and r.lines[-1] == "":
        r.lines.pop()
    return "\n".join(r.lines) + "\n"


def load_payload(path: str | None) -> dict[str, Any]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Path to structured JSON payload. Defaults to stdin.")
    parser.add_argument("--output", help="Path to write Markdown. Defaults to stdout.")
    args = parser.parse_args()

    payload = load_payload(args.input)
    markdown = render_messages(payload)

    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)


if __name__ == "__main__":
    main()
