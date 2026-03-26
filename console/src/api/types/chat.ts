export type ChatStatus = "idle" | "running";

export interface ChatSpec {
  id: string; // Chat UUID identifier
  name?: string;
  session_id: string; // Session identifier (channel:user_id format)
  user_id: string; // User identifier
  channel: string; // Channel name, default: "default"
  created_at: string | null; // Chat creation timestamp (ISO 8601)
  updated_at: string | null; // Chat last update timestamp (ISO 8601)
  meta?: Record<string, unknown>; // Additional metadata
  status?: ChatStatus; // Conversation status: idle or running
}

export interface Message {
  role: string;
  content: unknown;
  [key: string]: unknown;
}

export interface ChatHistory {
  messages: Message[];
  meta?: Record<string, unknown>;
  status?: ChatStatus; // Conversation status: idle or running
  /** Logical session id (ChatSpec.session_id); used for POST /console/chat reconnect */
  session_id?: string;
  user_id?: string;
  channel?: string;
}

export interface ChatDeleteResponse {
  success: boolean;
  chat_id: string;
}

// Legacy Session type alias for backward compatibility
export type Session = ChatSpec;
