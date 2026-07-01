---
name: km-browser-backup
description: 通过 CDP + 离屏 Edge 浏览器静默备份学城 (km.sankuai.com) 文档为本地 Markdown（含图片），不走 citadel CLI 因此没有埋点上报。适用场景：批量拉取学城 collabpage，保存为 md + assets/ 图片，请求间隔随机化避免检测。
---

# km-browser-backup — 学城文档静默备份 skill

## 使用场景

- 用户明确要「静默」拉取学城文档，不希望留下 citadel 操作日志
- 需要保存为本地 md，含图片，保留标题/代码块/表格/引用格式
- 批量备份（周报、专题合集等），需要控制间隔避免异常

## 前置

- 浏览器：Microsoft Edge（macOS：/Applications/Microsoft Edge.app）
- Debug profile 目录：`~/.edge-km-debug`（首次使用需要在有头模式下登录一次学城）
- 端口：9333（可改）

## 核心原理

1. **离屏窗口**：Edge 用 `--window-position=-32000,-32000` 放到屏幕外，用户看不见但仍是"visible"状态，不会触发 background throttling
2. **懒加载触发**：学城 `.pk-image` 是空 span 直到被 scroll into center。逐个 pk-image `scrollIntoView({block:'center'})` + wait 1.2s + 重试触发 `<img data-origin>` 注入。**这一步必须做**——学城不是 IntersectionObserver 单纯依赖 viewport 高度
3. **折叠面板**：图片可能藏在 `.ct-collapse-content`（display:none）里，此时 scrollIntoView 无效。开始触发前先强制 `.ct-collapse-content { display: block }` 展开所有折叠区
4. **数据源用 `data-origin` 而不是 `img.src`**：`.pk-image > img` 元素上有 `data-origin` 属性 = 原图 URL，避免读到低分辨率 `compress=@Nw_1l` 版本
5. **图片下载**：从 Edge 拿 cookie，用 curl/Python urllib 带 `Cookie:` + `Referer:` 直接抓 `/api/file/cdn/` 原图
6. **正文提取**：注入 JS 从 ProseMirror DOM 转 md（`.pk-title` → `#`、`.ct-heading` → `##/###`、`.ct-code` → 三反引号、`.pk-note` → `> [!NOTE]`）。SVG className 是 SVGAnimatedString 不是 string，用 `clsOf()` helper 兼容

## 使用流程

### 第一次使用（首次登录，唯一一次有头）

```bash
# 有头启动，让用户手动登录一次
"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  --remote-debugging-port=9333 \
  --user-data-dir=~/.edge-km-debug \
  https://km.sankuai.com &
# 用户完成 SSO 登录，然后关闭窗口
```

### 日常静默使用

```bash
# 启动离屏 debug Edge（用户看不到窗口）
bash ~/.claude/skills/km-browser-backup/scripts/start-edge.sh

# 备份单篇文档
python3 ~/.claude/skills/km-browser-backup/scripts/backup.py \
  --content-id 2572374431 \
  --out ~/Downloads/km-backup

# 批量备份
python3 ~/.claude/skills/km-browser-backup/scripts/backup.py \
  --content-ids 2572374431,2719376354 \
  --out ~/Downloads/km-backup \
  --min-interval 30 --max-interval 90
```

### 停止

```bash
bash ~/.claude/skills/km-browser-backup/scripts/stop-edge.sh
```

## 反检测策略

- **随机间隔**：批量时每篇文档之间 30-90s 随机 sleep
- **User-Agent 保持真实**：Edge 默认 UA 就是真人浏览器，不需要伪装
- **不使用 headless mode**：headless 会带 `HeadlessChrome` UA 特征，反而被识别；用 offscreen 有头保留真实指纹
- **图片下载复用同一 cookie**：跟浏览器同源，跟人手动查看图片的请求一致
- **只读操作**：不点击、不评论、不编辑；只是加载页面 + 读 DOM

## 已知限制

- 首次登录必须有头（用户手动 SSO）
- SSO 会话过期后需要重新登录（一般数天）
- 如果学城改造 ProseMirror DOM 结构，`data-origin` 选择器需要更新
- 表格提取当前是基础版（合并单元格可能不完美）
- 附件下载（非图片）暂未实现，只处理正文 + 图片

## 与 citadel 的对比

| 维度 | 本 skill | citadel |
|------|---------|---------|
| 埋点 | 无 | 有 CLI 调用记录 |
| 图片 | ✅ data-origin 直取 | ✅ fetchImage |
| 正文 | DOM → md（自研映射） | getSimpleMarkdown |
| 表格 | 基础 | 好 |
| 附件 | 未实现 | 支持 |
| 速度 | 稍慢（浏览器渲染） | 快 |
| 首次配置 | 需登录一次 | 一次 oa 认证 |

优先选本 skill 当"零埋点"是硬需求。要完美格式选 citadel。

## 输出目录结构

```
out-dir/
  <content-id>_<sanitized-title>.md
  <content-id>_assets/
    图片1.png
    图片2.png
    ...
```

md 里图片引用形式：`![图片1](<content-id>_assets/图片1.png)`
