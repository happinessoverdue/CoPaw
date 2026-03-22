import ToolCallCard from "./ToolCallCard";

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
  if (!content.length) return null;
  const loading = data.status === "in_progress";
  const first = content[0];
  const second = content[1];
  const toolName = first?.data?.name ?? "tool";
  const serverLabel = first?.data?.server_label
    ? `${first.data.server_label} / `
    : "";
  const title = `${serverLabel}${toolName}`;

  return (
    <ToolCallCard
      loading={loading}
      defaultOpen={false}
      title={title === "undefined" ? "" : title}
      input={first?.data?.arguments ?? ""}
      output={second?.data?.output ?? ""}
    />
  );
}
