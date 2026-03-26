import { request } from "../request";
import type {
  AgentContextUsage,
  AgentRequest,
  AgentsRunningConfig,
} from "../types";

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

  getAgentLanguage: () => request<{ language: string }>("/agent/language"),

  updateAgentLanguage: (language: string) =>
    request<{ language: string; copied_files: string[] }>("/agent/language", {
      method: "PUT",
      body: JSON.stringify({ language }),
    }),

  getCurrentPlan: (sessionId: string, userId: string = "default") => {
    const params = new URLSearchParams();
    params.set("session_id", sessionId);
    params.set("user_id", userId || "default");
    return request<CurrentPlanResponse>(`/agent/current-plan?${params.toString()}`);
  },

  getContextUsage: (sessionId: string, userId: string = "default") => {
    const params = new URLSearchParams();
    params.set("session_id", sessionId);
    params.set("user_id", userId || "default");
    return request<AgentContextUsage>(`/agent/context-usage?${params.toString()}`);
  },

  getAudioMode: () => request<{ audio_mode: string }>("/agent/audio-mode"),

  updateAudioMode: (audio_mode: string) =>
    request<{ audio_mode: string }>("/agent/audio-mode", {
      method: "PUT",
      body: JSON.stringify({ audio_mode }),
    }),

  getTranscriptionProviders: () =>
    request<{
      providers: { id: string; name: string; available: boolean }[];
      configured_provider_id: string;
    }>("/agent/transcription-providers"),

  updateTranscriptionProvider: (provider_id: string) =>
    request<{ provider_id: string }>("/agent/transcription-provider", {
      method: "PUT",
      body: JSON.stringify({ provider_id }),
    }),

  getTranscriptionProviderType: () =>
    request<{ transcription_provider_type: string }>(
      "/agent/transcription-provider-type",
    ),

  updateTranscriptionProviderType: (transcription_provider_type: string) =>
    request<{ transcription_provider_type: string }>(
      "/agent/transcription-provider-type",
      {
        method: "PUT",
        body: JSON.stringify({ transcription_provider_type }),
      },
    ),

  getLocalWhisperStatus: () =>
    request<{
      available: boolean;
      ffmpeg_installed: boolean;
      whisper_installed: boolean;
    }>("/agent/local-whisper-status"),
};
