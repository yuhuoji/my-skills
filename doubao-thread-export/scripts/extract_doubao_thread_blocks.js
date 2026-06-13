export function cleanText(value) {
  return String(value || "").replace(/\u00a0/g, " ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
}

function inlineMarkdown(node) {
  if (!node) return "";
  if (node.nodeType === 3) return node.textContent || "";
  if (node.nodeType !== 1) return "";

  const tag = node.tagName;
  if (tag === "BR") return "\n";

  const inner = Array.from(node.childNodes).map(inlineMarkdown).join("");
  if (tag === "STRONG" || tag === "B") return `**${cleanText(inner)}**`;
  return inner;
}

function parseParagraphContainer(node) {
  const text = cleanText(inlineMarkdown(node));
  return text ? { type: "paragraph", text } : null;
}

function parseList(listEl) {
  const items = Array.from(listEl.children)
    .filter((child) => child.tagName === "LI")
    .map((li) => {
      const text = cleanText(inlineMarkdown(li));
      return { blocks: text ? [{ type: "paragraph", text }] : [] };
    })
    .filter((item) => item.blocks.length);

  return items.length
    ? { type: "list", ordered: listEl.tagName === "OL", items }
    : null;
}

function parseMdBox(root) {
  const blocks = [];

  for (const child of Array.from(root.children)) {
    if (child.tagName === "HR") {
      blocks.push({ type: "separator" });
      continue;
    }

    const heading = child.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6");
    if (heading) {
      blocks.push({
        type: "heading",
        level: Number(heading.tagName[1]),
        text: cleanText(inlineMarkdown(heading)),
      });
      continue;
    }

    const list = child.querySelector(":scope > ul, :scope > ol");
    if (list) {
      const parsed = parseList(list);
      if (parsed) blocks.push(parsed);
      continue;
    }

    const paragraph = child.querySelector(":scope > .container-enLQFx");
    if (paragraph) {
      const parsed = parseParagraphContainer(paragraph);
      if (parsed) blocks.push(parsed);
      continue;
    }
  }

  return blocks;
}

function parseAttachment(messageEl) {
  const labelNode = messageEl.querySelector("[data-available='true'] .truncate");
  const typeNode = messageEl.querySelector("[data-available='true'] .text-12\\/18, [data-available='true'] .text-dbx-text-tertiary");
  const label = cleanText([labelNode?.textContent || "", typeNode?.textContent || ""].join(" ").trim());
  return label ? { type: "attachment", label } : null;
}

function parseFallbackParagraph(messageEl) {
  const text = cleanText(messageEl.innerText || messageEl.textContent || "");
  return text ? [{ type: "paragraph", text }] : [];
}

export function extractDoubaoThread(document) {
  const title = cleanText(document.querySelector("h1")?.textContent || "");
  const root = document.querySelector(".message-list-root-PvOWIA");
  const messages = [];

  if (!root) {
    return { title, messages };
  }

  for (const item of Array.from(root.children)) {
    const role = (item.className || "").includes("justify-end") ? "user" : "assistant";
    let blocks = [];

    const attachment = parseAttachment(item);
    if (attachment) {
      blocks.push(attachment);
    }

    const mdBox = item.querySelector(".md-box-root");
    if (mdBox) {
      blocks = blocks.concat(parseMdBox(mdBox));
    } else {
      const fallback = parseFallbackParagraph(item);
      if (fallback.length) blocks = blocks.concat(fallback);
    }

    // Extract visible images with actual src URL
    const images = item.querySelectorAll("img[src]");
    images.forEach((img) => {
      const src = img.getAttribute("src") || "";
      const alt = cleanText(img.getAttribute("alt") || "message image");
      // Skip data: URIs (inline base64) and tiny icons
      if (src && !src.startsWith("data:") && !src.includes("emoji") && !src.includes("icon")) {
        blocks.push({ type: "image", src, alt });
      }
    });

    if (blocks.length) {
      messages.push({ role, blocks });
    }
  }

  return {
    title,
    messages,
  };
}
