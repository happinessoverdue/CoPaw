import ToolCallCard from "./ToolCallCard";
import { useLogGridPawToolCall } from "./gridPawToolCallDebug";
import { shouldUseThemeHighlightForToolCall } from "./toolThemeHighlight";

type ToolData = {
  status?: string;
  content?: Array<{
    data?: {
      name?: string;
      server_label?: string;
      arguments?: unknown;
      output?: unknown;
    };
  }>;
};

export default function UniversalToolRenderer({ data }: { data: ToolData }) {
  const content = data?.content ?? [];
  const first = content[0];
  const second = content[1];
  const toolName = first?.data?.name ?? "tool";
  const serverLabel = first?.data?.server_label
    ? `${first.data.server_label} / `
    : "";
  const title = `${serverLabel}${toolName}`;
  const output = second?.data?.output ?? "";

  useLogGridPawToolCall(toolName, data);

  if (!content.length) return null;

  const loading = data.status === "in_progress";
  const themeHighlight = shouldUseThemeHighlightForToolCall(toolName, output);

  return (
    <ToolCallCard
      loading={loading}
      defaultOpen={false}
      title={title === "undefined" ? "" : title}
      input={first?.data?.arguments ?? ""}
      output={output}
      themeHighlight={themeHighlight}
    />
  );
}
