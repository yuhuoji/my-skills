---
name: doubao-thread-export
description: Export a Doubao shared thread URL into a single clean zip package containing the Markdown transcript and necessary assets. Use when a user sends a `doubao.com/thread/...` link and wants the conversation preserved in order, including visible text, images, attachment evidence, and customizable naming such as date plus thread title.
---

# Doubao Thread Export

Export a shared Doubao thread into:

- one final zip package for delivery
- the zip should expand directly into one Markdown file and one asset directory
- unpacked Markdown and asset directory are intermediate artifacts by default and should not be left in the user-requested output location unless the user asks for them

## Default approach: SSR payload

The shared thread page server-side-renders the full conversation into a
`<script data-fn-name="r" data-fn-args="...">` tag. Index 2 of that array
is the payload (`data.share_info` + `data.message_snapshot.message_list`).
This is the primary path — no browser required, faster, and exposes real
asset URLs that the rendered DOM only shows as cards.

The SSR path is implemented by two scripts and should be used unless it
fails (see Fallback below):

- `scripts/fetch_share_payload.py <url> --out payload.json`
- `scripts/render_from_ssr.py --payload payload.json --md OUT.md --assets-dir OUT_assets`

Both scripts default to proxy `http://127.0.0.1:7897` (override with
`--proxy` or the `DOUBAO_EXPORT_PROXY` env var; pass empty string to
disable). The proxy is required in environments where `NO_PROXY=*` is set
and `doubao.com` resolves to a fake-IP.

### Block handling in render_from_ssr.py

Block types in `message.content` (a JSON-encoded list):

- `10000` text — raw markdown; `#`/`##` are demoted to `###` so message
  headers (`##`) stay strictly higher than internal headings. Every
  single `\n` inside the body is promoted to `\n\n` (paragraph break)
  so the output renders correctly in ANY Markdown viewer — GFM's
  two-trailing-space hard break is not universally supported (many
  IDE previewers ignore it, which makes the export look like one
  collapsed wall of text). Fenced code blocks are preserved verbatim.
  Side effect: tight lists become loose lists; readability stays fine.
- `10025` search — emits italic summary, search keywords, and a
  `参考资料` list of `[title](url) — sitename`.
- `10052` attachment — type 3 (file/PDF) downloaded into the assets dir
  and linked as `📎 附件: [name](assets/name) (KB)`; type 1 (image)
  downloaded as `image_{idx}{ext}` and embedded inline.
- `10053` tips — italic disclaimer line.

Role is `user_type == 1 → 用户`, otherwise `豆包`.

## Fallback: DOM extraction

If SSR fetch returns non-200, the script is missing from the HTML, or
parsing fails, fall back to opening the thread in the in-app browser and
extracting blocks from the rendered DOM:

- `scripts/extract_doubao_thread_blocks.js` — extracts the structured
  block model from the DOM
- `scripts/render_structured_markdown.py --input blocks.json --output OUT.md`
  — deterministic renderer for the block model

The fallback path cannot recover real attachment download URLs (they are
not exposed in the DOM); take screenshots of attachment cards instead.

## Markdown fidelity

Preserve the original visible structure as closely as possible.

- headings stay headings
- unordered lists stay unordered lists
- ordered lists stay ordered lists
- paragraphs stay separate paragraphs
- visible bold becomes Markdown emphasis when practical
- separators become `---` when clearly present

Message-level heading hierarchy is strict:

- each exported message header uses level 2, for example `## 2. 豆包`
- any heading inside that message must be level 3 or deeper, never `#` or `##`
- the SSR renderer enforces this via `demote_headings`; the fallback
  renderer enforces it via `min_heading_level=3`

Do not build message bodies from a single `innerText` dump unless
structure is genuinely unavailable.

## Naming

Prefer the page title shown in the thread header (SSR:
`data.share_info.share_name`). Fall back to the thread id from the URL.

Default naming pattern:

- base name: `{export-date}_{thread-title}`
- markdown: `{base-name}.md`
- assets dir: `{base-name}_assets`
- zip: `{base-name}.zip`

Use `scripts/build_export_name.py` to normalize names:

```bash
python3 scripts/build_export_name.py \
  --date 2026-06-29 \
  --title "示例对话标题" \
  --thread-id "example-thread-id"
```

If the user provides a custom final zip name, pass it with `--zip-name`.
The user's literal name (e.g. `0628工商银行北京分行笔试`) overrides the
default — do not silently append the date prefix to a user-supplied name.

If the default name already exists, append the thread id as a stable
suffix instead of overwriting.

## Export workflow (SSR primary)

1. Determine the thread URL and the user's desired output base name. If
   the user did not supply a name, compute the default with
   `build_export_name.py`, tell the user the default, and offer a custom
   override.
2. Run `fetch_share_payload.py <url> --out /tmp/<base>_payload.json`.
3. If step 2 fails (non-zero exit, no payload, or parse error), switch
   to the Fallback workflow below and continue from step 4 with the
   browser-extracted blocks.
4. Run `render_from_ssr.py --payload <payload> --md <work>/<base>.md
   --assets-dir <work>/<base>_assets`. Read the printed JSON stats to
   confirm message count and asset download counts.
5. Package with `scripts/package_export.py --md <work>/<base>.md
   --assets-dir <work>/<base>_assets --output-dir <out>
   --zip-name <base>.zip`. Default `<out>` is `~/Downloads`.
6. Verify: the zip exists, is non-empty, and `unzip -l` shows the md
   plus the assets directory with the expected files.
7. Deliver only the final zip in the requested output location.
8. Remove unpacked intermediate files unless the user asked to keep them
   (`package_export.py` handles this by default).

## Fallback workflow (DOM)

1. Open the thread in the in-app browser.
2. Run `extract_doubao_thread_blocks.js` to produce the structured
   block JSON.
3. Render with `render_structured_markdown.py`.
4. Continue from step 5 of the primary workflow with the rendered md
   and any screenshots saved to the assets dir.

## Asset rules

Keep the export minimal.

- If an original image or file URL is downloadable (SSR path), keep
  that file.
- If only a card is visible (DOM fallback), keep one screenshot and
  note the limitation in the Markdown.
- Omit decorative or unrelated assets.
- Deduplicate by file name (PDFs) or `uri` (images).

Do not keep:

- browser debug inventories
- page-wide screenshots when a targeted asset file exists
- duplicate copies of the same image
- extra sidecar files whose only purpose is debugging

## User options

Support these options when requested:

- naming template / final zip filename
- output location (default `~/Downloads`)
- `necessary-only` vs `keep-more-evidence`
- whether to keep attachment card screenshots (fallback only)
- whether to preserve Chinese filenames (default on)
- whether to keep unpacked Markdown and asset directory alongside the zip
- whether to force the DOM fallback even when SSR works

If the user does not mention options, use:

- naming: compute default date + title, show it to the user, and ask
  whether to use it or provide a custom zip filename
- assets: `necessary-only`
- Chinese title preservation: on
- keep unpacked files: off
- path: SSR primary, DOM fallback only on SSR failure

## Validation

Before finishing, verify:

- the title used for naming matches the thread title or documented fallback
- the zip expands directly into the Markdown file and asset directory
  (md and `{base}_assets` at the top level — no nested wrapper folder)
- every kept asset is referenced from the Markdown
- no debug files remain in the final package
- only the final zip remains in the requested output location unless
  the user asked to keep unpacked files

Also verify Markdown fidelity on at least one complex message:

- internal headings start with `###` or deeper, never `#` or `##`
- lists appear as list items, not one collapsed sentence
- adjacent sections are separated by blank lines

If a complex message collapsed into one dense paragraph, treat the
export as failed and retry — for SSR, re-fetch the payload; for DOM
fallback, re-extract with structured blocks.
