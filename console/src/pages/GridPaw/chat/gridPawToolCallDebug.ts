/**
 * GridPaw：打印工具消息结构（便于对照「工具调用结果」真实形态）。
 * 须通过 useLogGridPawToolCall 使用：若在 render 里直接调 logGridPawToolCall，
 * 父组件每次重渲染都会刷屏（聊天/流式会触发成百上千次 render）。
 * 验证结束后可删去 useLogGridPawToolCall 调用。
 */

import { useEffect, useRef } from "react";

const MAX_STRING_INLINE = 12000;

/** 供 useEffect 依赖：output 内容不变则指纹不变，避免无意义重复打印 */
export function fingerprintToolMessageOutput(output: unknown): string {
  if (output === undefined) return "undef";
  if (output === null) return "null";
  if (typeof output === "string") {
    const n = output.length;
    if (n === 0) return "s:0";
    return `s:${n}:${output.slice(0, 80)}:${output.slice(Math.max(0, n - 80))}`;
  }
  if (Array.isArray(output)) {
    return `a:${output.length}:${fingerprintToolMessageOutput(output[0])}`;
  }
  if (typeof output === "object") {
    return `o:${Object.keys(output as object).sort().join("|")}`;
  }
  return `${typeof output}:${String(output)}`;
}

/**
 * 在工具卡片组件内调用：仅在 call_id / status / 输出内容指纹变化时打印一次。
 * 用 ref 挡掉 StrictMode 下 effect 双跑造成的重复同一条日志。
 */
export function useLogGridPawToolCall(
  toolName: string,
  data: { status?: string; content?: unknown[] },
): void {
  const content = data?.content ?? [];
  const first = content[0] as { data?: { call_id?: unknown } } | undefined;
  const second = content[1] as { data?: { output?: unknown } } | undefined;
  const callId = String(first?.data?.call_id ?? "");
  const output = second?.data?.output;
  const status = String(data?.status ?? "");
  const outFp = fingerprintToolMessageOutput(output);
  const slotCount = content.length;

  const lastPrintedKeyRef = useRef<string>("");

  useEffect(() => {
    if (slotCount === 0) return;
    const key = `${toolName}\t${callId}\t${status}\t${outFp}\t${slotCount}`;
    if (lastPrintedKeyRef.current === key) return;
    lastPrintedKeyRef.current = key;
    logGridPawToolCall(toolName, data);
    // 勿将 data 列入依赖：每条消息常为新建对象，会导致每次父级 render 都跑 effect、再次刷屏。
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 以 callId/status/output 指纹为准
  }, [toolName, callId, status, outFp, slotCount]);
}

/** 单行说明「工具返回 output」的运行时类型，便于在 Console 里一眼看到 */
function formatToolOutputTypeLine(value: unknown): string {
  if (value === undefined) return "undefined（无 content[1].data.output）";
  if (value === null) return "null";
  if (Array.isArray(value)) {
    return `object 且 Array.isArray===true，length=${value.length}`;
  }
  const t = typeof value;
  if (t === "string") {
    return `string，length=${(value as string).length}`;
  }
  if (t === "object") {
    const ctor = (value as object).constructor?.name ?? "Object";
    const keys = Object.keys(value as object);
    return `object（constructor=${ctor}），keys=[${keys.join(", ")}]`;
  }
  return `${t}（primitive）`;
}

function describeValue(value: unknown): Record<string, unknown> {
  if (value === null) return { typeof: "object", detail: "null" };
  if (Array.isArray(value)) {
    return {
      typeof: "object",
      isArray: true,
      length: value.length,
    };
  }
  if (typeof value === "string") {
    const s = value;
    const out: Record<string, unknown> = { typeof: "string", length: s.length };
    if (s.length <= MAX_STRING_INLINE) {
      out.fullText = s;
    } else {
      out.head = s.slice(0, 6000);
      out.tail = s.slice(-2000);
      out.truncatedChars = s.length - 8000;
    }
    const trim = s.trim();
    if (
      (trim.startsWith("{") && trim.endsWith("}")) ||
      (trim.startsWith("[") && trim.endsWith("]"))
    ) {
      try {
        out.jsonParsed = JSON.parse(trim);
      } catch {
        out.jsonParsed = "(looks like JSON but parse failed)";
      }
    }
    return out;
  }
  if (typeof value === "object") {
    return {
      typeof: "object",
      isArray: false,
      keys: Object.keys(value as object),
    };
  }
  return { typeof: typeof value, value };
}

/** 所有经 GridPaw 自定义渲染的工具都会走到这里，打印类型 + 内容摘要 + raw（可展开） */
export function logGridPawToolCall(
  toolName: string,
  data: { status?: string; content?: unknown[] },
): void {
  const content = data?.content ?? [];

  console.log("[GridPaw tool call] summary", {
    toolName,
    status: data?.status ?? "(none)",
    contentLength: content.length,
  });

  const toolResultOutput = (content[1] as { data?: { output?: unknown } } | undefined)?.data
    ?.output;
  console.log(
    "[GridPaw tool call] ★ 工具返回 output 类型:",
    formatToolOutputTypeLine(toolResultOutput),
  );

  console.log("[GridPaw tool call] content (raw, 可在 DevTools 里展开)", content);

  content.forEach((slot, index) => {
    if (slot === null || typeof slot !== "object" || !("data" in slot)) {
      console.log(`[GridPaw tool call] content[${index}]`, {
        slotType: typeof slot,
        slotIsArray: Array.isArray(slot),
        describe: describeValue(slot),
        slotRaw: slot,
      });
      return;
    }

    const wrap = slot as { data?: Record<string, unknown> };
    const d = wrap.data;
    if (!d) {
      console.log(`[GridPaw tool call] content[${index}]`, { data: undefined, slotRaw: slot });
      return;
    }

    const args = d.arguments;
    const out = d.output;

    console.log(`[GridPaw tool call] content[${index}].data meta`, {
      name: d.name,
      call_id: d.call_id,
      server_label: d.server_label,
      status: d.status,
    });
    console.log(`[GridPaw tool call] content[${index}].arguments describe`, describeValue(args));
    console.log(`[GridPaw tool call] content[${index}].arguments raw`, args);
    console.log(`[GridPaw tool call] content[${index}].output describe`, describeValue(out));
    console.log(`[GridPaw tool call] content[${index}].output raw`, out);
  });
}
