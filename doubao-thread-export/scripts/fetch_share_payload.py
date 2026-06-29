#!/usr/bin/env python3
"""Fetch a Doubao shared thread page and extract the SSR payload.

The shared thread page embeds the full conversation in a
`<script data-fn-name="r" data-fn-args="...">` tag. The `data-fn-args`
attribute is an HTML-escaped JSON array; element [2] is the payload dict
containing `data.share_info` and `data.message_snapshot.message_list`.

Usage:
  python3 fetch_share_payload.py <thread-url> [--out payload.json] [--proxy URL]

Exit code 0 on success, non-zero if fetch or parse fails.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_PROXY = "http://127.0.0.1:7897"

SCRIPT_RE = re.compile(
    rb'<script[^>]*data-fn-name="r"[^>]*data-fn-args="([^"]+)"',
    re.IGNORECASE,
)


def fetch_html(url: str, proxy: str | None) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
        tmp_path = tf.name
    try:
        cmd = ["curl", "-sS", "-L", "-m", "60"]
        if proxy:
            cmd += ["--proxy", proxy, "--noproxy", ""]
        cmd += [
            "-H",
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "-o",
            tmp_path,
            url,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"curl failed: rc={r.returncode} stderr={r.stderr.strip()}")
        data = Path(tmp_path).read_bytes()
        if not data:
            raise RuntimeError("empty response")
        return data
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def extract_payload(html_bytes: bytes) -> dict:
    matches = SCRIPT_RE.findall(html_bytes)
    if not matches:
        raise RuntimeError("no <script data-fn-name=\"r\"> found in page")
    # Prefer the largest match (the real payload, not a stub).
    raw = max(matches, key=len)
    decoded = html.unescape(raw.decode("utf-8"))
    args = json.loads(decoded)
    if not isinstance(args, list) or len(args) < 3:
        raise RuntimeError(f"unexpected data-fn-args shape: type={type(args).__name__} len={len(args) if hasattr(args, '__len__') else 'n/a'}")
    payload = args[2]
    if not isinstance(payload, dict) or "data" not in payload:
        raise RuntimeError("payload missing 'data' key")
    data = payload["data"]
    if "share_info" not in data or "message_snapshot" not in data:
        raise RuntimeError("payload.data missing share_info or message_snapshot")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("url", help="Doubao thread URL, e.g. https://www.doubao.com/thread/<id>")
    p.add_argument("--out", help="Write payload JSON to this path (default: stdout)")
    p.add_argument(
        "--proxy",
        default=os.environ.get("DOUBAO_EXPORT_PROXY", DEFAULT_PROXY),
        help="HTTP proxy (default: %(default)s). Pass empty string to disable.",
    )
    args = p.parse_args()

    proxy = args.proxy or None
    try:
        html_bytes = fetch_html(args.url, proxy)
    except Exception as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        return 2
    try:
        payload = extract_payload(html_bytes)
    except Exception as e:
        print(f"parse failed: {e}", file=sys.stderr)
        return 3

    out_text = json.dumps(payload, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(out_text, encoding="utf-8")
        msgs = payload["data"]["message_snapshot"].get("message_list", [])
        title = payload["data"]["share_info"].get("share_name", "")
        print(
            f"wrote {args.out} ({len(out_text)} bytes, title={title!r}, messages={len(msgs)})",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
