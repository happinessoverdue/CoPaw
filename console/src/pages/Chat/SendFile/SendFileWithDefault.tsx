/**
 * send_file_to_user 的 Wrapper 组件：默认 ToolCall 展示 + 下方 SendFileRender 下载卡片。
 * 实现「默认工具输出 + 额外特殊展示」的叠加模式。
 */
import type { FC } from "react";
import { ToolCall } from "@agentscope-ai/chat";
import SendFileRender from "./index";

interface SendFileWithDefaultProps {
  data: {
    status?: string;
    content?: Array<{
      data?: {
        name?: string;
        server_label?: string;
        arguments?: string | Record<string, unknown>;
        output?: unknown;
      };
    }>;
  };
}

export const SendFileWithDefault: FC<SendFileWithDefaultProps> = ({ data }) => {
  const content = data?.content ?? [];
  const loading = data?.status === "in_progress";
  const first = content[0];
  const second = content[1];
  const toolName = first?.data?.name ?? "send_file_to_user";
  const serverLabel = first?.data?.server_label
    ? `${first.data.server_label} / `
    : "";
  const title = `${serverLabel}${toolName}`;
  const input = first?.data?.arguments ?? "";
  const output = second?.data?.output ?? "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <ToolCall
        loading={loading}
        defaultOpen={false}
        title={title === "undefined" ? "" : title}
        input={input}
        output={output}
      />
      <SendFileRender data={data} />
    </div>
  );
};

export default SendFileWithDefault;
