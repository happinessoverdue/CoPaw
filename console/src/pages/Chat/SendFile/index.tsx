import { useMemo, useState } from "react";
import { Button, Card, Typography, message, Tag } from "antd";
import {
  CheckCircleOutlined,
  DownloadOutlined,
  FileOutlined,
} from "@ant-design/icons";
import { getApiToken, getApiUrl } from "../../../api/config";

interface SendFileRenderProps {
  data: {
    status?: string;
    content?: Array<{ data?: { name?: string; output?: unknown } }>;
  };
}

interface FileInfo {
  callId: string;
  url: string;
  filename: string;
}


function parseNestedJson(input: unknown): unknown {
  let value = input;
  for (let i = 0; i < 3; i += 1) {
    if (typeof value !== "string") break;
    try {
      value = JSON.parse(value);
    } catch {
      break;
    }
  }
  return value;
}

function filenameFromUrl(url: string): string {
  const raw = url.replace(/^file:\/\//, "");
  const parts = raw.split("/");
  const name = decodeURIComponent(parts[parts.length - 1] || "").trim();
  return name || "downloaded_file";
}

function findFileInfo(data: SendFileRenderProps["data"]): FileInfo | null {
  const content = data?.content || [];
  const callId = String(
    (
      (content[0] as unknown as { data?: { call_id?: string } } | undefined)
        ?.data?.call_id || ""
    ).trim(),
  );

  // 兼容两种消息结构：
  // 1. 实时流：同一 item 同时有 name 和 output
  // 2. 历史加载：content[0] 为 tool_call（有 name），content[1] 为 tool_output（有 output）
  const first = content[0] as { data?: { name?: string; output?: unknown } } | undefined;
  const second = content[1] as { data?: { name?: string; output?: unknown } } | undefined;
  const isSendFileFromFirst = first?.data?.name === "send_file_to_user";
  const outputSource = second?.data?.output ?? first?.data?.output;

  if (!isSendFileFromFirst) {
    // 若 content[0] 不是 send_file_to_user，再尝试从其他 item 查找（兼容旧结构）
    for (const item of content) {
      const toolName = item?.data?.name || "";
      if (toolName !== "send_file_to_user") continue;
      const parsed = parseNestedJson(item?.data?.output);
      if (!Array.isArray(parsed)) continue;
      const fileBlock = parsed.find(
        (block: unknown) =>
          typeof block === "object" &&
          block !== null &&
          ["file", "image", "audio", "video"].includes(
            String((block as { type?: unknown }).type || ""),
          ),
      ) as
        | {
            type?: string;
            source?: { type?: string; url?: string };
            filename?: string;
          }
        | undefined;

      const url = fileBlock?.source?.url;
      if (!url || typeof url !== "string") continue;
      const filename =
        fileBlock?.filename && typeof fileBlock.filename === "string"
          ? fileBlock.filename
          : filenameFromUrl(url);
      return { callId, url, filename };
    }
    return null;
  }

  const parsed = parseNestedJson(outputSource);
  if (!Array.isArray(parsed)) return null;
  const fileBlock = parsed.find(
    (block: unknown) =>
      typeof block === "object" &&
      block !== null &&
      ["file", "image", "audio", "video"].includes(
        String((block as { type?: unknown }).type || ""),
      ),
  ) as
    | {
        type?: string;
        source?: { type?: string; url?: string };
        filename?: string;
      }
    | undefined;

  const url = fileBlock?.source?.url;
  if (!url || typeof url !== "string") return null;
  const filename =
    fileBlock?.filename && typeof fileBlock.filename === "string"
      ? fileBlock.filename
      : filenameFromUrl(url);
  return { callId, url, filename };
}

export default function SendFileRender(props: SendFileRenderProps) {
  const [msgApi, contextHolder] = message.useMessage();
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const fileInfo = useMemo(() => findFileInfo(props.data), [props.data]);

  const status = String(props.data?.status || "").toLowerCase();
  if (["in_progress", "running", "pending"].includes(status)) return null;
  if (!fileInfo) return null;

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const headers: HeadersInit = {};
      const token = getApiToken();
      if (token) {
        (headers as Record<string, string>).Authorization = `Bearer ${token}`;
      }

      const url = getApiUrl(
        `/agent/download-file?file_path=${encodeURIComponent(fileInfo.url)}`,
      );
      const response = await fetch(url, { method: "GET", headers });
      if (!response.ok) {
        if (response.status === 404) {
          throw new Error("文件已被移动或删除");
        }
        if (response.status === 400) {
          throw new Error("文件路径无效，请重新生成文件后再试");
        }
        if (response.status === 401 || response.status === 403) {
          throw new Error("无权限下载该文件，请检查登录状态");
        }
        throw new Error(`服务异常（${response.status}）`);
      }

      const contentType = (
        response.headers.get("content-type") || ""
      ).toLowerCase();
      if (contentType.includes("text/html")) {
        throw new Error(
          "下载接口返回了页面内容，请重启 CoPaw 服务后重试下载",
        );
      }

      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = fileInfo.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(objectUrl);
      setDownloaded(true);
      msgApi.success("文件下载成功");
    } catch (error) {
      const reason =
        error instanceof Error ? error.message : "未知错误，请稍后重试";
      msgApi.error(`文件下载失败：${reason}`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      {contextHolder}
      <Card
        size="small"
        style={{
          width: "100%",
          borderRadius: 12,
          overflow: "hidden",
          background: "rgba(248, 242, 255, 0.78)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          border: "1px solid rgba(196, 181, 253, 0.35)",
          boxShadow:
            "0 2px 12px rgba(139, 92, 246, 0.06), inset 0 1px 0 rgba(255,255,255,0.6)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <Typography.Text strong>
              <FileOutlined style={{ marginRight: 8 }} />
              {fileInfo.filename}
            </Typography.Text>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {downloaded
                  ? "文件已下载，可再次下载"
                  : "文件已生成，可点击下载"}
              </Typography.Text>
              {downloaded && (
                <Tag
                  color="success"
                  icon={<CheckCircleOutlined />}
                  style={{ marginLeft: 8 }}
                >
                  已下载
                </Tag>
              )}
            </div>
          </div>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={downloading}
            onClick={() => void handleDownload()}
          >
            下载
          </Button>
        </div>
      </Card>
    </>
  );
}
