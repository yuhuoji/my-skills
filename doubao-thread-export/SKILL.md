---
name: doubao-thread-export
description: Export a Doubao shared thread URL into a single clean zip package containing the Markdown transcript and necessary assets. Use when a user sends a `doubao.com/thread/...` link and wants the conversation preserved in order, including visible text, images, attachment evidence, and customizable naming such as date plus thread title.
---

# Doubao Thread Export

Export a shared Doubao thread into:

- one final zip package for delivery
- the zip should expand directly into one Markdown file and one asset directory
- unpacked Markdown and asset directory are intermediate artifacts by default and should not be left in the user-requested output location unless the user asks for them

## Default behavior

Use the shared thread page as the source of truth.

Export visible conversation content in strict on-page order:

- user messages
- assistant messages
- visible images
- visible attachment cards or filenames

Default to `necessary-only` assets:

- keep original image files when they can be downloaded
- keep attachment screenshots when the original attachment URL is not exposed
- do not include debug inventories, temporary screenshots, or extra notes unless the user asks

## Markdown fidelity

Preserve the original visible structure as closely as possible.

Prefer structured Markdown reconstruction over plain-text flattening:

- headings must stay headings
- unordered lists must stay unordered lists
- ordered lists must stay ordered lists
- paragraphs must stay separate paragraphs
- visible bold emphasis should become Markdown emphasis when practical
- separators should become `---` when clearly present

Message-level heading hierarchy is strict:

- each exported message header uses level 2, for example `## 2. 豆包`
- any heading inside that message must be rendered at a smaller visual level than the message header
- therefore in Markdown, internal message headings must be level 3 or deeper, never `#` or `##`

Do not build message bodies from a single `innerText` or `textContent` dump unless structure is genuinely unavailable.

When a message contains multiple structural elements, extract them as structured blocks first, then render Markdown from those blocks.

Use `scripts/render_structured_markdown.py` for deterministic rendering once blocks are extracted.

## Structured extraction contract

When reading a message from the page, aim to produce blocks shaped like:

```json
{
  "role": "assistant",
  "blocks": [
    { "type": "heading", "level": 3, "text": "回答示例（STAR 结构，突出主动性）" },
    { "type": "paragraph", "text": "下面给你一个可直接参考的回答示例..." },
    {
      "type": "list",
      "ordered": false,
      "items": [
        {
          "blocks": [
            { "type": "paragraph", "text": "S（情境）：项目初期..." }
          ]
        }
      ]
    }
  ]
}
```

Use the simplest accurate block model:

- `paragraph`
- `heading`
- `list`
- `separator`
- `image`
- `attachment`

If a block contains nested content, keep it nested instead of concatenating it into one line.

## Naming

Prefer the page title shown in the thread header. If unavailable, fall back to the thread id from the URL.

Default naming pattern:

- base name: `{export-date}_{thread-title}`
- markdown: `{base-name}.md`
- assets dir: `{base-name}_assets`
- zip: `{base-name}.zip`

Use `scripts/build_export_name.py` to normalize names:

```bash
python3 scripts/build_export_name.py \
  --date 2026-06-02 \
  --title "示例对话标题" \
  --thread-id "example-thread-id"
```

If the user provides a custom final zip name, pass it with `--zip-name`.

If the user explicitly asks for a custom scheme, support it. Good examples:

- add a custom prefix
- use timestamp instead of date only
- preserve the raw Chinese title
- switch to ASCII-heavy names

If the user does not specify naming for the final zip, do not silently proceed.

Instead:

- compute the default final zip name first
- tell the user exactly what the current default filename is
- offer a choice between:
  - using that default filename
  - providing a custom zip filename
- if the user gives a custom name only for the zip, keep the export date prefix by default and keep the internal Markdown and asset directory names aligned to that final base name unless the user asks otherwise

If the default name already exists, append a stable suffix such as the thread id instead of overwriting.

## Export workflow

1. Open the Doubao thread in the in-app browser.
2. Read the page title and visible message list.
3. Extract conversation items in sequence, keeping user and assistant roles distinct.
4. For each message, extract structured blocks instead of flattened text whenever possible.
5. Render Markdown from those blocks with `scripts/render_structured_markdown.py`.
6. Collect only necessary assets:
   - original image files when obtainable
   - attachment screenshots when the original file cannot be fetched
7. Reference kept assets from the Markdown near the relevant message.
8. Package with `scripts/package_export.py` so the final zip uses UTF-8 filenames and expands directly into the Markdown file and asset directory.
9. Deliver only the final zip in the user-requested output location by default.
10. Remove unpacked intermediate Markdown and asset directory copies from the user-requested output location unless the user explicitly asked to keep them.

## Asset rules

Keep the export minimal.

For each non-text item:

- If an original image file is accessible, keep that file.
- If the page shows an attachment card but no downloadable file URL, keep a screenshot of the card and note the limitation in the Markdown.
- If an asset is decorative or unrelated to the conversation, omit it.

Do not keep:

- browser debug inventories
- page-wide screenshots when a targeted asset file exists
- duplicate copies of the same image
- extra sidecar files whose only purpose is debugging

Prefer explaining limitations inside the Markdown so the asset directory stays small.

## User options

Support these options when requested:

- naming template
- final zip filename
- output location
- `necessary-only` vs `keep-more-evidence`
- whether to keep attachment card screenshots
- whether to preserve Chinese filenames
- whether to keep unpacked Markdown and asset directory alongside the zip

If the user does not mention options, use:

- naming: compute default date + title, show it to the user, and ask whether to use it or provide a custom zip filename
- assets: `necessary-only`
- attachment fallback screenshot: on
- Chinese title preservation: on
- keep unpacked files: off

## Validation

Before finishing, verify:

- the title used for naming matches the thread title or documented fallback
- the zip expands directly into the Markdown file and asset directory
- every kept asset is referenced or justified
- no debug files remain in the final package
- only the final zip remains in the requested output location unless the user asked to keep unpacked files

Also verify Markdown fidelity on at least one complex message:

- a heading should still start with `#`, `##`, or `###`
- lists should still appear as list items rather than one collapsed sentence
- adjacent sections should still be separated by blank lines

If a complex message collapsed into one dense paragraph, treat the export as failed and retry with more structured extraction.
