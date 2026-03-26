import {
  AgentScopeRuntimeWebUI,
  type IAgentScopeRuntimeWebUIOptions,
  type IAgentScopeRuntimeWebUIMessage,
  type IAgentScopeRuntimeWebUIRef,
  type IAgentScopeRuntimeWebUISession,
  type IAgentScopeRuntimeWebUISessionAPI,
} from "@agentscope-ai/chat";
import { Empty, Progress, Spin, Tag, Typography, message } from "antd";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Brain, Camera, ChevronLeft, Paperclip, X } from "lucide-react";
import { getApiToken, getApiUrl } from "../../api/config";
import type { ChatHistory } from "../../api/types/chat";
import type { AgentContextUsage } from "../../api/types";
import { agentApi, type CurrentPlanResponse } from "../../api/modules/agent";
import { chatApi } from "../../api/modules/chat";
import { providerApi } from "../../api/modules/provider";
import gridPawSessionApi from "./chat/sessionApi";
import ContextUsageRing from "./chat/ContextUsageRing";
import SendFileWithDefault from "./chat/SendFileWithDefault";
import UniversalToolRenderer from "./chat/UniversalToolRenderer";
import { GRIDPAW_PRESET_VIEWS } from "./presetViews";
import gridPawLogo from "../../assets/gridpaw-logo.svg";
import styles from "./index.module.less";

type GridPawTheme = "sage" | "azure";

type SessionMeta = {
  session_id?: string;
  user_id?: string;
  channel?: string;
};

type ResponseUsage = {
  input_tokens?: number;
  output_tokens?: number;
};

type InputChunk = {
  session?: SessionMeta;
  content?: unknown;
  [key: string]: unknown;
};

type HistorySessionItem = {
  id: string;
  sessionId: string;
  title: string;
  updatedAt: string | null;
  latestUsage?: ResponseUsage | null;
};

type PlanTask = {
  name: string;
  target: string;
  status: string;
};

type PlanViewModel = {
  name: string;
  tasks: PlanTask[];
};

type PendingImageAsset = {
  id: string;
  fileName: string;
  previewUrl: string;
  uploadedUrl?: string;
  uploading: boolean;
  error?: string;
};

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

const THEME_KEY = "gridpaw_theme";
const VIEW_KEY = "gridpaw_view";
const DOCK_MIN_WIDTH = 420;
const DOCK_MIN_HEIGHT = 460;
const TOP_BAR_GAP = 3;
const TOP_BAR_HEIGHT = 56;
const TOP_TO_DOCK_GAP = 10;
const DOCK_BOTTOM_GAP = 14;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function normalizeAddress(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

function buildModelError(): Response {
  return new Response(
    JSON.stringify({
      error: "Model not configured",
      message: "Please configure a model in /models before chatting.",
    }),
    { status: 400, headers: { "Content-Type": "application/json" } },
  );
}

function getSelectedAgentId(): string {
  try {
    const agentStorage = localStorage.getItem("copaw-agent-storage");
    if (!agentStorage) return "";
    const parsed = JSON.parse(agentStorage);
    return parsed?.state?.selectedAgent || "";
  } catch {
    return "";
  }
}

function toStoredName(url: string): string {
  const matchWithAgent = url.match(/\/console\/files\/[^/]+\/(.+)$/);
  if (matchWithAgent?.[1]) {
    return matchWithAgent[1];
  }
  const matchSimple = url.match(/^[^/]+\/(.+)$/);
  if (matchSimple?.[1]) {
    return matchSimple[1];
  }
  return url;
}

function rewriteInputPayload(input: unknown[]): unknown[] {
  if (!Array.isArray(input) || input.length === 0) return input;
  const lastInput = input[input.length - 1] as InputChunk;
  if (!Array.isArray(lastInput?.content)) return input;

  const rewrittenContent = lastInput.content.map((rawPart) => {
    if (!rawPart || typeof rawPart !== "object") return rawPart;
    const part = { ...(rawPart as Record<string, unknown>) };
    const type = typeof part.type === "string" ? part.type : "";

    if (type === "image" && typeof part.image_url === "string") {
      part.image_url = toStoredName(part.image_url);
    }
    if (type === "file" && typeof part.file_url === "string") {
      part.file_url = toStoredName(part.file_url);
    }
    if (type === "audio" && typeof part.audio_url === "string") {
      part.data = toStoredName(part.audio_url);
    }
    if (type === "video" && typeof part.video_url === "string") {
      part.video_url = toStoredName(part.video_url);
    }

    return part;
  });

  return [
    ...input.slice(0, -1),
    {
      ...lastInput,
      content: rewrittenContent,
    },
  ];
}

function pickLatestUserInputChunk(input: unknown[]): InputChunk | undefined {
  if (!Array.isArray(input) || input.length === 0) return undefined;

  for (let index = input.length - 1; index >= 0; index -= 1) {
    const chunk = input[index] as InputChunk | undefined;
    if (!chunk || typeof chunk !== "object") continue;
    const role = (chunk as { role?: unknown }).role;
    if (role === "user") return chunk;
    if (Array.isArray(chunk.content)) return chunk;
  }

  return input[input.length - 1] as InputChunk;
}

function formatSessionTime(value: string | null): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function toPlanViewModel(raw: Record<string, unknown> | null): PlanViewModel | null {
  if (!raw || typeof raw !== "object") return null;
  const candidate =
    (raw.plan as Record<string, unknown> | undefined) ||
    (raw.todo_list as Record<string, unknown> | undefined) ||
    raw;

  const name = candidate?.name;
  const tasks = candidate?.tasks;
  if (typeof name !== "string" || !Array.isArray(tasks)) return null;

  const normalizedTasks = tasks
    .map((item) => {
      const task = item as Record<string, unknown>;
      return {
        name: String(task.name ?? ""),
        target: String(task.target ?? ""),
        status: String(task.status ?? "pending"),
      };
    })
    .filter((task) => task.name || task.target);

  return { name, tasks: normalizedTasks };
}

function getStatusMeta(status: string): { label: string; color: string } {
  const normalized = status.toLowerCase();
  if (normalized === "in_progress") return { label: "进行中", color: "processing" };
  if (normalized === "complete" || normalized === "success")
    return { label: "已完成", color: "success" };
  if (normalized === "failed") return { label: "失败", color: "error" };
  return { label: "待处理", color: "default" };
}

function deriveAgentRuntimeStatus(history: ChatHistory): {
  label: string;
  busy: boolean;
} {
  if (history.status !== "running") {
    return { label: "空闲中：就绪", busy: false };
  }

  const messages = Array.isArray(history.messages) ? history.messages : [];
  const lastMessage = [...messages].reverse().find((message) => !!message);
  if (!lastMessage) return { label: "正在思考", busy: true };

  const role = String(lastMessage.role || "");
  const type = String(lastMessage.type || "");
  if (type === "plugin_call" || role === "tool") {
    return { label: "正在使用工具", busy: true };
  }
  if (role === "assistant" || type === "plugin_call_output") {
    return { label: "正在分析总结", busy: true };
  }
  return { label: "正在思考", busy: true };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object";
}

function readUsageValue(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function extractLatestUsageFromUiMessages(
  messages: IAgentScopeRuntimeWebUIMessage[] | undefined,
): ResponseUsage | null {
  if (!messages?.length) return null;

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index] as {
      cards?: Array<{ code?: string; data?: unknown }>;
    };
    const responseCard = message.cards?.find(
      (card) => card.code === "AgentScopeRuntimeResponseCard",
    );
    if (!responseCard || !isRecord(responseCard.data)) continue;
    const usage = responseCard.data.usage;
    if (!isRecord(usage)) continue;
    const inputTokens = readUsageValue(usage.input_tokens);
    const outputTokens = readUsageValue(usage.output_tokens);
    if (inputTokens <= 0 && outputTokens <= 0) continue;
    return {
      input_tokens: inputTokens,
      output_tokens: outputTokens,
    };
  }

  return null;
}

function buildContextUsageFromResponseUsage(
  usage: ResponseUsage,
  maxInputTokens: number,
  compactThresholdRatio: number,
  reserveThresholdRatio: number,
): AgentContextUsage {
  const usedTokens = Math.max(readUsageValue(usage.input_tokens), 0);
  const compactThresholdTokens = Math.max(
    Math.floor(maxInputTokens * compactThresholdRatio),
    0,
  );
  const reserveThresholdTokens = Math.max(
    Math.floor(maxInputTokens * reserveThresholdRatio),
    0,
  );

  return {
    session_id: "",
    user_id: "",
    used_tokens: usedTokens,
    max_input_tokens: maxInputTokens,
    compact_threshold_tokens: compactThresholdTokens,
    reserve_threshold_tokens: reserveThresholdTokens,
    system_prompt_tokens: 0,
    summary_tokens: 0,
    messages_tokens: usedTokens,
    message_count: 0,
    usage_ratio: maxInputTokens > 0 ? Math.min(usedTokens / maxInputTokens, 1) : 0,
    compact_ratio:
      compactThresholdTokens > 0
        ? Math.min(usedTokens / compactThresholdTokens, 1)
        : 0,
    compact_threshold_ratio:
      maxInputTokens > 0 ? compactThresholdTokens / maxInputTokens : 0,
    has_compressed_summary: false,
  };
}

function toImageFiles(files: File[]): File[] {
  return files.filter((file) => file.type.startsWith("image/"));
}

function filesFromClipboard(event: ClipboardEvent): File[] {
  const files: File[] = [];
  const items = event.clipboardData?.items || [];
  for (const item of Array.from(items)) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (!file) continue;
    files.push(file);
  }
  return toImageFiles(files);
}

function filesFromDrop(event: DragEvent): File[] {
  const files = Array.from(event.dataTransfer?.files || []);
  return toImageFiles(files);
}

export default function GridPawPage() {
  const [theme, setTheme] = useState<GridPawTheme>(() => {
    const storedTheme = localStorage.getItem(THEME_KEY);
    return storedTheme === "azure" ? "azure" : "sage";
  });
  const [canvasUrl, setCanvasUrl] = useState<string>(() => {
    const stored = localStorage.getItem(VIEW_KEY);
    const normalized = normalizeAddress(stored || "");
    return normalized || GRIDPAW_PRESET_VIEWS[0]?.url || "about:blank";
  });
  const [addressInput, setAddressInput] = useState<string>(canvasUrl);
  const [dockCollapsed, setDockCollapsed] = useState(false);
  const [planPanelOpen, setPlanPanelOpen] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const [currentPlan, setCurrentPlan] = useState<CurrentPlanResponse | null>(null);
  const [planLastUpdatedAt, setPlanLastUpdatedAt] = useState("");
  const [topBarHidden, setTopBarHidden] = useState(false);
  // --- GridPaw: start --- 默认展开历史会话，便于刷新后与当前选中会话一致
  const [historyOpen, setHistoryOpen] = useState(true);
  // --- GridPaw: end ---
  const [historyMenuOpenId, setHistoryMenuOpenId] = useState("");
  const [historyDeletingId, setHistoryDeletingId] = useState("");
  const [historySessions, setHistorySessions] = useState<HistorySessionItem[]>(
    [],
  );
  const [pendingImages, setPendingImages] = useState<PendingImageAsset[]>([]);
  const [imagePreviewUrl, setImagePreviewUrl] = useState("");
  const [agentStatus, setAgentStatus] = useState("空闲中：就绪");
  const [agentBusy, setAgentBusy] = useState(false);
  const [contextUsage, setContextUsage] = useState<AgentContextUsage | null>(null);
  const [contextUsageLoading, setContextUsageLoading] = useState(false);
  const [maxInputTokens, setMaxInputTokens] = useState(0);
  const [compactThresholdRatio, setCompactThresholdRatio] = useState(0);
  const [reserveThresholdRatio, setReserveThresholdRatio] = useState(0);
  const [activeHistorySessionId, setActiveHistorySessionId] = useState("");
  const activeHistorySessionIdRef = useRef(activeHistorySessionId);
  const [chatInstanceKey, setChatInstanceKey] = useState(0);
  const [dockWidth, setDockWidth] = useState(860);
  const [dockHeight, setDockHeight] = useState(1020);
  const [viewportWidth, setViewportWidth] = useState<number>(
    window.innerWidth || 1440,
  );
  const isCompact = viewportWidth <= 1080;
  const resizeFrameRef = useRef<number | null>(null);
  const pendingWidthRef = useRef<number | null>(null);
  const pendingHeightRef = useRef<number | null>(null);
  const resizingRef = useRef(false);
  const resizePointerIdRef = useRef<number | null>(null);
  const resizeCleanupRef = useRef<(() => void) | null>(null);
  const pendingImagesRef = useRef<PendingImageAsset[]>([]);
  const chatDockRef = useRef<HTMLElement | null>(null);
  const chatRef = useRef<IAgentScopeRuntimeWebUIRef>(null);
  const reconnectTriggeredForRef = useRef<string | null>(null);
  const latestUsagePersistedRef = useRef("");

  useEffect(() => {
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    document.title = "GridPaw智能体";
  }, []);

  useEffect(() => {
    pendingImagesRef.current = pendingImages;
  }, [pendingImages]);

  useEffect(() => {
    activeHistorySessionIdRef.current = activeHistorySessionId;
  }, [activeHistorySessionId]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "azure") {
      root.style.setProperty("--gp-primary", "#0b5f8f");
      root.style.setProperty("--gp-panel", "rgba(242, 248, 252, 0.84)");
      return;
    }
    root.style.setProperty("--gp-primary", "#0d5f1d");
    root.style.setProperty("--gp-panel", "rgba(251, 249, 244, 0.82)");
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(VIEW_KEY, canvasUrl);
  }, [canvasUrl]);

  useEffect(() => {
    const onResize = () => {
      setViewportWidth(window.innerWidth || 1440);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void agentApi
      .getAgentRunningConfig()
      .then((config) => {
        if (cancelled) return;
        setMaxInputTokens(config.max_input_length ?? 0);
        setCompactThresholdRatio(config.memory_compact_ratio ?? 0);
        setReserveThresholdRatio(config.memory_reserve_ratio ?? 0);
      })
      .catch((error) => {
        console.warn("Failed to load agent running config", error);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const applyUsageToContextRing = useCallback(
    (usage: ResponseUsage | null, sessionId?: string, userId?: string) => {
      if (!usage || maxInputTokens <= 0) return false;
      const nextUsage = buildContextUsageFromResponseUsage(
        usage,
        maxInputTokens,
        compactThresholdRatio,
        reserveThresholdRatio,
      );
      nextUsage.session_id = sessionId || "";
      nextUsage.user_id = userId || "";
      setContextUsage(nextUsage);
      return true;
    },
    [compactThresholdRatio, maxInputTokens, reserveThresholdRatio],
  );

  const persistLatestUsageForSession = useCallback(
    async (sessionId: string, usage: ResponseUsage) => {
      const chatId = gridPawSessionApi.resolveChatId(sessionId);
      const session = gridPawSessionApi.getSessionSnapshot(sessionId);
      if (!chatId || !session) return;

      const cacheKey = `${chatId}:${readUsageValue(usage.input_tokens)}:${readUsageValue(
        usage.output_tokens,
      )}`;
      if (latestUsagePersistedRef.current === cacheKey) return;
      latestUsagePersistedRef.current = cacheKey;

      try {
        await chatApi.updateChat(chatId, {
          id: chatId,
          name: session.name || "New GridPaw Chat",
          session_id: session.sessionId || sessionId,
          user_id: session.userId || "default",
          channel: session.channel || "console",
          meta: {
            ...(session.meta || {}),
            latest_usage: {
              input_tokens: readUsageValue(usage.input_tokens),
              output_tokens: readUsageValue(usage.output_tokens),
            },
          },
        });
      } catch (error) {
        console.warn("Failed to persist latest response usage", error);
      }
    },
    [],
  );

  const runtimeSessionApi = useMemo(
    () =>
      ({
        getSessionList: () => gridPawSessionApi.getSessionList(),
        getSession: async (sessionId: string) => {
          const session = await gridPawSessionApi.getSession(sessionId);
          const usage = extractLatestUsageFromUiMessages(session.messages);
          const sessionMeta = (session as unknown as { meta?: Record<string, unknown> }).meta;
          if (usage) {
            applyUsageToContextRing(
              usage,
              (session as { sessionId?: string }).sessionId || sessionId,
              (session as { userId?: string }).userId || "default",
            );
          } else if (isRecord(sessionMeta) && isRecord(sessionMeta.latest_usage)) {
            const latestUsage = sessionMeta.latest_usage as Record<string, unknown>;
            applyUsageToContextRing(
              {
                input_tokens: readUsageValue(latestUsage.input_tokens),
                output_tokens: readUsageValue(latestUsage.output_tokens),
              },
              (session as { sessionId?: string }).sessionId || sessionId,
              (session as { userId?: string }).userId || "default",
            );
          }
          return session;
        },
        createSession: (session: Partial<IAgentScopeRuntimeWebUISession>) =>
          gridPawSessionApi.createSession(session),
        updateSession: async (session: Partial<IAgentScopeRuntimeWebUISession>) => {
          const next = await gridPawSessionApi.updateSession(session);
          const usage = extractLatestUsageFromUiMessages(session.messages);
          const sessionId =
            (session as { sessionId?: string }).sessionId ||
            session.id ||
            window.currentSessionId ||
            "";
          const userId =
            (session as { userId?: string }).userId || window.currentUserId || "default";
          if (usage) {
            applyUsageToContextRing(usage, sessionId, userId);
            if (sessionId) {
              void persistLatestUsageForSession(sessionId, usage);
            }
          }
          return next;
        },
        removeSession: (session: Partial<IAgentScopeRuntimeWebUISession>) =>
          gridPawSessionApi.removeSession(session),
      }) as IAgentScopeRuntimeWebUISessionAPI,
    [applyUsageToContextRing, persistLatestUsageForSession],
  );

  const customToolRenderConfig = useMemo(
    () =>
      new Proxy(
        { send_file_to_user: SendFileWithDefault } as Record<string, unknown>,
        {
          get(target, prop) {
            if (typeof prop === "string" && prop in target) {
              return target[prop];
            }
            return UniversalToolRenderer;
          },
        },
      ),
    [],
  );

  const loadHistorySessions = useCallback(async () => {
    const chats = await chatApi.listChats();
    gridPawSessionApi.ingestChatsFromHistory(chats);
    const mapped = [...chats].reverse().map((chat) => {
      const named = (chat as { name?: string }).name;
      const title = named || `Session ${chat.session_id.slice(-8) || chat.id.slice(-8)}`;
      const meta = isRecord(chat.meta) ? chat.meta : {};
      const latestUsage = isRecord(meta.latest_usage)
        ? {
            input_tokens: readUsageValue(meta.latest_usage.input_tokens),
            output_tokens: readUsageValue(meta.latest_usage.output_tokens),
          }
        : null;
      return {
        id: chat.id,
        sessionId: chat.session_id,
        title,
        updatedAt: chat.updated_at,
        latestUsage,
      };
    });
    setHistorySessions(mapped);
    // --- GridPaw: start --- 刷新进入且尚未选中会话时，默认选中历史列表第一项并与 sessionApi 对齐
    if (!activeHistorySessionIdRef.current && mapped.length > 0) {
      const first = mapped[0];
      const firstId = first.id;
      activeHistorySessionIdRef.current = firstId;
      gridPawSessionApi.setPreferredSessionId(firstId);
      setActiveHistorySessionId(firstId);
      window.currentSessionId = first.sessionId || firstId;
      queueMicrotask(() => {
        setChatInstanceKey((k) => k + 1);
      });
    }
    // --- GridPaw: end ---
  }, []);

  useEffect(() => {
    void loadHistorySessions();
  }, [loadHistorySessions]);

  useEffect(() => {
    if (!historyOpen) return;
    const timer = window.setInterval(() => {
      void loadHistorySessions();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [historyOpen, loadHistorySessions]);

  const loadCurrentPlan = useCallback(async (silent: boolean = false) => {
    const sessionId = window.currentSessionId || "";
    const userId = window.currentUserId || "default";
    if (!sessionId) {
      setCurrentPlan({ exists: false, file_path: "", plan: null });
      return;
    }

    if (!silent) setPlanLoading(true);
    try {
      const result = await agentApi.getCurrentPlan(sessionId, userId);
      setCurrentPlan(result);
      setPlanLastUpdatedAt(
        new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      );
    } catch (error) {
      setCurrentPlan({
        exists: false,
        file_path: "",
        plan: { error: `读取计划失败: ${String(error)}` },
      });
    } finally {
      if (!silent) setPlanLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!planPanelOpen) return;
    void loadCurrentPlan(false);
    const timer = window.setInterval(() => {
      void loadCurrentPlan(true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadCurrentPlan, planPanelOpen]);

  useEffect(() => {
    if (!historyMenuOpenId) return;
    const closeMenu = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("[data-history-menu-interactive='true']")) {
        return;
      }
      setHistoryMenuOpenId("");
    };
    const closeOnEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setHistoryMenuOpenId("");
      }
    };
    document.addEventListener("pointerdown", closeMenu);
    document.addEventListener("keydown", closeOnEsc);
    return () => {
      document.removeEventListener("pointerdown", closeMenu);
      document.removeEventListener("keydown", closeOnEsc);
    };
  }, [historyMenuOpenId]);

  useEffect(() => {
    if (dockCollapsed) {
      setPlanPanelOpen(false);
    }
  }, [dockCollapsed]);

  useEffect(() => {
    let mounted = true;
    const syncAgentStatus = async () => {
      const sessionId = activeHistorySessionId || window.currentSessionId || "";
      if (!sessionId) {
        if (!mounted) return;
        setAgentStatus("空闲中：就绪");
        setAgentBusy(false);
        return;
      }

      const chatId = gridPawSessionApi.resolveChatId(sessionId);
      if (!chatId) {
        if (!mounted) return;
        setAgentStatus("空闲中：就绪");
        setAgentBusy(false);
        return;
      }

      try {
        const history = await chatApi.getChat(chatId);
        if (!mounted) return;
        const next = deriveAgentRuntimeStatus(history);
        setAgentStatus(next.label);
        setAgentBusy(next.busy);
      } catch {
        if (!mounted) return;
        setAgentStatus("空闲中：就绪");
        setAgentBusy(false);
      }
    };

    void syncAgentStatus();
    const timer = window.setInterval(() => {
      void syncAgentStatus();
    }, 1800);

    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [activeHistorySessionId, chatInstanceKey, dockCollapsed]);

  useEffect(() => {
    const tryReconnectRunningSession = async () => {
      const sessionId = activeHistorySessionId || window.currentSessionId || "";
      const chatId = gridPawSessionApi.resolveChatId(sessionId);
      if (!chatId) return;
      const history = await chatApi.getChat(chatId).catch(() => null);
      if (!history || history.status !== "running") {
        reconnectTriggeredForRef.current = null;
        return;
      }
      const reconnectAttemptKey = `${chatId}:${chatInstanceKey}`;
      if (reconnectTriggeredForRef.current === reconnectAttemptKey) return;
      reconnectTriggeredForRef.current = reconnectAttemptKey;
      chatRef.current?.input?.submit?.({
        query: "",
        biz_params: {
          reconnect: true,
        } as Record<string, unknown>,
      });
    };

    void tryReconnectRunningSession();
  }, [activeHistorySessionId, chatInstanceKey]);

  const removePendingImage = useCallback((id: string) => {
    setPendingImages((prev) => {
      const target = prev.find((item) => item.id === id);
      if (target?.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return prev.filter((item) => item.id !== id);
    });
  }, []);

  const clearPendingImages = useCallback(() => {
    setPendingImages((prev) => {
      prev.forEach((item) => {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      });
      return [];
    });
  }, []);

  useEffect(() => {
    return () => {
      pendingImagesRef.current.forEach((item) => {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      });
    };
  }, []);

  const addImageFiles = useCallback(async (files: File[]) => {
    const images = toImageFiles(files);
    if (!images.length) return;

    const uploadTasks = images.map(async (file) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const previewUrl = URL.createObjectURL(file);
      setPendingImages((prev) => [
        ...prev,
        {
          id,
          fileName: file.name || "image.png",
          previewUrl,
          uploading: true,
        },
      ]);

      try {
        const uploaded = await chatApi.uploadFile(file);
        setPendingImages((prev) =>
          prev.map((item) =>
            item.id === id
              ? {
                  ...item,
                  uploading: false,
                  uploadedUrl: chatApi.fileUrl(uploaded.url),
                }
              : item,
          ),
        );
      } catch (error) {
        setPendingImages((prev) =>
          prev.map((item) =>
            item.id === id
              ? {
                  ...item,
                  uploading: false,
                  error: error instanceof Error ? error.message : "上传失败",
                }
              : item,
          ),
        );
      }
    });

    await Promise.all(uploadTasks);
  }, []);

  const handleCaptureBackground = useCallback(async () => {
    try {
      if (!navigator.mediaDevices?.getDisplayMedia) {
        message.error("当前浏览器不支持截图能力");
        return;
      }

      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      });

      const video = document.createElement("video");
      video.srcObject = stream;
      await video.play();

      const baseCanvas = document.createElement("canvas");
      baseCanvas.width = video.videoWidth;
      baseCanvas.height = video.videoHeight;
      const baseCtx = baseCanvas.getContext("2d");
      if (!baseCtx) throw new Error("无法初始化截图画布");
      baseCtx.drawImage(video, 0, 0, baseCanvas.width, baseCanvas.height);

      const iframeEl = document.querySelector(
        `.${styles.canvasFrame}`,
      ) as HTMLIFrameElement | null;
      let finalCanvas = baseCanvas;
      if (iframeEl) {
        const rect = iframeEl.getBoundingClientRect();
        const ratioX = baseCanvas.width / window.innerWidth;
        const ratioY = baseCanvas.height / window.innerHeight;
        const sx = Math.max(0, Math.floor(rect.left * ratioX));
        const sy = Math.max(0, Math.floor(rect.top * ratioY));
        const sw = Math.max(1, Math.floor(rect.width * ratioX));
        const sh = Math.max(1, Math.floor(rect.height * ratioY));
        const cropCanvas = document.createElement("canvas");
        cropCanvas.width = sw;
        cropCanvas.height = sh;
        const cropCtx = cropCanvas.getContext("2d");
        if (cropCtx) {
          cropCtx.drawImage(baseCanvas, sx, sy, sw, sh, 0, 0, sw, sh);
          finalCanvas = cropCanvas;
        }
      }

      stream.getTracks().forEach((track) => track.stop());
      const blob = await new Promise<Blob | null>((resolve) =>
        finalCanvas.toBlob((value) => resolve(value), "image/png"),
      );
      if (!blob) {
        message.error("截图失败，请重试");
        return;
      }

      const file = new File([blob], `gridpaw-shot-${Date.now()}.png`, {
        type: "image/png",
      });
      await addImageFiles([file]);
    } catch (error) {
      message.error(
        `截图失败：${error instanceof Error ? error.message : "未知错误"}`,
      );
    }
  }, [addImageFiles, styles.canvasFrame]);

  useEffect(() => {
    const dock = chatDockRef.current;
    if (!dock) return;
    const onPaste = (event: ClipboardEvent) => {
      const files = filesFromClipboard(event);
      if (!files.length) return;
      event.preventDefault();
      void addImageFiles(files);
    };
    const onDragOver = (event: DragEvent) => {
      const hasImage = filesFromDrop(event).length > 0;
      if (!hasImage) return;
      event.preventDefault();
    };
    const onDrop = (event: DragEvent) => {
      const files = filesFromDrop(event);
      if (!files.length) return;
      event.preventDefault();
      void addImageFiles(files);
    };
    dock.addEventListener("paste", onPaste);
    dock.addEventListener("dragover", onDragOver);
    dock.addEventListener("drop", onDrop);
    return () => {
      dock.removeEventListener("paste", onPaste);
      dock.removeEventListener("dragover", onDragOver);
      dock.removeEventListener("drop", onDrop);
    };
  }, [addImageFiles, chatInstanceKey]);

  const customFetch = useCallback(
    async (data: {
      input?: unknown[];
      biz_params?: Record<string, unknown>;
      signal?: AbortSignal;
      session_id?: string;
      user_id?: string;
      channel?: string;
    }) => {
      const shouldReconnect = data.biz_params?.reconnect === true;
      if (!shouldReconnect) {
        setAgentStatus("正在思考");
        setAgentBusy(true);
      }

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      const token = getApiToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const selectedAgent = getSelectedAgentId();
      if (selectedAgent) headers["X-Agent-Id"] = selectedAgent;

      if (shouldReconnect) {
        const rawReconnect =
          data.session_id || window.currentSessionId || "";
        const reconnectSessionId =
          gridPawSessionApi.normalizeReconnectSessionId(rawReconnect);
        if (reconnectSessionId) {
          const response = await fetch(getApiUrl("/console/chat"), {
            method: "POST",
            headers,
            body: JSON.stringify({
              reconnect: true,
              session_id: reconnectSessionId,
              user_id: data.user_id || window.currentUserId || "default",
              channel: data.channel || window.currentChannel || "console",
            }),
            signal: data.signal,
          });
          if (!response.ok) {
            setAgentStatus("空闲中：就绪");
            setAgentBusy(false);
          }
          return response;
        }
      }

      const activeModels = await providerApi.getActiveModels().catch(() => null);
      const hasModel =
        !!activeModels?.active_llm?.provider_id && !!activeModels?.active_llm?.model;
      if (!hasModel) {
        message.warning("Please configure an active model first.");
        setAgentStatus("空闲中：就绪");
        setAgentBusy(false);
        return buildModelError();
      }

      const input = Array.isArray(data.input) ? data.input : [];
      const latestUserChunk = pickLatestUserInputChunk(input);
      const readyImages = pendingImagesRef.current.filter(
        (item) => !item.uploading && !!item.uploadedUrl,
      );
      const latestChunkWithImages =
        latestUserChunk && readyImages.length > 0
          ? {
              ...latestUserChunk,
              content: [
                ...(Array.isArray(latestUserChunk.content)
                  ? latestUserChunk.content
                  : []),
                ...readyImages.map((image) => ({
                  type: "image",
                  image_url: image.uploadedUrl as string,
                })),
              ],
            }
          : latestUserChunk;
      const rewrittenInput = latestUserChunk
        ? rewriteInputPayload([latestChunkWithImages as InputChunk])
        : [];
      const lastInput = rewrittenInput[rewrittenInput.length - 1] as
        | InputChunk
        | undefined;
      const sessionMeta = lastInput?.session || {};

      const sessionId =
        data.session_id ||
        window.currentSessionId ||
        sessionMeta.session_id ||
        Date.now().toString();
      const userId = data.user_id || window.currentUserId || sessionMeta.user_id || "default";
      const channel =
        data.channel || window.currentChannel || sessionMeta.channel || "console";

      window.currentSessionId = sessionId;
      window.currentUserId = userId;
      window.currentChannel = channel;
      if (readyImages.length > 0) {
        clearPendingImages();
      }

      return fetch(getApiUrl("/console/chat"), {
        method: "POST",
        headers,
        body: JSON.stringify({
          input: rewrittenInput,
          session_id: sessionId,
          user_id: userId,
          channel,
          stream: true,
          ...(data.biz_params || {}),
        }),
        signal: data.signal,
      });
    },
    [clearPendingImages],
  );

  const runtimeOptions = useMemo(() => {
    const primaryColor = theme === "azure" ? "#0b5f8f" : "#0d5f1d";
    const isUploadingImage = pendingImages.some((item) => item.uploading);
    return {
      theme: {
        colorPrimary: primaryColor,
        darkMode: false,
        prefix: "copaw",
        leftHeader: {
          title: "GridPaw 助手",
          logo: "",
        },
      },
      welcome: {
        greeting: "GridPaw助手已就绪",
        description:
          "",
        avatar: `${import.meta.env.BASE_URL}copaw-symbol.svg`,
        prompts: [
          // { value: "检查关键节点负荷并总结当前风险。" },
          // { value: "生成安全的倒换建议和执行步骤。" },
        ],
      },
      sender: {
        maxLength: 10000,
        beforeSubmit: async () => {
          if (isUploadingImage) {
            message.warning("图片仍在上传中，请稍候发送");
            return false;
          }
          return true;
        },
        beforeUI:
          pendingImages.length > 0 ? (
            <div className={styles.pendingImageStrip}>
              {pendingImages.map((item) => (
                <button
                  key={item.id}
                  className={styles.pendingImageItem}
                  type="button"
                  onClick={() => setImagePreviewUrl(item.previewUrl)}
                >
                  <img src={item.previewUrl} alt={item.fileName} />
                  {item.uploading && <span className={styles.pendingImageMask}>上传中</span>}
                  {item.error && <span className={styles.pendingImageError}>失败</span>}
                  <span
                    className={styles.pendingImageRemove}
                    onClick={(event) => {
                      event.stopPropagation();
                      removePendingImage(item.id);
                    }}
                  >
                    <X size={12} />
                  </span>
                </button>
              ))}
            </div>
          ) : undefined,
        attachments: {
          accept: "image/*",
          pastable: true,
          trigger: ({ disabled }: { disabled?: boolean }) => (
            <div className={styles.senderTriggerWrap}>
              <button
                type="button"
                className={styles.senderTriggerBtn}
                disabled={disabled}
                title="上传图片"
              >
                <Paperclip size={15} />
              </button>
              <button
                type="button"
                className={styles.senderTriggerBtn}
                disabled={disabled}
                title="截图"
                onMouseDown={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                }}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  (
                    event.nativeEvent as Event & {
                      stopImmediatePropagation?: () => void;
                    }
                  ).stopImmediatePropagation?.();
                  void handleCaptureBackground();
                }}
              >
                <Camera size={15} />
              </button>
            </div>
          ),
          customRequest: async (options: {
            file: File;
            onSuccess: (body: { url?: string; thumbUrl?: string }) => void;
            onError?: (error: Error) => void;
            onProgress?: (event: { percent?: number }) => void;
          }) => {
            try {
              const file = options.file;
              if (!file.type.startsWith("image/")) {
                message.error("目前仅支持图片");
                options.onError?.(new Error("Only image files are supported"));
                return;
              }
              const isLt10M = file.size / 1024 / 1024 < 10;
              if (!isLt10M) {
                message.error("图片大小不能超过 10MB");
                options.onError?.(new Error("Image exceeds 10MB"));
                return;
              }

              options.onProgress?.({ percent: 0 });
              const uploaded = await chatApi.uploadFile(file);
              options.onProgress?.({ percent: 100 });
              options.onSuccess({ url: chatApi.fileUrl(uploaded.url) });
            } catch (error) {
              options.onError?.(
                error instanceof Error ? error : new Error(String(error)),
              );
            }
          },
        },
      },
      session: {
        multiple: false,
        api: runtimeSessionApi,
      },
      customToolRenderConfig,
      api: {
        baseURL: "",
        token: "",
        fetch: customFetch,
        cancel: (data: { session_id?: string }) => {
          const stopId = gridPawSessionApi.getStopChatId(data.session_id);
          if (!stopId) return;
          void chatApi.stopConsoleChat(stopId);
        },
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [
    customFetch,
    customToolRenderConfig,
    handleCaptureBackground,
    pendingImages,
    removePendingImage,
    runtimeSessionApi,
    theme,
  ]);

  const flushPendingResize = useCallback(() => {
    if (pendingWidthRef.current !== null) {
      setDockWidth(pendingWidthRef.current);
    }
    if (pendingHeightRef.current !== null) {
      setDockHeight(pendingHeightRef.current);
    }
    resizeFrameRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      resizeCleanupRef.current?.();
    };
  }, []);

  const handleCornerResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (isCompact) return;
      event.preventDefault();
      event.stopPropagation();

      resizeCleanupRef.current?.();
      resizingRef.current = true;
      resizePointerIdRef.current = event.pointerId;
      const handle = event.currentTarget;
      handle.setPointerCapture?.(event.pointerId);
      document.body.style.userSelect = "none";
      document.body.style.cursor = "nesw-resize";

      const dockTop = TOP_BAR_GAP + TOP_BAR_HEIGHT + TOP_TO_DOCK_GAP;
      const dockRight = 20;

      const onMove = (moveEvent: PointerEvent) => {
        if (!resizingRef.current) return;
        if (
          resizePointerIdRef.current !== null &&
          moveEvent.pointerId !== resizePointerIdRef.current
        ) {
          return;
        }

        const centerLimitedWidth = window.innerWidth / 2 - dockRight;
        const maxWidth = Math.max(DOCK_MIN_WIDTH, centerLimitedWidth);
        const viewportMaxHeight = window.innerHeight - dockTop - DOCK_BOTTOM_GAP;
        const maxHeight = Math.max(DOCK_MIN_HEIGHT, viewportMaxHeight);
        const targetWidth = window.innerWidth - dockRight - (moveEvent.clientX - 5);
        const targetHeight = moveEvent.clientY - dockTop + 5;
        pendingWidthRef.current = clamp(targetWidth, DOCK_MIN_WIDTH, maxWidth);
        pendingHeightRef.current = clamp(
          targetHeight,
          DOCK_MIN_HEIGHT,
          maxHeight,
        );
        if (resizeFrameRef.current === null) {
          resizeFrameRef.current = window.requestAnimationFrame(flushPendingResize);
        }
      };

      const endResize = () => {
        if (!resizingRef.current) return;
        resizingRef.current = false;
        resizePointerIdRef.current = null;
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        if (resizeFrameRef.current !== null) {
          window.cancelAnimationFrame(resizeFrameRef.current);
          flushPendingResize();
        }
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", endResize);
        window.removeEventListener("pointercancel", endResize);
        window.removeEventListener("blur", endResize);
        resizeCleanupRef.current = null;
        try {
          if (handle.hasPointerCapture?.(event.pointerId)) {
            handle.releasePointerCapture(event.pointerId);
          }
        } catch {
          // ignore
        }
      };

      resizeCleanupRef.current = endResize;
      window.addEventListener("pointermove", onMove, { passive: true });
      window.addEventListener("pointerup", endResize);
      window.addEventListener("pointercancel", endResize);
      window.addEventListener("blur", endResize);
    },
    [flushPendingResize, isCompact],
  );

  const handleSelectHistorySession = useCallback((sessionId: string) => {
    const matched = historySessions.find(
      (item) => item.id === sessionId || item.sessionId === sessionId,
    );
    const resolvedSessionId = matched?.sessionId || sessionId;
    if (matched?.latestUsage) {
      applyUsageToContextRing(
        matched.latestUsage,
        resolvedSessionId,
        window.currentUserId || "default",
      );
    }
    setActiveHistorySessionId(sessionId);
    gridPawSessionApi.setPreferredSessionId(sessionId);
    window.currentSessionId = resolvedSessionId;
    setDockCollapsed(false);
    setHistoryMenuOpenId("");
    setChatInstanceKey((prev) => prev + 1);
  }, [applyUsageToContextRing, historySessions]);

  const handleDeleteHistorySession = useCallback(
    async (session: HistorySessionItem) => {
      if (!session.id || historyDeletingId === session.id) return;
      setHistoryDeletingId(session.id);
      try {
        await chatApi.deleteChat(session.id);
        message.success("会话已删除");
        setHistoryMenuOpenId("");
        await loadHistorySessions();

        const isActive =
          session.id === activeHistorySessionId ||
          session.sessionId === activeHistorySessionId;
        if (isActive) {
          const nextSessionId = gridPawSessionApi.createStandaloneSession(
            "New GridPaw Chat",
          );
          setActiveHistorySessionId(nextSessionId);
          gridPawSessionApi.setPreferredSessionId(nextSessionId);
          window.currentSessionId = nextSessionId;
          setChatInstanceKey((prev) => prev + 1);
        }
      } catch {
        message.error("删除会话失败");
      } finally {
        setHistoryDeletingId("");
      }
    },
    [activeHistorySessionId, historyDeletingId, loadHistorySessions],
  );

  const handleCreateNewSession = useCallback(() => {
    const sessionId = gridPawSessionApi.createStandaloneSession("New GridPaw Chat");
    setActiveHistorySessionId(sessionId);
    setDockCollapsed(false);
    gridPawSessionApi.setPreferredSessionId(sessionId);
    setChatInstanceKey((prev) => prev + 1);
  }, []);

  const visibleHistorySessions = useMemo(() => {
    if (!activeHistorySessionId) return historySessions;
    const exists = historySessions.some(
      (item) =>
        item.id === activeHistorySessionId || item.sessionId === activeHistorySessionId,
    );
    if (exists) return historySessions;
    return [
      {
        id: activeHistorySessionId,
        sessionId: activeHistorySessionId,
        title: `Session ${activeHistorySessionId.slice(-8)}`,
        updatedAt: null,
      },
      ...historySessions,
    ];
  }, [activeHistorySessionId, historySessions]);

  const dockStyle = useMemo(() => {
    const dockTop = TOP_BAR_GAP + TOP_BAR_HEIGHT + TOP_TO_DOCK_GAP;
    if (isCompact) return undefined;
    return {
      top: dockTop,
      width: dockWidth,
      height: dockHeight,
    };
  }, [dockHeight, dockWidth, isCompact]);

  const historyPanelStyle = useMemo(() => {
    const dockTop = TOP_BAR_GAP + TOP_BAR_HEIGHT + TOP_TO_DOCK_GAP;
    if (isCompact) return undefined;
    return {
      top: dockTop,
      right: dockWidth + 32,
      height: dockHeight,
    };
  }, [dockHeight, dockWidth, isCompact]);

  const handleNavigateCanvas = useCallback(() => {
    const normalized = normalizeAddress(addressInput);
    if (!normalized) {
      message.warning("Please enter a valid URL.");
      return;
    }
    setCanvasUrl(normalized);
    setAddressInput(normalized);
  }, [addressInput]);

  const planVM = useMemo(() => toPlanViewModel(currentPlan?.plan ?? null), [currentPlan]);
  const totalTasks = planVM?.tasks.length ?? 0;
  const doneCount =
    planVM?.tasks.filter((task) =>
      ["complete", "success"].includes(task.status.toLowerCase()),
    ).length ?? 0;
  const inProgressCount =
    planVM?.tasks.filter((task) => task.status.toLowerCase() === "in_progress")
      .length ?? 0;
  const progressPercent =
    totalTasks > 0 ? Math.round((doneCount / totalTasks) * 100) : 0;

  const loadContextUsage = useCallback(async () => {
    const sessionId = window.currentSessionId || activeHistorySessionId;
    const userId = window.currentUserId || "default";

    if (!sessionId) {
      setContextUsage(null);
      return;
    }

    const sessionUsage = gridPawSessionApi
      .getSessionSnapshot(sessionId)
      ?.meta?.latest_usage;
    if (isRecord(sessionUsage)) {
      const applied = applyUsageToContextRing(
        {
          input_tokens: readUsageValue(sessionUsage.input_tokens),
          output_tokens: readUsageValue(sessionUsage.output_tokens),
        },
        sessionId,
        userId,
      );
      if (applied) return;
    }

    setContextUsageLoading(true);
    try {
      const usage = await agentApi.getContextUsage(sessionId, userId);
      setContextUsage(usage);
    } catch (error) {
      console.warn("Failed to load GridPaw context usage", error);
    } finally {
      setContextUsageLoading(false);
    }
  }, [activeHistorySessionId, applyUsageToContextRing]);

  useEffect(() => {
    void loadContextUsage();
    const timer = window.setInterval(() => {
      void loadContextUsage();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [chatInstanceKey, loadContextUsage]);

  return (
    <div
      className={`${styles.gridpawRoot} ${
        theme === "azure" ? styles.themeAzure : ""
      }`}
    >
      <div className={styles.canvasLayer}>
        <iframe
          className={styles.canvasFrame}
          src={canvasUrl}
          title="GridPaw business canvas"
        />
        <div className={styles.canvasMask} />
      </div>

      {!topBarHidden && (
        <header className={styles.topBar}>
          <div className={styles.brandLogoWrap}>
            <img
              className={styles.brandLogo}
              src={gridPawLogo}
              alt="GridPaw"
            />
          </div>
          <div className={styles.toolbar}>
            <input
              className={styles.toolbarAddress}
              value={addressInput}
              onChange={(event) => setAddressInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  handleNavigateCanvas();
                }
              }}
              placeholder="输入网址（例如 https://dispatch.example.com）"
            />
            <button
              className={styles.toolbarBtn}
              type="button"
              onClick={handleNavigateCanvas}
            >
              跳转
            </button>
            <button
              className={styles.toolbarBtn}
              type="button"
              onClick={() => setTheme((prev) => (prev === "sage" ? "azure" : "sage"))}
            >
              主题: {theme === "sage" ? "鼠尾草" : "蔚蓝"}
            </button>
            <button
              className={styles.toolbarBtn}
              type="button"
              onClick={() =>
                window.open(
                  `${window.location.origin}${import.meta.env.BASE_URL}chat`,
                  "_blank",
                  "noopener,noreferrer",
                )
              }
            >
              Console后台
            </button>
            <button
              className={styles.toolbarBtn}
              type="button"
              onClick={() => setTopBarHidden(true)}
              title="隐藏系统栏"
            >
              隐藏系统栏
            </button>
          </div>
        </header>
      )}

      {historyOpen && !dockCollapsed && (
        <aside className={styles.historyPanel} style={historyPanelStyle}>
          <div className={styles.historyHeader}>
            <span>历史会话</span>
            <button
              className={styles.historyRefresh}
              type="button"
              onClick={() => void loadHistorySessions()}
            >
              刷新
            </button>
          </div>
          <div className={styles.historyList}>
            {visibleHistorySessions.map((session) => {
              const isActive =
                session.id === activeHistorySessionId ||
                session.sessionId === activeHistorySessionId;
              return (
                <div
                  key={session.id}
                  className={`${styles.historyItemWrap} ${
                    isActive ? styles.historyItemActive : ""
                  }`}
                >
                  <button
                    type="button"
                    className={styles.historyItem}
                    onClick={() => handleSelectHistorySession(session.id)}
                  >
                    <div className={styles.historyItemTitle}>{session.title}</div>
                    <div className={styles.historyItemTime}>
                      {formatSessionTime(session.updatedAt)}
                    </div>
                  </button>
                  <button
                    type="button"
                    className={styles.historyItemMore}
                    title="更多操作"
                    data-history-menu-interactive="true"
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setHistoryMenuOpenId((prev) =>
                        prev === session.id ? "" : session.id,
                      );
                    }}
                  >
                    ...
                  </button>
                  {historyMenuOpenId === session.id && (
                    <div
                      className={styles.historyItemMenu}
                      data-history-menu-interactive="true"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                      }}
                    >
                      <button
                        type="button"
                        className={styles.historyItemMenuAction}
                        data-history-menu-interactive="true"
                        disabled={historyDeletingId === session.id}
                        onClick={() => void handleDeleteHistorySession(session)}
                      >
                        {historyDeletingId === session.id ? "删除中..." : "删除会话"}
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </aside>
      )}

      {topBarHidden && (
        <button
          className={`${styles.edgeToggleBtn} ${styles.edgeTopBarBtn}`}
          type="button"
          onClick={() => setTopBarHidden(false)}
          title="显示系统栏"
        >
          <ChevronLeft size={18} />
        </button>
      )}

      {dockCollapsed && (
        <button
          className={`${styles.edgeToggleBtn} ${styles.edgeDockBtn}`}
          type="button"
          onClick={() => setDockCollapsed(false)}
          title="显示智能体窗口"
        >
          <Brain size={18} />
        </button>
      )}

      {!dockCollapsed && (
        <aside className={styles.chatDock} style={dockStyle} ref={chatDockRef}>
          {!isCompact && (
            <div
              className={styles.resizeHandleCorner}
              onPointerDown={handleCornerResizeStart}
            />
          )}
          <div className={styles.dockHeader}>
            <div className={styles.dockHeadLeft}>
              <button
                className={styles.dockAction}
                type="button"
                onClick={() => setHistoryOpen((prev) => !prev)}
              >
                {historyOpen ? "隐藏历史" : "历史会话"}
              </button>
              <button
                className={styles.dockAction}
                type="button"
                onClick={handleCreateNewSession}
              >
                新建会话
              </button>
            </div>
            <div className={styles.dockStatusCenter}>
              <span>{agentStatus}</span>
              {agentBusy && (
                <span className={styles.statusWave} aria-hidden="true">
                  <i />
                  <i />
                  <i />
                  <i />
                </span>
              )}
            </div>
            <div className={styles.dockActions}>
              <button
                className={styles.dockAction}
                type="button"
                onClick={() => setDockCollapsed(true)}
                title="隐藏窗口"
              >
                隐藏
              </button>
            </div>
          </div>
          <div className={styles.dockBody}>
            <AgentScopeRuntimeWebUI
              ref={chatRef}
              key={chatInstanceKey}
              options={runtimeOptions}
            />
            <ContextUsageRing
              usage={contextUsage}
              loading={contextUsageLoading}
              theme={theme === "azure" ? "azure" : "default"}
            />
            <button
              type="button"
              className={styles.planToggleBtn}
              onClick={() => setPlanPanelOpen((prev) => !prev)}
              title={planPanelOpen ? "收起当前计划" : "查看当前计划"}
            >
              当前计划
            </button>
            <aside
              className={`${styles.planPanel} ${planPanelOpen ? styles.planPanelOpen : ""}`}
            >
              <div className={styles.planPanelHeader}>
                <div className={styles.planPanelTitleWrap}>
                  <span className={styles.planPanelTitle}>当前计划</span>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {planLastUpdatedAt ? `上次更新：${planLastUpdatedAt}` : "上次更新：--:--:--"}
                  </Typography.Text>
                </div>
                <div className={styles.planPanelActions}>
                  <button
                    type="button"
                    className={styles.planPanelActionBtn}
                    onClick={() => void loadCurrentPlan(false)}
                    title="刷新计划"
                  >
                    刷新
                  </button>
                  <button
                    type="button"
                    className={styles.planPanelActionBtn}
                    onClick={() => setPlanPanelOpen(false)}
                    title="关闭"
                  >
                    关闭
                  </button>
                </div>
              </div>
              <div className={styles.planPanelBody}>
                <Spin spinning={planLoading}>
                  {currentPlan?.exists ? (
                    <>
                      <div className={styles.planPath}>{currentPlan.file_path}</div>
                      {planVM ? (
                        <>
                          <div className={styles.planSummary}>
                            <Typography.Title level={5} style={{ margin: 0 }}>
                              {planVM.name}
                            </Typography.Title>
                            <Typography.Text type="secondary">
                              共 {totalTasks} 项 · 已完成 {doneCount} 项 · 进行中 {inProgressCount} 项
                            </Typography.Text>
                            <div style={{ marginTop: 10 }}>
                              <Progress
                                percent={progressPercent}
                                status={inProgressCount > 0 ? "active" : "normal"}
                                size="small"
                              />
                            </div>
                          </div>
                          <div className={styles.planTaskList}>
                            {planVM.tasks.map((task, index) => {
                              const meta = getStatusMeta(task.status);
                              return (
                                <div key={`${task.name}-${index}`} className={styles.planTaskItem}>
                                  <div className={styles.planTaskHeader}>
                                    <Typography.Text strong>
                                      {index + 1}. {task.name || "未命名任务"}
                                    </Typography.Text>
                                    <Tag color={meta.color}>{meta.label}</Tag>
                                  </div>
                                  <Typography.Text type="secondary">
                                    {task.target || "暂无任务目标说明"}
                                  </Typography.Text>
                                </div>
                              );
                            })}
                          </div>
                        </>
                      ) : (
                        <div className={styles.planRaw}>
                          <Typography.Text type="secondary">
                            计划格式暂不标准，已展示原始内容：
                          </Typography.Text>
                          <pre>{JSON.stringify(currentPlan.plan, null, 2)}</pre>
                        </div>
                      )}
                    </>
                  ) : (
                    <Empty description="当前会话暂无计划" />
                  )}
                </Spin>
              </div>
            </aside>
          </div>
        </aside>
      )}

      {imagePreviewUrl && (
        <div
          className={styles.imagePreviewMask}
          onClick={() => setImagePreviewUrl("")}
          onDrop={(event: ReactDragEvent<HTMLDivElement>) => event.preventDefault()}
          onDragOver={(event: ReactDragEvent<HTMLDivElement>) => event.preventDefault()}
        >
          <img src={imagePreviewUrl} alt="预览图片" className={styles.imagePreviewLarge} />
        </div>
      )}
    </div>
  );
}
