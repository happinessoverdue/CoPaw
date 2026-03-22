import type {
  IAgentScopeRuntimeWebUIMessage,
  IAgentScopeRuntimeWebUISession,
} from "@agentscope-ai/chat";
import api, { type ChatSpec, type Message } from "../../../api";
import { chatApi } from "../../../api/modules/chat";

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const DEFAULT_SESSION_NAME = "New GridPaw Chat";
const ROLE_USER = "user";
const ROLE_TOOL = "tool";
const TYPE_PLUGIN_CALL_OUTPUT = "plugin_call_output";

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

type OutputMessage = Omit<Message, "role"> & {
  role: string;
  metadata: null;
  sequence_number?: number;
};

type ContentPart = Record<string, unknown>;

type ExtendedSession = IAgentScopeRuntimeWebUISession & {
  sessionId: string;
  userId: string;
  channel: string;
  meta: Record<string, unknown>;
  realId?: string;
};

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

function isLocalTimestamp(sessionId: string): boolean {
  return /^\d+$/.test(sessionId);
}

function readStringField(obj: Record<string, unknown>, key: string): string {
  const value = obj[key];
  return typeof value === "string" ? value : "";
}

function toDisplayUrl(url: string | undefined): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  return chatApi.fileUrl(url.startsWith("/") ? url : `/${url}`);
}

function contentToRequestParts(content: unknown): ContentPart[] {
  if (typeof content === "string") {
    return [{ type: "text", text: content, status: "created" }];
  }

  if (!Array.isArray(content)) {
    return [{ type: "text", text: String(content ?? ""), status: "created" }];
  }

  const parts: ContentPart[] = [];
  for (const rawPart of content) {
    if (!rawPart || typeof rawPart !== "object") continue;
    const part = rawPart as Record<string, unknown>;
    const type = readStringField(part, "type");
    if (type === "text") {
      const text = readStringField(part, "text");
      if (text) {
        parts.push({ type: "text", text, status: "created" });
      }
      continue;
    }

    if (type === "image") {
      const imageUrl = readStringField(part, "image_url");
      if (imageUrl) {
        parts.push({
          type: "image",
          image_url: toDisplayUrl(imageUrl),
          status: "created",
        });
      }
      continue;
    }

    if (type === "file") {
      const fileUrl = readStringField(part, "file_url");
      const fileId = readStringField(part, "file_id");
      const filename = readStringField(part, "filename");
      const fileName = readStringField(part, "file_name");
      const finalUrl = fileUrl || fileId;
      if (finalUrl) {
        parts.push({
          type: "file",
          file_url: toDisplayUrl(finalUrl),
          file_name: filename || fileName || "file",
          status: "created",
        });
      }
    }
  }

  if (parts.length === 0) {
    parts.push({ type: "text", text: "", status: "created" });
  }

  return parts;
}

function toOutputMessage(msg: Message): OutputMessage {
  return {
    ...msg,
    role:
      msg.type === TYPE_PLUGIN_CALL_OUTPUT && msg.role === "system"
        ? ROLE_TOOL
        : msg.role,
    metadata: null,
  };
}

function buildUserCard(msg: Message): IAgentScopeRuntimeWebUIMessage {
  const content = contentToRequestParts(msg.content);
  return {
    id: (msg.id as string) || generateId(),
    role: "user",
    cards: [
      {
        code: "AgentScopeRuntimeRequestCard",
        data: {
          input: [
            {
              role: "user",
              type: "message",
              content,
            },
          ],
        },
      },
    ],
  } as IAgentScopeRuntimeWebUIMessage;
}

function buildResponseCard(
  outputMessages: OutputMessage[],
): IAgentScopeRuntimeWebUIMessage {
  const now = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, item) => Math.max(max, item.sequence_number || 0),
    0,
  );

  return {
    id: generateId(),
    role: "assistant",
    cards: [
      {
        code: "AgentScopeRuntimeResponseCard",
        data: {
          id: `response_${generateId()}`,
          output: outputMessages,
          object: "response",
          status: "completed",
          created_at: now,
          sequence_number: maxSeq + 1,
          error: null,
          completed_at: now,
          usage: null,
        },
      },
    ],
    msgStatus: "finished",
  } as IAgentScopeRuntimeWebUIMessage;
}

function convertMessages(messages: Message[]): IAgentScopeRuntimeWebUIMessage[] {
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  let index = 0;

  while (index < messages.length) {
    const current = messages[index];
    if (current.role === ROLE_USER) {
      result.push(buildUserCard(current));
      index += 1;
      continue;
    }

    const outputs: OutputMessage[] = [];
    while (index < messages.length && messages[index].role !== ROLE_USER) {
      outputs.push(toOutputMessage(messages[index]));
      index += 1;
    }
    if (outputs.length > 0) {
      result.push(buildResponseCard(outputs));
    }
  }

  return result;
}

function chatSpecToSession(chat: ChatSpec): ExtendedSession {
  return {
    id: chat.id,
    name: (chat as ChatSpec & { name?: string }).name || DEFAULT_SESSION_NAME,
    sessionId: chat.session_id || chat.id,
    userId: chat.user_id || DEFAULT_USER_ID,
    channel: chat.channel || DEFAULT_CHANNEL,
    messages: [],
    meta: chat.meta || {},
  } as ExtendedSession;
}

class GridPawSessionApi {
  private sessionList: ExtendedSession[] = [];
  private sessionListRequest: Promise<ExtendedSession[]> | null = null;
  private preferredSessionId: string | null = null;

  private findSessionByAnyId(sessionId?: string | null): ExtendedSession | null {
    if (!sessionId) return null;
    return (
      this.sessionList.find(
        (item) =>
          item.id === sessionId ||
          item.realId === sessionId ||
          item.sessionId === sessionId,
      ) || null
    );
  }

  private updateWindowVariables(session: ExtendedSession): void {
    window.currentSessionId = session.sessionId || session.id || "";
    window.currentUserId = session.userId || DEFAULT_USER_ID;
    window.currentChannel = session.channel || DEFAULT_CHANNEL;
  }

  private createEmptySession(sessionId: string): ExtendedSession {
    const session: ExtendedSession = {
      id: sessionId,
      name: DEFAULT_SESSION_NAME,
      sessionId,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
      messages: [],
      meta: {},
    };
    this.updateWindowVariables(session);
    return session;
  }

  getStopChatId(sessionId?: string): string {
    if (!sessionId) return "";
    const session = this.findSessionByAnyId(sessionId);
    if (!session) return sessionId;
    return session.realId || session.id;
  }

  resolveChatId(sessionId?: string): string {
    if (!sessionId) return "";
    const session = this.findSessionByAnyId(sessionId);
    if (session?.realId) return session.realId;
    if (session?.id && !isLocalTimestamp(session.id)) return session.id;
    if (!session && !isLocalTimestamp(sessionId)) return sessionId;
    return "";
  }

  setPreferredSessionId(sessionId?: string | null): void {
    this.preferredSessionId = sessionId || null;
  }

  clearPreferredSessionId(): void {
    this.preferredSessionId = null;
  }

  createStandaloneSession(name?: string): string {
    const sessionId = Date.now().toString();
    const local: ExtendedSession = {
      id: sessionId,
      name: name || DEFAULT_SESSION_NAME,
      sessionId,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
      messages: [],
      meta: {},
    };
    this.sessionList.unshift(local);
    this.preferredSessionId = local.id;
    this.updateWindowVariables(local);
    return local.id;
  }

  async getSessionList(): Promise<IAgentScopeRuntimeWebUISession[]> {
    if (this.sessionListRequest) {
      return this.sessionListRequest;
    }

    this.sessionListRequest = (async () => {
      try {
        const previous = [...this.sessionList];
        const chats = await api.listChats();
        const remote = chats
          .filter((item) => item.id && item.id !== "undefined" && item.id !== "null")
          .map(chatSpecToSession)
          .reverse();

        const merged = remote.map((remoteSession) => {
          const existingBySessionId = previous.find(
            (item) => item.sessionId === remoteSession.sessionId,
          );
          if (!existingBySessionId) return remoteSession;

          return {
            ...remoteSession,
            id: isLocalTimestamp(existingBySessionId.id)
              ? existingBySessionId.id
              : remoteSession.id,
            realId: remoteSession.id,
            messages:
              existingBySessionId.messages && existingBySessionId.messages.length > 0
                ? existingBySessionId.messages
                : remoteSession.messages,
            meta:
              Object.keys(existingBySessionId.meta || {}).length > 0
                ? existingBySessionId.meta
                : remoteSession.meta,
          } as ExtendedSession;
        });

        const locals = previous.filter((item) => {
          if (!isLocalTimestamp(item.id)) return false;
          return !merged.some((mergedItem) => mergedItem.sessionId === item.sessionId);
        });

        const finalList = [...locals, ...merged];
        if (this.preferredSessionId) {
          finalList.sort((a, b) => {
            const aMatched =
              a.id === this.preferredSessionId ||
              a.realId === this.preferredSessionId ||
              a.sessionId === this.preferredSessionId;
            const bMatched =
              b.id === this.preferredSessionId ||
              b.realId === this.preferredSessionId ||
              b.sessionId === this.preferredSessionId;
            if (aMatched === bMatched) return 0;
            return aMatched ? -1 : 1;
          });
        }

        this.sessionList = finalList;
        return [...this.sessionList];
      } finally {
        this.sessionListRequest = null;
      }
    })();

    return this.sessionListRequest;
  }

  async getSession(sessionId: string): Promise<IAgentScopeRuntimeWebUISession> {
    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      return this.createEmptySession(Date.now().toString());
    }

    const existing = this.findSessionByAnyId(sessionId);
    if (existing?.messages?.length) {
      this.updateWindowVariables(existing);
      return existing;
    }

    if (isLocalTimestamp(sessionId) && !existing?.realId) {
      const local = existing || this.createEmptySession(sessionId);
      this.updateWindowVariables(local);
      return local;
    }

    const remoteId = existing?.realId || (!isLocalTimestamp(sessionId) ? sessionId : "");
    if (!remoteId) {
      const local = existing || this.createEmptySession(sessionId);
      this.updateWindowVariables(local);
      return local;
    }

    const chatHistory = await api.getChat(remoteId);
    const session: ExtendedSession = {
      id: existing?.id || sessionId,
      name: existing?.name || DEFAULT_SESSION_NAME,
      sessionId: existing?.sessionId || sessionId,
      userId: existing?.userId || DEFAULT_USER_ID,
      channel: existing?.channel || DEFAULT_CHANNEL,
      messages: convertMessages(chatHistory.messages || []),
      meta: existing?.meta || {},
      realId: remoteId,
    };

    const previousIndex = this.sessionList.findIndex((item) => item.id === session.id);
    if (previousIndex >= 0) {
      this.sessionList[previousIndex] = session;
    } else {
      this.sessionList.unshift(session);
    }

    this.updateWindowVariables(session);
    return session;
  }

  async createSession(
    session: Partial<IAgentScopeRuntimeWebUISession>,
  ): Promise<IAgentScopeRuntimeWebUISession[]> {
    const createdId = this.createStandaloneSession(session.name);
    const created = this.findSessionByAnyId(createdId);
    if (created) {
      created.messages = session.messages || [];
    }
    return [...this.sessionList];
  }

  async updateSession(
    session: Partial<IAgentScopeRuntimeWebUISession>,
  ): Promise<IAgentScopeRuntimeWebUISession[]> {
    if (!session.id) return [...this.sessionList];

    const existing = this.findSessionByAnyId(session.id);
    if (existing) {
      const next: ExtendedSession = {
        ...existing,
        ...session,
        id: existing.id,
        sessionId: existing.sessionId || session.id,
        userId: existing.userId || DEFAULT_USER_ID,
        channel: existing.channel || DEFAULT_CHANNEL,
        meta: existing.meta || {},
        messages: session.messages ?? existing.messages ?? [],
      } as ExtendedSession;
      const idx = this.sessionList.findIndex((item) => item.id === existing.id);
      this.sessionList[idx] = next;
      return [...this.sessionList];
    }

    const created: ExtendedSession = {
      id: session.id,
      name: session.name || DEFAULT_SESSION_NAME,
      sessionId: session.id,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
      messages: session.messages || [],
      meta: {},
    };
    this.sessionList.unshift(created);
    return [...this.sessionList];
  }

  async removeSession(
    session: Partial<IAgentScopeRuntimeWebUISession>,
  ): Promise<IAgentScopeRuntimeWebUISession[]> {
    if (!session.id) return [...this.sessionList];

    const existing = this.findSessionByAnyId(session.id);
    const deleteId = existing?.realId || (!isLocalTimestamp(session.id) ? session.id : "");
    if (deleteId) {
      await api.deleteChat(deleteId);
    }

    this.sessionList = this.sessionList.filter(
      (item) =>
        item.id !== session.id &&
        item.realId !== session.id &&
        item.sessionId !== session.id,
    );

    return [...this.sessionList];
  }
}

export default new GridPawSessionApi();
