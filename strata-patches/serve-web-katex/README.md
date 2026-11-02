# Strata serve/web 的 KaTeX 公式渲染补丁

Strata 的网页聊天是零依赖手写前端（`serve/web/app.js`，无 package.json、无构建步骤），
`markdown()` 只处理代码块、粗体、斜体、链接、表格、列表，**不支持 LaTeX**。
上游 llama.cpp 的 webui 能显示公式，是因为它是 Svelte + Vite 工程，
装了 `remark-math` + `rehype-katex` 整套 unified 管线
（见 `examples/server/webui_llamacpp/src/lib/components/app/content/MarkdownContent/MarkdownContent.svelte`）。

本目录是给 Strata 补上同样能力的最小改动。

## 文件

| 文件 | 说明 |
|---|---|
| `katex.min.js` | KaTeX 0.16.45（264 KB） |
| `katex.min.css` | 已改写字体路径为 `/fonts/`，删掉 woff/ttf 回退（24 KB） |
| `fonts/KaTeX_*.woff2` | 20 个字体，与 serve/web/fonts/outfit-*.woff2 同目录 |
| `a.js.diff` / `a.css.diff` / `a.html.diff` | 相对上游 v0.2.6 的三个文件 diff |

## 应用方法

```bash
cd E:/strata-src
cp <本目录>/katex.min.js <本目录>/katex.min.css serve/web/
cp <本目录>/fonts/KaTeX_*.woff2 serve/web/fonts/
patch -p0 serve/web/app.js < <本目录>/a.js.diff
patch -p0 serve/web/app.css < <本目录>/a.css.diff
patch -p0 serve/web/index.html < <本目录>/a.html.diff
# 重启引擎
```

## 关键点

1. **字体路由**：`serve.py` 的 `/fonts/` 路由只放行 `.woff2`，所以 CSS 里的
   `url(fonts/X.woff2)` 必须改成 `url(/fonts/X.woff2)`，woff/ttf 回退必须删掉，
   否则浏览器会去请求 `/web/fonts/...`（被 404）。
2. **`$` 的识别**：对齐 remark-math 的规则——美元符号内侧不能紧邻空格、
   闭合 `$` 后不能紧跟数字。所以 `价格 $5 和 $6` 保持不变，不会被当成公式。
3. **解析失败不吞内容**：`renderMath()` 里 `throwOnError: false`，
   抛异常时回退成 `<code class="math-raw">` 原样显示。
4. **跨行公式**：`$$...$$` 的匹配放在 fenced-code 扫描**之前**，
   否则多行的 display 公式会被按段落切开。

## 实测

| 环境 | 结果 |
|---|---|
| 本地 `127.0.0.1:8081` | katexNodes=4, displayBlocks=2, 宽度 686px, rawDollar=0 |
| 公网 `18c23w6n.zjz-service.cn:28024` | 同上，且自然提问（非强制输出）也能正确渲染 |

## 维护

这层改动会在**上游更新 serve/web 时被覆盖**。届时重新打补丁即可，
三个 diff 相对 v0.2.6，若上游改动大可能需要手工 rebase。
