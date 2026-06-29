#!/usr/bin/env python3
"""Render Markdown + download assets from a Doubao SSR payload.

Input: the payload dict produced by `fetch_share_payload.py` (i.e. args[2]
from the `data-fn-name="r"` script).

Output:
  - Markdown file at --md
  - asset directory at --assets-dir (created if missing); referenced
    relatively from the Markdown via {assets-dir-name}/...

Block types handled:
  10000 text          -> raw markdown with heading demotion (#,## -> ###)
  10025 search        -> summary + queries + reference list
  10052 attachment    -> type 3 file (download), type 1 image (download)
  10053 tips          -> italic disclaimer line

Heading rule: text blocks may contain `#`/`##` which would collide with the
`##` message-level header. Demote both to `###` so message structure stays
strictly higher than internal content.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

DEFAULT_PROXY = "http://127.0.0.1:7897"
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def safe_name(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_")


def demote_headings(text: str) -> str:
    out = []
    for ln in text.split("\n"):
        if ln.startswith("# "):
            out.append("### " + ln[2:])
        elif ln.startswith("## "):
            out.append("### " + ln[3:])
        else:
            out.append(ln)
    return "\n".join(out)


def enforce_hard_breaks(text: str) -> str:
    """Doubao renders every `\\n` as a visible line break, but in CommonMark
    a single `\\n` between two non-empty lines collapses to a space.

    Promote every single `\\n` to `\\n\\n` (paragraph break) so the output
    works in any Markdown renderer — GFM's two-trailing-space hard break
    is not universally supported (many IDE previewers ignore it).

    Skip lines inside fenced code blocks (preserve verbatim).
    Also ensure ATX headings have a blank line both before and after.
    Collapse runs of >2 newlines back down to exactly two.
    """
    lines = text.split("\n")
    in_code = False
    out: list[str] = []
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if is_fence:
            in_code = not in_code
            out.append(ln)
            continue
        if in_code:
            out.append(ln)
            continue
        is_heading = stripped.startswith("#")
        prev = out[-1] if out else ""
        if is_heading and prev.strip() != "":
            out.append("")
        out.append(ln)
        # Force a blank line after this line if the next line is non-empty
        # (turns single \n into paragraph break). Headings also get a blank
        # line after, by the same mechanism.
        next_nonempty = i + 1 < len(lines) and lines[i + 1].strip() != ""
        if ln.strip() and next_nonempty:
            out.append("")
    # Collapse runs of >1 blank line into a single blank line (so we have
    # exactly one blank between content lines, which is one paragraph break).
    collapsed: list[str] = []
    prev_blank = False
    for ln in out:
        blank = ln.strip() == ""
        if blank and prev_blank:
            continue
        collapsed.append(ln)
        prev_blank = blank
    return "\n".join(collapsed)


def curl_download(url: str, dest: Path, proxy: str | None, timeout: int = 60) -> bool:
    cmd = ["curl", "-sS", "-L", "-m", str(timeout)]
    if proxy:
        cmd += ["--proxy", proxy, "--noproxy", ""]
    cmd += ["-o", str(dest), url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def guess_image_ext(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    for e in IMG_EXTS:
        if e in path:
            return e
    return ".png"


def render(payload: dict, md_path: Path, assets_dir: Path, proxy: str | None) -> dict:
    data = payload["data"]
    title = data["share_info"].get("share_name", "豆包对话")
    msgs = data["message_snapshot"].get("message_list", [])

    assets_dir.mkdir(parents=True, exist_ok=True)
    assets_name = assets_dir.name

    lines: list[str] = [f"# {title}", ""]
    counter = 0
    pdf_seen: dict[str, bool] = {}
    img_seen: dict[str, tuple[str, bool]] = {}
    stats = {"pdf_ok": 0, "pdf_fail": 0, "img_ok": 0, "img_fail": 0, "messages": 0}

    for m in msgs:
        role = "用户" if m.get("user_type") == 1 else "豆包"
        raw_content = m.get("content", "")
        try:
            parsed = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
        except json.JSONDecodeError:
            parsed = []
        # Normalize: content may be (a) a list of blocks, (b) a dict like
        # {"text": "..."} for plain assistant replies, or (c) something else.
        if isinstance(parsed, list):
            blocks = parsed
        elif isinstance(parsed, dict):
            if "text" in parsed and isinstance(parsed["text"], str):
                blocks = [{"block_type": 10000, "content": {"text_block": {"text": parsed["text"]}}}]
            elif "block_type" in parsed:
                blocks = [parsed]
            else:
                blocks = []
        else:
            blocks = []
        counter += 1
        stats["messages"] += 1
        lines.append(f"## {counter}. {role}")
        lines.append("")
        for b in blocks:
            bt = b.get("block_type")
            c = b.get("content", {}) or {}
            if bt == 10000:
                txt = (c.get("text_block", {}) or {}).get("text", "").strip()
                if txt:
                    lines.append(enforce_hard_breaks(demote_headings(txt)))
                    lines.append("")
            elif bt == 10052:
                for a in (c.get("attachment_block", {}) or {}).get("attachments", []) or []:
                    atype = a.get("type")
                    if atype == 3 and "file" in a:
                        f = a["file"] or {}
                        raw_name = f.get("name", "attachment")
                        name = safe_name(raw_name)
                        url = f.get("url")
                        size_kb = (f.get("size", 0) or 0) // 1024
                        if url and name not in pdf_seen:
                            ok = curl_download(url, assets_dir / name, proxy)
                            pdf_seen[name] = ok
                            stats["pdf_ok" if ok else "pdf_fail"] += 1
                            print(f"  [pdf] {name}  {'ok' if ok else 'FAIL'}  ({size_kb} KB)", file=sys.stderr)
                        rel = f"{assets_name}/{name}"
                        if pdf_seen.get(name):
                            lines.append(f"📎 附件: [{raw_name}]({rel}) ({size_kb} KB)")
                        else:
                            lines.append(f"📎 附件: **{raw_name}** ({size_kb} KB) — 下载失败")
                        lines.append("")
                    elif atype == 1 and "image" in a:
                        img = a["image"] or {}
                        url = (img.get("image_ori") or {}).get("url") or (img.get("image_thumb") or {}).get("url")
                        if not url:
                            continue
                        key = img.get("uri") or url
                        if key not in img_seen:
                            idx = len(img_seen) + 1
                            name = f"image_{idx}{guess_image_ext(url)}"
                            ok = curl_download(url, assets_dir / name, proxy)
                            img_seen[key] = (name, ok)
                            stats["img_ok" if ok else "img_fail"] += 1
                            print(f"  [img] {name}  {'ok' if ok else 'FAIL'}", file=sys.stderr)
                        name, ok = img_seen[key]
                        rel = f"{assets_name}/{name}"
                        if ok:
                            lines.append(f"![图片]({rel})")
                        else:
                            lines.append(f"![图片(下载失败)]({url})")
                        lines.append("")
            elif bt == 10025:
                sqr = c.get("search_query_result_block", {}) or {}
                summary = (sqr.get("summary") or "").strip()
                if summary:
                    lines.append(f"_🔍 {summary}_")
                    lines.append("")
                for q in sqr.get("queries", []) or []:
                    lines.append(f"- 搜索关键词: {q}")
                results = sqr.get("results", []) or []
                if results:
                    lines.append("")
                    lines.append("参考资料:")
                    for r in results:
                        tc = r.get("text_card", {}) or {}
                        t = (tc.get("title") or "").strip()
                        u = tc.get("url") or ""
                        s = tc.get("sitename") or ""
                        if t and u:
                            lines.append(f"- [{t}]({u})" + (f" — {s}" if s else ""))
                lines.append("")
            elif bt == 10053:
                tip = (c.get("tips_block", {}) or {}).get("text", "").strip()
                if tip:
                    lines.append(f"_{tip}_")
                    lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return stats


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--payload", required=True, help="Path to payload JSON from fetch_share_payload.py")
    p.add_argument("--md", required=True, help="Output Markdown path")
    p.add_argument("--assets-dir", required=True, help="Output assets directory")
    p.add_argument(
        "--proxy",
        default=os.environ.get("DOUBAO_EXPORT_PROXY", DEFAULT_PROXY),
        help="HTTP proxy for downloads (default: %(default)s). Empty to disable.",
    )
    args = p.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    stats = render(payload, Path(args.md), Path(args.assets_dir), args.proxy or None)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
