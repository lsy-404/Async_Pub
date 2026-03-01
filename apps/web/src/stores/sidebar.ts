import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { useAuthStore, useFrontendMockData } from "./auth";

export interface SidebarSession {
  id: number;
  name: string;
  type: "session";
}

export interface SidebarFolder {
  id: number;
  name: string;
  type: "folder";
  children: SidebarSession[];
}

export interface SidebarProject {
  id: number;
  name: string;
  items: (SidebarSession | SidebarFolder)[];
}

export interface SidebarStructure {
  projects: SidebarProject[];
}

export interface SessionMetadata {
  ai_context: SessionChatMessage[];
  transcription: string;
}

export interface SessionChatMessage {
  id?: number | string;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  created_at?: string;
  tool_calls?: Array<{
    id?: string;
    name?: string;
    position?: number;
    status?: "pending" | "executing" | "success" | "error";
    args?: Record<string, unknown>;
    result?: unknown;
  }>;
}

export interface SessionChatChunk {
  id?: string;
  object?: string;
  created?: number;
  model?: string;
  choices?: Array<{
    index?: number;
    delta?: {
      content?: string;
      tool_call_info?: {
        id?: string;
        name?: string;
        position?: number;
        status?: "pending" | "executing" | "success" | "error";
        args?: Record<string, unknown>;
        result?: unknown;
      };
    };
    finish_reason?: string | null;
  }>;
}

export interface SessionSummaryHeading {
  heading_no: number;
  title: string;
  chunk_id: string;
  chunk_offset: number;
  chunk_length: number;
  created_at?: string;
}

export interface SessionSummaryState {
  summary: string;
  index: SessionSummaryHeading[];
  updated_at?: string;
  loading?: boolean;
}

// Backend UserDataNode interface for API response
interface UserDataNode {
  id: number;
  name: string;
  type: "workspace" | "folder" | "session" | "file";
  children?: UserDataNode[];
  description?: string;
  extra_data?: Record<string, any>;
  model_id?: string;
  last_active_at?: string;
  file_type?: string;
  file_path?: string;
  meta_data?: Record<string, any>;
  created_at?: string;
}

const toIdSet = (values: unknown): Set<number> => {
  if (!Array.isArray(values)) return new Set<number>();
  const ids = values
    .map((value) => (typeof value === "number" ? value : Number(value)))
    .filter((value) => Number.isInteger(value));
  return new Set<number>(ids);
};

// Batch operation types
export type OperationType = "create" | "update" | "delete" | "move";
export type EntityType = "workspace" | "folder" | "session";

export interface FileSystemOperation {
  operation: OperationType;
  id?: number | null;
  type: EntityType;
  name?: string;
  parent_id?: number | null;
  is_directory?: boolean;
}

export interface BatchOperationRequest {
  operations: FileSystemOperation[];
}

export interface OperationResult {
  operation: OperationType;
  id?: number | null;
  type?: EntityType;
  success: boolean;
  error?: string;
  created_id?: number | null;
}

export interface BatchOperationResponse {
  success: boolean;
  results: OperationResult[];
  total: number;
  succeeded: number;
  failed: number;
}

export const useSidebarStore = defineStore("sidebar", () => {
  const authStore = useAuthStore();
  const structure = ref<SidebarStructure>({ projects: [] });
  const rawUserDataTree = ref<UserDataNode[]>([]);
  const isLoading = ref(false);

  const currentSessionId = ref<number | null>(null);
  const currentSessionMetadata = ref<SessionMetadata | null>(null);
  const mockSessionMetadata = ref<Record<number, SessionMetadata>>({});
  const sessionSummaries = ref<Record<number, SessionSummaryState>>({});
  const summaryCursors = ref<Record<number, number>>({});
  const summaryJobInFlight = ref<Record<number, boolean>>({});
  let mockIdSeed = -1;
  const nextMockId = () => mockIdSeed--;

  const createEmptyMetadata = (): SessionMetadata => ({
    ai_context: [],
    transcription: "",
  });

  const getAllSessions = () => {
    const sessions: SidebarSession[] = [];
    for (const project of structure.value.projects) {
      for (const item of project.items) {
        if (item.type === "session") {
          sessions.push(item);
        } else {
          sessions.push(...item.children);
        }
      }
    }
    return sessions;
  };

  const ensureCurrentSession = () => {
    const sessions = getAllSessions();
    if (sessions.length === 0) {
      currentSessionId.value = null;
      currentSessionMetadata.value = null;
      return;
    }

    const exists = sessions.some((s) => s.id === currentSessionId.value);
    if (!exists) {
      currentSessionId.value = sessions[0]!.id;
      const metadata = mockSessionMetadata.value[currentSessionId.value] || createEmptyMetadata();
      mockSessionMetadata.value[currentSessionId.value] = JSON.parse(JSON.stringify(metadata));
      currentSessionMetadata.value = JSON.parse(JSON.stringify(metadata));
    }
  };

  const createMockStructure = (): SidebarStructure => {
    const sessionIdA = nextMockId();
    const sessionIdB = nextMockId();
    const sessionIdC = nextMockId();
    const folderId = nextMockId();

    mockSessionMetadata.value[sessionIdA] = {
      ai_context: [
        { id: nextMockId(), role: "assistant", content: "欢迎来到前端 Mock 调试模式。" },
        { id: nextMockId(), role: "user", content: "先给我一份会前准备清单。" },
      ],
      transcription: "[Mock] 今天的会议重点：需求梳理、里程碑和风险。",
    };
    mockSessionMetadata.value[sessionIdB] = createEmptyMetadata();
    mockSessionMetadata.value[sessionIdC] = {
      ai_context: [
        { id: nextMockId(), role: "assistant", content: "这是一个仅本地状态的伪 Session。" },
      ],
      transcription: "",
    };

    return {
      projects: [
        {
          id: nextMockId(),
          name: "Mock Workspace Alpha",
          items: [
            {
              id: sessionIdA,
              name: "需求讨论",
              type: "session",
            },
            {
              id: folderId,
              name: "Sprint A",
              type: "folder",
              children: [
                {
                  id: sessionIdB,
                  name: "站会记录",
                  type: "session",
                },
              ],
            },
          ],
        },
        {
          id: nextMockId(),
          name: "Mock Workspace Beta",
          items: [
            {
              id: sessionIdC,
              name: "头脑风暴",
              type: "session",
            },
          ],
        },
      ],
    };
  };

  const applyMockOperation = (op: FileSystemOperation): OperationResult => {
    const result: OperationResult = {
      operation: op.operation,
      id: op.id,
      success: true,
    };

    const findFolder = (id: number) => {
      for (const project of structure.value.projects) {
        for (const item of project.items) {
          if (item.type === "folder" && item.id === id) {
            return { project, folder: item };
          }
        }
      }
      return null;
    };

    const findNodeById = (id: number) => {
      for (const project of structure.value.projects) {
        if (project.id === id) return { kind: "project" as const, project };
        for (const item of project.items) {
          if (item.id === id && item.type === "session")
            return { kind: "session" as const, project, session: item };
          if (item.id === id && item.type === "folder")
            return { kind: "folder" as const, project, folder: item };
          if (item.type === "folder") {
            const child = item.children.find((s) => s.id === id);
            if (child)
              return { kind: "session-in-folder" as const, project, folder: item, session: child };
          }
        }
      }
      return null;
    };

    if (op.operation === "create") {
      if (op.is_directory) {
        const folderId = op.id ?? nextMockId();
        const newFolder: SidebarFolder = {
          id: folderId,
          name: op.name || "New Folder",
          type: "folder",
          children: [],
        };

        if (op.parent_id) {
          const parentFolder = findFolder(op.parent_id);
          if (!parentFolder) {
            return { ...result, success: false, error: "parentFolderNotFound" };
          }
          parentFolder.project.items.push(newFolder);
          return result;
        }

        if (structure.value.projects.length === 0) {
          structure.value.projects.push({
            id: nextMockId(),
            name: "Mock Workspace",
            items: [],
          });
        }
        structure.value.projects[0]!.items.push(newFolder);
        return result;
      }

      const sessionId = op.id ?? nextMockId();
      const newSession: SidebarSession = {
        id: sessionId,
        name: op.name || "New Session",
        type: "session",
      };
      mockSessionMetadata.value[newSession.id] = createEmptyMetadata();

      if (op.parent_id) {
        const parentFolder = findFolder(op.parent_id);
        if (!parentFolder) {
          return { ...result, success: false, error: "parentFolderNotFound" };
        }
        parentFolder.folder.children.push(newSession);
        return result;
      }

      if (structure.value.projects.length === 0) {
        structure.value.projects.push({
          id: nextMockId(),
          name: "Mock Workspace",
          items: [],
        });
      }
      structure.value.projects[0]!.items.push(newSession);
      ensureCurrentSession();
      return result;
    }

    if (op.operation === "update") {
      if (op.id == null) {
        return { ...result, success: false, error: "itemNotFound" };
      }
      const node = findNodeById(op.id);
      if (!node || !op.name) {
        return { ...result, success: false, error: "itemNotFound" };
      }
      if (node.kind === "project") node.project.name = op.name;
      if (node.kind === "folder") node.folder.name = op.name;
      if (node.kind === "session" || node.kind === "session-in-folder") node.session.name = op.name;
      return result;
    }

    if (op.operation === "delete") {
      for (const project of structure.value.projects) {
        if (project.id === op.id) {
          project.items.forEach((item) => {
            if (item.type === "session") delete mockSessionMetadata.value[item.id];
            if (item.type === "folder")
              item.children.forEach((child) => delete mockSessionMetadata.value[child.id]);
          });
          structure.value.projects = structure.value.projects.filter((p) => p.id !== op.id);
          ensureCurrentSession();
          return result;
        }

        const index = project.items.findIndex((item) => item.id === op.id);
        if (index >= 0) {
          const [removed] = project.items.splice(index, 1);
          if (removed?.type === "session") {
            delete mockSessionMetadata.value[removed.id];
          }
          if (removed?.type === "folder") {
            removed.children.forEach((child) => delete mockSessionMetadata.value[child.id]);
          }
          ensureCurrentSession();
          return result;
        }

        for (const item of project.items) {
          if (item.type !== "folder") continue;
          const childIndex = item.children.findIndex((child) => child.id === op.id);
          if (childIndex >= 0) {
            const [removedChild] = item.children.splice(childIndex, 1);
            if (removedChild) delete mockSessionMetadata.value[removedChild.id];
            ensureCurrentSession();
            return result;
          }
        }
      }
      return { ...result, success: false, error: "itemNotFound" };
    }

    return { ...result, success: false, error: "unsupportedOperation" };
  };

  const fetchStructure = async () => {
    if (useFrontendMockData) {
      if (structure.value.projects.length === 0) {
        structure.value = createMockStructure();
      }
      ensureCurrentSession();
      return;
    }

    isLoading.value = true;
    try {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/userdata`, {
        headers: authStore.getAuthHeaders(),
      });
      if (response.ok) {
        const userDataTree: UserDataNode[] = await response.json();
        rawUserDataTree.value = userDataTree;
        // Transform UserDataNode[] to SidebarStructure
        structure.value = parseUserDataTree(userDataTree);
      }
    } catch (err) {
      console.error("Failed to fetch sidebar structure", err);
    } finally {
      isLoading.value = false;
    }
  };

  /**
   * Parse UserDataNode tree from backend to SidebarStructure.
   */
  const parseUserDataTree = (nodes: UserDataNode[]): SidebarStructure => {
    const projects: SidebarProject[] = [];

    for (const node of nodes) {
      if (node.type === "workspace") {
        const sessionFolderIds = toIdSet(node.extra_data?.session_folder_ids);
        const project: SidebarProject = {
          id: node.id,
          name: node.name,
          items: [],
        };

        if (node.children) {
          project.items = parseWorkspaceChildren(node.children, sessionFolderIds);
        }

        projects.push(project);
      }
    }

    return { projects };
  };

  /**
   * Parse children of a workspace node (folders and sessions).
   */
  const parseWorkspaceChildren = (
    children: UserDataNode[],
    sessionFolderIds: Set<number>,
  ): (SidebarSession | SidebarFolder)[] => {
    const items: (SidebarSession | SidebarFolder)[] = [];

    for (const child of children) {
      if (child.type === "folder") {
        const parsedChildren = child.children ? parseFolderChildren(child.children) : [];
        const isSessionFolder = sessionFolderIds.has(child.id) || parsedChildren.length > 0;
        if (!isSessionFolder) {
          continue;
        }

        const folder: SidebarFolder = {
          id: child.id,
          name: child.name,
          type: "folder",
          children: parsedChildren,
        };

        items.push(folder);
      } else if (child.type === "session") {
        items.push({
          id: child.id,
          name: child.name,
          type: "session",
        });
      }
      // Skip type="file" for now as it's not shown in sidebar
    }

    return items;
  };

  /**
   * Parse children of a folder node (sessions only for sidebar).
   */
  const parseFolderChildren = (children: UserDataNode[]): SidebarSession[] => {
    const sessions: SidebarSession[] = [];

    for (const child of children) {
      if (child.type === "session") {
        sessions.push({
          id: child.id,
          name: child.name,
          type: "session",
        });
      }
      // Note: Nested folders could be supported here if needed
    }

    return sessions;
  };

  /**
   * Execute file system operations.
   * This is the preferred method for file system modifications.
   */
  const executeBatchOperations = async (
    operations: FileSystemOperation[],
  ): Promise<BatchOperationResponse> => {
    if (useFrontendMockData) {
      const results = operations.map((op) => applyMockOperation(op));
      const succeeded = results.filter((r) => r.success).length;
      const response: BatchOperationResponse = {
        success: succeeded === operations.length,
        results,
        total: operations.length,
        succeeded,
        failed: operations.length - succeeded,
      };
      ensureCurrentSession();
      return response;
    }

    try {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/filesystem`, {
        method: "POST",
        headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ operations } as BatchOperationRequest),
      });

      if (response.ok) {
        const result: BatchOperationResponse = await response.json();
        // Refresh structure after successful operation
        if (result.success) {
          await fetchStructure();
        }
        return result;
      } else {
        throw new Error(`Operation failed: ${response.statusText}`);
      }
    } catch (err) {
      console.error("Failed to execute operations", err);
      throw err;
    }
  };

  /**
   * Create a new entity using filesystem batch API.
   * ID is auto-generated by the backend for CREATE operations.
   */
  const createItem = async (
    entityType: EntityType,
    name: string,
    parentId?: number | null,
  ): Promise<{ success: boolean; createdId?: number | null }> => {
    const result = await executeBatchOperations([
      {
        operation: "create",
        type: entityType,
        name,
        parent_id: parentId,
      },
    ]);
    const createdId = result.results?.[0]?.created_id;
    return { success: result.success, createdId };
  };

  /**
   * Update an existing entity's name using filesystem batch API.
   */
  const updateItem = async (entityType: EntityType, id: number, name: string): Promise<boolean> => {
    const result = await executeBatchOperations([
      {
        operation: "update",
        type: entityType,
        id,
        name,
      },
    ]);
    return result.success;
  };

  /**
   * Delete an entity using filesystem batch API.
   */
  const deleteItem = async (entityType: EntityType, id: number): Promise<boolean> => {
    const result = await executeBatchOperations([
      {
        operation: "delete",
        type: entityType,
        id,
      },
    ]);
    return result.success;
  };

  const createSession = async () => {
    if (useFrontendMockData) {
      const id = nextMockId();
      mockSessionMetadata.value[id] = createEmptyMetadata();
      return { session_id: id };
    }

    try {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/sessions`, {
        method: "POST",
        headers: authStore.getAuthHeaders(),
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (err) {
      console.error("Failed to create session", err);
    }
    return null;
  };

  const fetchSessionMetadata = async (id: number) => {
    if (useFrontendMockData) {
      const metadata = mockSessionMetadata.value[id] || createEmptyMetadata();
      mockSessionMetadata.value[id] = JSON.parse(JSON.stringify(metadata));
      currentSessionMetadata.value = JSON.parse(JSON.stringify(metadata));
      return;
    }

    try {
      const [messagesResponse, sessionResponse] = await Promise.all([
        fetch(`${authStore.effectiveBackendUrl}/api/sessions/${id}/messages`, {
          headers: authStore.getAuthHeaders(),
        }),
        fetch(`${authStore.effectiveBackendUrl}/api/sessions/${id}`, {
          headers: authStore.getAuthHeaders(),
        }),
      ]);

      let transcription = "";
      if (sessionResponse.ok) {
        const sessionData = (await sessionResponse.json()) as {
          transcription?: string | null;
        };
        transcription = sessionData.transcription ?? "";
      }

      const existingForCurrentSession =
        currentSessionId.value === id && currentSessionMetadata.value
          ? currentSessionMetadata.value
          : null;
      if (!transcription && existingForCurrentSession?.transcription) {
        transcription = existingForCurrentSession.transcription;
      }

      if (messagesResponse.ok) {
        const messages: {
          id: number;
          session_id: number;
          role: string;
          content: string;
          tool_calls?: Array<{
            id?: string;
            name?: string;
            position?: number;
            status?: "pending" | "executing" | "success" | "error";
            args?: Record<string, unknown>;
            result?: unknown;
          }> | null;
          created_at: string;
        }[] = await messagesResponse.json();
        currentSessionMetadata.value = {
          ai_context: messages.map((m) => ({
            id: m.id,
            role: m.role as "system" | "user" | "assistant" | "tool",
            content: m.content,
            tool_calls: m.tool_calls || undefined,
            created_at: m.created_at,
          })),
          transcription,
        };
      } else {
        // Session exists but may have no messages yet
        currentSessionMetadata.value = {
          ai_context: existingForCurrentSession?.ai_context ?? [],
          transcription,
        };
      }
    } catch (err) {
      console.error("Failed to fetch session metadata", err);
    }
  };

  const fetchSessionSummary = async (id: number) => {
    const existing = sessionSummaries.value[id] || { summary: "", index: [] };
    sessionSummaries.value[id] = { ...existing, loading: true };

    if (useFrontendMockData) {
      sessionSummaries.value[id] = {
        summary: existing.summary || "[Mock] 摘要内容将在这里显示。",
        index: existing.index || [],
        updated_at: existing.updated_at,
        loading: false,
      };
      return;
    }

    try {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/sessions/${id}/summary`, {
        headers: authStore.getAuthHeaders(),
      });
      if (response.ok) {
        const payload = (await response.json()) as SessionSummaryState;
        sessionSummaries.value[id] = { ...payload, loading: false };
        if (!(id in summaryCursors.value)) {
          const baseline = currentSessionMetadata.value?.transcription?.length ?? 0;
          summaryCursors.value[id] = baseline;
        }
      } else {
        sessionSummaries.value[id] = { ...existing, loading: false };
      }
    } catch (err) {
      sessionSummaries.value[id] = { ...existing, loading: false };
    }
  };

  const enqueueSummaryJob = async (
    sessionId: number,
    payload: { chunk: string; chunk_offset?: number; chunk_length?: number; total_length?: number },
  ) => {
    if (!payload.chunk?.trim()) return;
    if (summaryJobInFlight.value[sessionId]) return;

    summaryJobInFlight.value[sessionId] = true;

    if (useFrontendMockData) {
      const existing = sessionSummaries.value[sessionId] || { summary: "", index: [] };
      const headingNo = (existing.index?.length || 0) + 1;
      const title = payload.chunk.slice(0, 40) || `Chunk ${headingNo}`;
      const entry = {
        heading_no: headingNo,
        title,
        chunk_id: `${payload.chunk_offset ?? 0}-${payload.chunk_length ?? payload.chunk.length}`,
        chunk_offset: payload.chunk_offset ?? 0,
        chunk_length: payload.chunk_length ?? payload.chunk.length,
        created_at: new Date().toISOString(),
      } as SessionSummaryHeading;
      const section = `## ${headingNo}. ${title}\n- ${payload.chunk.slice(0, 120)}`;
      const newSummary = `${existing.summary ? `${existing.summary}\n\n` : ""}${section}`;
      sessionSummaries.value[sessionId] = {
        summary: newSummary,
        index: [...(existing.index || []), entry],
        updated_at: entry.created_at,
        loading: false,
      };
      summaryJobInFlight.value[sessionId] = false;
      return;
    }

    try {
      const response = await fetch(
        `${authStore.effectiveBackendUrl}/api/sessions/${sessionId}/summary/jobs`,
        {
          method: "POST",
          headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify(payload),
        },
      );
      if (response.ok) {
        const result = (await response.json()) as SessionSummaryState;
        sessionSummaries.value[sessionId] = { ...result, loading: false };
      }
    } catch (err) {
      // silent fail
    } finally {
      summaryJobInFlight.value[sessionId] = false;
    }
  };

  const setCurrentSession = (id: number | null) => {
    currentSessionId.value = id;
    if (id) {
      fetchSessionMetadata(id);
      fetchSessionSummary(id);
      if (!(id in summaryCursors.value)) {
        const baseline = currentSessionMetadata.value?.transcription?.length ?? 0;
        summaryCursors.value[id] = baseline;
      }
    } else {
      currentSessionMetadata.value = null;
    }
  };

  /**
   * Add a single message to a session via the DB messages API.
   */
  const addSessionMessage = async (
    sessionId: number,
    role: "user" | "assistant",
    content: string,
  ) => {
    if (useFrontendMockData) {
      const metadata = mockSessionMetadata.value[sessionId] || createEmptyMetadata();
      metadata.ai_context.push({
        id: nextMockId(),
        role,
        content,
        created_at: new Date().toISOString(),
      });
      mockSessionMetadata.value[sessionId] = JSON.parse(JSON.stringify(metadata));
      if (sessionId === currentSessionId.value) {
        currentSessionMetadata.value = JSON.parse(JSON.stringify(metadata));
      }
      return {
        id: metadata.ai_context[metadata.ai_context.length - 1]?.id,
        role,
        content,
        created_at: metadata.ai_context[metadata.ai_context.length - 1]?.created_at,
      };
    }

    try {
      const response = await fetch(
        `${authStore.effectiveBackendUrl}/api/sessions/${sessionId}/messages`,
        {
          method: "POST",
          headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ role, content }),
        },
      );
      if (response.ok) {
        const createdMessage = (await response.json()) as {
          id: number;
          session_id: number;
          role: string;
          content: string;
          created_at: string;
        };
        if (sessionId === currentSessionId.value && currentSessionMetadata.value) {
          currentSessionMetadata.value.ai_context.push({
            id: createdMessage.id,
            role: createdMessage.role as "system" | "user" | "assistant" | "tool",
            content: createdMessage.content,
            created_at: createdMessage.created_at,
          });
        }
        return createdMessage;
      }
    } catch (err) {
      // silently fail
    }

    return null;
  };

  const deleteSessionMessage = async (messageId: number) => {
    if (useFrontendMockData) {
      Object.values(mockSessionMetadata.value).forEach((meta) => {
        meta.ai_context = meta.ai_context.filter((m) => m.id !== messageId);
      });
      if (currentSessionMetadata.value) {
        currentSessionMetadata.value.ai_context = currentSessionMetadata.value.ai_context.filter(
          (m) => m.id !== messageId,
        );
      }
      return true;
    }

    try {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/messages/${messageId}`, {
        method: "DELETE",
        headers: authStore.getAuthHeaders(),
      });
      return response.ok;
    } catch {
      return false;
    }
  };

  const streamSessionChatCompletion = async (
    sessionId: number,
    payload: {
      content: string;
      model?: string;
      temperature?: number;
      transcription?: string;
      stream?: boolean;
      enable_tools?: boolean;
    },
    handlers: {
      onChunk?: (chunk: SessionChatChunk) => void;
      onDone?: () => void;
      onError?: (error: string) => void;
    } = {},
    signal?: AbortSignal,
  ) => {
    if (useFrontendMockData) {
      handlers.onChunk?.({
        choices: [{ delta: { content: "[Mock] 已收到消息，正在生成回答。" } }],
      });
      handlers.onDone?.();
      return;
    }

    const response = await fetch(
      `${authStore.effectiveBackendUrl}/api/sessions/${sessionId}/chat/completions`,
      {
        method: "POST",
        headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          content: payload.content,
          model: payload.model,
          temperature: payload.temperature,
          transcription: payload.transcription,
          stream: payload.stream ?? true,
          enable_tools: payload.enable_tools ?? true,
        }),
        signal,
      },
    );

    if (!response.ok || !response.body) {
      const detail = await response.text().catch(() => "");
      handlers.onError?.(detail || `HTTP ${response.status}`);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const event of events) {
        const lines = event
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;

          if (raw === "[DONE]") {
            handlers.onDone?.();
            continue;
          }

          try {
            const parsed = JSON.parse(raw) as SessionChatChunk;
            handlers.onChunk?.(parsed);
          } catch {
            // ignore malformed stream chunk
          }
        }
      }
    }
  };

  const updateSessionMetadata = async (id: number, metadata: SessionMetadata) => {
    // Persist transcription to backend session metadata.
    if (useFrontendMockData) {
      const cloned = JSON.parse(JSON.stringify(metadata)) as SessionMetadata;
      mockSessionMetadata.value[id] = cloned;
      if (id === currentSessionId.value) {
        currentSessionMetadata.value = JSON.parse(JSON.stringify(cloned));
      }
      return;
    }

    try {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/sessions/${id}`, {
        method: "PUT",
        headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          transcription: metadata.transcription ?? "",
        }),
      });

      if (!response.ok) {
        const detail = await response.text().catch(() => "");
        throw new Error(detail || `HTTP ${response.status}`);
      }
    } catch (err) {
      console.error("Failed to persist session metadata", err);
    }

    // Always keep local state in sync with current editing state.
    if (id === currentSessionId.value) {
      currentSessionMetadata.value = JSON.parse(JSON.stringify(metadata));
    }
  };

  const findSessionLocation = (sessionId: number) => {
    for (const project of structure.value.projects) {
      for (const item of project.items) {
        if (item.type === "session" && item.id === sessionId) {
          return { projectId: project.id, folderId: undefined };
        }
        if (item.type === "folder") {
          const found = item.children.find((s) => s.id === sessionId);
          if (found) return { projectId: project.id, folderId: item.id };
        }
      }
    }
    return null;
  };

  const currentSession = computed(() => {
    if (!currentSessionId.value) return null;
    for (const project of structure.value.projects) {
      for (const item of project.items) {
        if (item.type === "session" && item.id === currentSessionId.value) return item;
        if (item.type === "folder") {
          const found = item.children.find((s) => s.id === currentSessionId.value);
          if (found) return found;
        }
      }
    }
    return null;
  });

  return {
    structure,
    rawUserDataTree,
    isLoading,
    currentSessionId,
    currentSessionMetadata,
    currentSession,
    sessionSummaries,
    summaryCursors,
    fetchStructure,
    executeBatchOperations,
    createItem,
    updateItem,
    deleteItem,
    createSession,
    setCurrentSession,
    fetchSessionMetadata,
    fetchSessionSummary,
    enqueueSummaryJob,
    addSessionMessage,
    deleteSessionMessage,
    streamSessionChatCompletion,
    updateSessionMetadata,
    findSessionLocation,
    addProject: async () => {
      const name = "New Workspace";
      const result = await createItem("workspace", name, null);
      if (result.success && result.createdId) {
        // createItem -> executeBatchOperations will refresh structure on success,
        // so we should read the created project from the refreshed state instead
        // of pushing again (which would cause duplicate workspace rows in UI).
        return structure.value.projects.find((project) => project.id === result.createdId) ?? null;
      }
      // Fallback: refresh from server
      await fetchStructure();
      return structure.value.projects[structure.value.projects.length - 1] ?? null;
    },
  };
});
