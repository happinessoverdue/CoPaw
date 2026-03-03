import { request } from "../request";
import type { AgentRequest, AgentsRunningConfig } from "../types";

export interface CurrentPlanResponse {
  exists: boolean;
  file_path: string;
  plan: Record<string, unknown> | null;
}

// Agent API
export const agentApi = {
  agentRoot: () => request<unknown>("/agent/"),

  healthCheck: () => request<unknown>("/agent/health"),

  agentApi: (body: AgentRequest) =>
    request<unknown>("/agent/process", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getProcessStatus: () => request<unknown>("/agent/admin/status"),

  shutdownSimple: () =>
    request<void>("/agent/shutdown", {
      method: "POST",
    }),

  shutdown: () =>
    request<void>("/agent/admin/shutdown", {
      method: "POST",
    }),

  getAgentRunningConfig: () =>
    request<AgentsRunningConfig>("/agent/running-config"),

  updateAgentRunningConfig: (config: AgentsRunningConfig) =>
    request<AgentsRunningConfig>("/agent/running-config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  getCurrentPlan: (sessionId: string, userId: string = "default") => {
    const params = new URLSearchParams();
    params.set("session_id", sessionId);
    params.set("user_id", userId || "default");
    return request<CurrentPlanResponse>(`/agent/current-plan?${params.toString()}`);
  },
};
