/**
 * GridPaw：哪些工具调用折叠条使用主题主色（与默认中性样式区分）。
 *
 * - 工具名在名单内 → 高亮
 * - 或工具返回为「块列表」时，任一元素的 `text` 字段**开头**符合文件交接 YAML 约定 → 高亮
 *
 * 后续可扩展：增删名单、增加检测器（本文件内集中维护）。
 */

/** 按工具名强制使用主题色折叠条 */
export const GRIDPAW_THEME_HIGHLIGHT_TOOL_NAMES = new Set<string>(["send_file_to_user"]);

const JSON_UNWRAP_MAX = 4;

function unwrapJsonStringLayers(value: unknown): unknown {
  let current: unknown = value;
  for (let i = 0; i < JSON_UNWRAP_MAX; i += 1) {
    if (typeof current !== "string") break;
    const t = current.trim();
    if (!((t.startsWith("{") || t.startsWith("[")) && t.length > 1)) break;
    try {
      current = JSON.parse(t);
    } catch {
      break;
    }
  }
  return current;
}

/**
 * 仅检测字符串**开头**（允许前导 BOM/空白）：是否以文件交接式 YAML front matter 起头，例如：
 *
 * ---
 * type: file
 * source: http://...
 * description: ...
 * ---
 * ...后续内容...
 */
export function textStartsWithFileHandoffYamlFrontmatter(text: string): boolean {
  if (!text || typeof text !== "string") return false;
  const lead = text.replace(/^\uFEFF/, "").replace(/^\s+/, "");
  const normalized = lead.replace(/\r\n/g, "\n");
  if (!normalized.startsWith("---")) return false;
  const m = normalized.match(/^---\s*\n([\s\S]*?)\n---(?:\n|$)/);
  if (!m) return false;
  const inner = m[1];
  return /\btype:\s*file\b/.test(inner) && /\bsource:\s*\S+/.test(inner);
}

/** 从工具 output 根节点收集「顶层元素」上的 text 字符串（不递归子对象） */
function collectTopLevelTextFields(root: unknown): string[] {
  const out: string[] = [];
  if (Array.isArray(root)) {
    for (const item of root) {
      if (
        item !== null &&
        typeof item === "object" &&
        typeof (item as { text?: unknown }).text === "string"
      ) {
        out.push((item as { text: string }).text);
      }
    }
    return out;
  }
  if (
    root !== null &&
    typeof root === "object" &&
    typeof (root as { text?: unknown }).text === "string"
  ) {
    out.push((root as { text: string }).text);
  }
  return out;
}

/** 仅根据「结果顶层每个元素的 text 字段开头」判断是否高亮 */
export function toolOutputIndicatesThemeHighlight(output: unknown): boolean {
  const root = unwrapJsonStringLayers(output);
  const texts = collectTopLevelTextFields(root);
  return texts.some((t) => textStartsWithFileHandoffYamlFrontmatter(t));
}

/** 是否对该条工具调用使用主题色折叠条 */
export function shouldUseThemeHighlightForToolCall(
  toolName: string | undefined,
  output: unknown,
): boolean {
  const name = (toolName ?? "").trim();
  if (name && GRIDPAW_THEME_HIGHLIGHT_TOOL_NAMES.has(name)) return true;
  return toolOutputIndicatesThemeHighlight(output);
}
