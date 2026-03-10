import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
} from "@agentscope-ai/chat";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Modal,
  Button,
  Result,
  Spin,
  Empty,
  Tag,
  Progress,
  Typography,
  Divider,
} from "antd";
import {
  CloseOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
  SettingOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import defaultConfig, { getDefaultConfig } from "./OptionsPanel/defaultConfig";
import Weather from "./Weather";
import SendFileWithDefault from "./SendFile/SendFileWithDefault";
import { getApiToken, getApiUrl } from "../../api/config";
import { providerApi } from "../../api/modules/provider";
import ModelSelector from "./ModelSelector";
import { agentApi } from "../../api/modules/agent";
import type { CurrentPlanResponse } from "../../api/modules/agent";
import "./index.module.less";

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

function buildModelError(): Response {
  return new Response(
    JSON.stringify({
      error: "Model not configured",
      message: "Please configure a model first",
    }),
    { status: 400, headers: { "Content-Type": "application/json" } },
  );
}

type PlanTask = {
  name: string;
  target: string;
  status: string;
};

type PlanViewModel = {
  name: string;
  tasks: PlanTask[];
};

function toPlanViewModel(
  raw: Record<string, unknown> | null,
): PlanViewModel | null {
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

export default function ChatPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const chatId = useMemo(() => {
    const match = location.pathname.match(/^\/chat\/(.+)$/);
    return match?.[1];
  }, [location.pathname]);
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const [currentPlan, setCurrentPlan] = useState<CurrentPlanResponse | null>(null);
  const [planLastUpdatedAt, setPlanLastUpdatedAt] = useState<string>("");

  const isComposingRef = useRef(false);
  const isChatActiveRef = useRef(false);
  isChatActiveRef.current =
    location.pathname === "/" || location.pathname.startsWith("/chat");

  const lastSessionIdRef = useRef<string | null>(null);
  const chatIdRef = useRef(chatId);
  const navigateRef = useRef(navigate);
  chatIdRef.current = chatId;
  navigateRef.current = navigate;

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

  const handleTogglePlanPanel = async () => {
    if (planModalOpen) {
      setPlanModalOpen(false);
      return;
    }
    setPlanModalOpen(true);
    await loadCurrentPlan(false);
  };

  useEffect(() => {
    if (!planModalOpen) return;
    const timer = window.setInterval(() => {
      void loadCurrentPlan(true);
    }, 10000);
    return () => { window.clearInterval(timer); };
  }, [planModalOpen, loadCurrentPlan]);

  useEffect(() => {
    const handleCompositionStart = () => {
      if (!isChatActiveRef.current) return;
      isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
      if (!isChatActiveRef.current) return;
      setTimeout(() => {
        isComposingRef.current = false;
      }, 150);
    };

    const handleKeyPress = (e: KeyboardEvent) => {
      if (!isChatActiveRef.current) return;
      const target = e.target as HTMLElement;
      if (target?.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey) {
        if (isComposingRef.current || (e as any).isComposing) {
          e.stopPropagation();
          e.stopImmediatePropagation();
          return false;
        }
      }
    };

    document.addEventListener("compositionstart", handleCompositionStart, true);
    document.addEventListener("compositionend", handleCompositionEnd, true);
    document.addEventListener("keypress", handleKeyPress, true);

    return () => {
      document.removeEventListener(
        "compositionstart",
        handleCompositionStart,
        true,
      );
      document.removeEventListener(
        "compositionend",
        handleCompositionEnd,
        true,
      );
      document.removeEventListener("keypress", handleKeyPress, true);
    };
  }, []);

  useEffect(() => {
    sessionApi.onSessionIdResolved = (tempId, realId) => {
      if (!isChatActiveRef.current) return;
      if (chatIdRef.current === tempId) {
        lastSessionIdRef.current = realId;
        navigateRef.current(`/chat/${realId}`, { replace: true });
      }
    };

    sessionApi.onSessionRemoved = (removedId) => {
      if (!isChatActiveRef.current) return;
      if (chatIdRef.current === removedId) {
        lastSessionIdRef.current = null;
        navigateRef.current("/chat", { replace: true });
      }
    };

    return () => {
      sessionApi.onSessionIdResolved = null;
      sessionApi.onSessionRemoved = null;
    };
  }, []);

  const getSessionListWrapped = useCallback(async () => {
    const sessions = await sessionApi.getSessionList();
    const currentChatId = chatIdRef.current;

    if (currentChatId) {
      const idx = sessions.findIndex((s) => s.id === currentChatId);
      if (idx > 0) {
        return [
          sessions[idx],
          ...sessions.slice(0, idx),
          ...sessions.slice(idx + 1),
        ];
      }
    }

    return sessions;
  }, []);

  const getSessionWrapped = useCallback(async (sessionId: string) => {
    const currentChatId = chatIdRef.current;

    if (
      isChatActiveRef.current &&
      sessionId &&
      sessionId !== lastSessionIdRef.current &&
      sessionId !== currentChatId
    ) {
      const urlId = sessionApi.getRealIdForSession(sessionId) ?? sessionId;
      lastSessionIdRef.current = urlId;
      navigateRef.current(`/chat/${urlId}`, { replace: true });
    }

    return sessionApi.getSession(sessionId);
  }, []);

  const createSessionWrapped = useCallback(async (session: any) => {
    const result = await sessionApi.createSession(session);
    const newSessionId = result[0]?.id;
    if (isChatActiveRef.current && newSessionId) {
      lastSessionIdRef.current = newSessionId;
      navigateRef.current(`/chat/${newSessionId}`, { replace: true });
    }
    return result;
  }, []);

  const wrappedSessionApi = useMemo(
    () => ({
      getSessionList: getSessionListWrapped,
      getSession: getSessionWrapped,
      createSession: createSessionWrapped,
      updateSession: sessionApi.updateSession.bind(sessionApi),
      removeSession: sessionApi.removeSession.bind(sessionApi),
    }),
    [],
  );

  const customFetch = useCallback(
    async (data: {
      input: any[];
      biz_params?: any;
      signal?: AbortSignal;
    }): Promise<Response> => {
      try {
        const activeModels = await providerApi.getActiveModels();
        if (
          !activeModels?.active_llm?.provider_id ||
          !activeModels?.active_llm?.model
        ) {
          setShowModelPrompt(true);
          return buildModelError();
        }
      } catch {
        setShowModelPrompt(true);
        return buildModelError();
      }

      const { input, biz_params } = data;
      const session = input[input.length - 1]?.session || {};

      const requestBody = {
        input: input.slice(-1),
        session_id: window.currentSessionId || session?.session_id || "",
        user_id: window.currentUserId || session?.user_id || "default",
        channel: window.currentChannel || session?.channel || "console",
        stream: true,
        ...biz_params,
      };

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      const token = getApiToken();
      if (token) headers.Authorization = `Bearer ${token}`;

      return fetch(defaultConfig?.api?.baseURL || getApiUrl("/agent/process"), {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });
    },
    [],
  );

  const options = useMemo(() => {
    const i18nConfig = getDefaultConfig(t);

    const handleBeforeSubmit = async () => {
      if (isComposingRef.current) return false;
      return true;
    };

    return {
      ...i18nConfig,
      theme: {
        ...defaultConfig.theme,
        rightHeader: <ModelSelector />,
      },
      sender: {
        ...(i18nConfig as any)?.sender,
        beforeSubmit: handleBeforeSubmit,
      },
      session: { multiple: true, api: wrappedSessionApi },
      api: {
        ...defaultConfig.api,
        fetch: customFetch,
        cancel(data: { session_id: string }) {
          console.log(data);
        },
      },
      customToolRenderConfig: {
        "weather search mock": Weather,
        send_file_to_user: SendFileWithDefault,
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [wrappedSessionApi, customFetch, t]);

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

  return (
    <div style={{ height: "100%", width: "100%" }}>
      <AgentScopeRuntimeWebUI options={options} />

      <Button
        type="primary"
        icon={<UnorderedListOutlined />}
        onClick={handleTogglePlanPanel}
        style={{
          position: "fixed",
          right: 0,
          top: "50%",
          transform: "translateY(-50%)",
          zIndex: 1200,
          borderTopRightRadius: 0,
          borderBottomRightRadius: 0,
          boxShadow: "0 4px 12px rgba(0, 0, 0, 0.2)",
        }}
      >
        当前计划
      </Button>

      {planModalOpen && (
        <div
          style={{
            position: "fixed",
            right: 56,
            top: "50%",
            transform: "translateY(-50%)",
            width: 620,
            maxWidth: "calc(100vw - 72px)",
            maxHeight: "72vh",
            background: "#fff",
            border: "1px solid #f0f0f0",
            borderRadius: 12,
            boxShadow: "0 10px 30px rgba(0,0,0,0.15)",
            zIndex: 1199,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 14px",
              borderBottom: "1px solid #f0f0f0",
              fontSize: 16,
              fontWeight: 600,
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span>当前计划</span>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {planLastUpdatedAt
                  ? `上次更新：${planLastUpdatedAt}`
                  : "上次更新：--:--:--"}
              </Typography.Text>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => void loadCurrentPlan(false)}
                title="刷新计划"
              />
              <Button
                type="text"
                size="small"
                icon={<CloseOutlined />}
                onClick={() => setPlanModalOpen(false)}
                title="关闭"
              />
            </div>
          </div>

          <div style={{ padding: 12, overflow: "auto" }}>
            <Spin spinning={planLoading}>
              {currentPlan?.exists ? (
                <div>
                  <div style={{ marginBottom: 12, color: "#666", fontSize: 12 }}>
                    {currentPlan.file_path}
                  </div>

                  {planVM ? (
                    <div>
                      <div
                        style={{
                          padding: 12,
                          border: "1px solid #f0f0f0",
                          borderRadius: 10,
                          marginBottom: 12,
                          background: "#fafafa",
                        }}
                      >
                        <Typography.Title level={5} style={{ margin: 0 }}>
                          {planVM.name}
                        </Typography.Title>
                        <Typography.Text type="secondary">
                          共 {totalTasks} 项 · 已完成 {doneCount} 项 · 进行中{" "}
                          {inProgressCount} 项
                        </Typography.Text>
                        <div style={{ marginTop: 10 }}>
                          <Progress
                            percent={progressPercent}
                            status={inProgressCount > 0 ? "active" : "normal"}
                            size="small"
                          />
                        </div>
                      </div>

                      <div style={{ display: "grid", gap: 10 }}>
                        {planVM.tasks.map((task, index) => {
                          const meta = getStatusMeta(task.status);
                          return (
                            <div
                              key={`${task.name}-${index}`}
                              style={{
                                padding: 12,
                                border: "1px solid #f0f0f0",
                                borderRadius: 10,
                                background: "#fff",
                              }}
                            >
                              <div
                                style={{
                                  display: "flex",
                                  justifyContent: "space-between",
                                  alignItems: "center",
                                  gap: 8,
                                }}
                              >
                                <Typography.Text strong>
                                  {index + 1}. {task.name || "未命名任务"}
                                </Typography.Text>
                                <Tag color={meta.color}>{meta.label}</Tag>
                              </div>
                              <Divider style={{ margin: "10px 0" }} />
                              <Typography.Text type="secondary">
                                {task.target || "暂无任务目标说明"}
                              </Typography.Text>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : (
                    <div
                      style={{
                        maxHeight: "56vh",
                        overflow: "auto",
                        background: "#f7f7f7",
                        borderRadius: 8,
                        padding: 12,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}
                    >
                      <Typography.Text type="secondary">
                        计划格式暂不标准，已展示原始内容：
                      </Typography.Text>
                      <pre style={{ marginTop: 8 }}>
                        {JSON.stringify(currentPlan.plan, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ) : (
                <Empty description="当前会话暂无计划" />
              )}
            </Spin>
          </div>
        </div>
      )}

      <Modal open={showModelPrompt} closable={false} footer={null} width={480}>
        <Result
          icon={<ExclamationCircleOutlined style={{ color: "#faad14" }} />}
          title={t("modelConfig.promptTitle")}
          subTitle={t("modelConfig.promptMessage")}
          extra={[
            <Button key="skip" onClick={() => setShowModelPrompt(false)}>
              {t("modelConfig.skipButton")}
            </Button>,
            <Button
              key="configure"
              type="primary"
              icon={<SettingOutlined />}
              onClick={() => {
                setShowModelPrompt(false);
                navigate("/models");
              }}
            >
              {t("modelConfig.configureButton")}
            </Button>,
          ]}
        />
      </Modal>
    </div>
  );
}
