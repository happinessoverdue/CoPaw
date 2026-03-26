export interface AgentRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  channel?: string | null;
  [key: string]: unknown;
}

export interface AgentsRunningConfig {
  max_iters: number;
  llm_retry_enabled: boolean;
  llm_max_retries: number;
  llm_backoff_base: number;
  llm_backoff_cap: number;
  max_input_length: number;
  memory_compact_ratio: number;
  memory_reserve_ratio: number;
  tool_result_compact_recent_n: number;
  tool_result_compact_old_threshold: number;
  tool_result_compact_recent_threshold: number;
  tool_result_compact_retention_days: number;
}

export interface AgentContextUsage {
  session_id: string;
  user_id: string;
  used_tokens: number;
  max_input_tokens: number;
  compact_threshold_tokens: number;
  reserve_threshold_tokens: number;
  system_prompt_tokens: number;
  summary_tokens: number;
  messages_tokens: number;
  message_count: number;
  usage_ratio: number;
  compact_ratio: number;
  compact_threshold_ratio: number;
  has_compressed_summary: boolean;
}
