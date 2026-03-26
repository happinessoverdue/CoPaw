import type { FC } from "react";
import SendFileRender from "./SendFileRender";
import ToolCallCard from "./ToolCallCard";
import { useLogGridPawToolCall } from "./gridPawToolCallDebug";
import { shouldUseThemeHighlightForToolCall } from "./toolThemeHighlight";

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

const SendFileWithDefault: FC<SendFileWithDefaultProps> = ({ data }) => {
  const content = data?.content ?? [];
  const loading = data?.status === "in_progress";
  const first = content[0];
  const second = content[1];
  const toolName = first?.data?.name ?? "send_file_to_user";
  const serverLabel = first?.data?.server_label ? `${first.data.server_label} / ` : "";
  const title = `${serverLabel}${toolName}`;
  const input = first?.data?.arguments ?? "";
  const output = second?.data?.output ?? "";

  useLogGridPawToolCall(toolName, data);

  const themeHighlight = shouldUseThemeHighlightForToolCall(toolName, output);

  return (
    <ToolCallCard
      loading={loading}
      defaultOpen={false}
      title={title === "undefined" ? "" : title}
      input={input}
      output={output}
      themeHighlight={themeHighlight}
      extraContent={<SendFileRender data={data} />}
    />
  );
};

export default SendFileWithDefault;
