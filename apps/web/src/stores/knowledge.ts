import { defineStore } from "pinia";
import { ref } from "vue";
import TurndownService from "turndown";
import { useAuthStore, useFrontendMockData } from "./auth";
import { useSidebarStore, type SidebarProject } from "./sidebar";

export type KnowledgeNodeType = "folder" | "file";

export interface KnowledgeNode {
  id: number;
  name: string;
  type: KnowledgeNodeType;
  fileType: string | null;
  filePath: string | null;
  children: KnowledgeNode[];
}

export interface KnowledgeWorkspace {
  workspaceId: number;
  workspaceName: string;
  items: KnowledgeNode[];
}

interface UserDataNode {
  id: number;
  name: string;
  type: "workspace" | "folder" | "session" | "file";
  children?: UserDataNode[];
  extra_data?: Record<string, unknown>;
  file_type?: string;
  file_path?: string;
}

const toIdSet = (values: unknown): Set<number> => {
  if (!Array.isArray(values)) return new Set<number>();
  const ids = values
    .map((value) => (typeof value === "number" ? value : Number(value)))
    .filter((value) => Number.isInteger(value));
  return new Set<number>(ids);
};

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const MARKDOWN_EXTENSIONS = new Set(["md", "markdown", "mdx"]);
const TEXT_LIKE_EXTENSIONS = new Set([
  "txt",
  "text",
  "log",
  "csv",
  "tsv",
  "json",
  "xml",
  "yaml",
  "yml",
  "ini",
  "conf",
  "toml",
]);
const HTML_EXTENSIONS = new Set(["html", "htm"]);

const getExtension = (filename: string) => {
  const idx = filename.lastIndexOf(".");
  return idx >= 0 ? filename.slice(idx + 1).toLowerCase() : "";
};

const toMdFilename = (filename: string) => {
  const idx = filename.lastIndexOf(".");
  const base = idx >= 0 ? filename.slice(0, idx) : filename;
  return `${base}.md`;
};

const withExtension = (filename: string, extension: string) => {
  const idx = filename.lastIndexOf(".");
  const base = idx >= 0 ? filename.slice(0, idx) : filename;
  return `${base}.${extension}`;
};

const markdownFileFromText = (filename: string, content: string) =>
  new File([content], toMdFilename(filename), { type: "text/markdown;charset=utf-8" });

const htmlToMarkdown = (html: string) => {
  const turndown = new TurndownService({
    headingStyle: "atx",
    codeBlockStyle: "fenced",
    emDelimiter: "_",
  });
  return turndown.turndown(html || "").trim();
};

const convertDocumentToMarkdownFile = async (file: File): Promise<File | null> => {
  const ext = getExtension(file.name);

  if (MARKDOWN_EXTENSIONS.has(ext)) {
    return file;
  }

  if (TEXT_LIKE_EXTENSIONS.has(ext) || file.type.startsWith("text/")) {
    const text = await file.text();
    return markdownFileFromText(file.name, text);
  }

  if (HTML_EXTENSIONS.has(ext) || file.type === "text/html") {
    const html = await file.text();
    return markdownFileFromText(file.name, htmlToMarkdown(html));
  }

  if (file.type === DOCX_MIME || ext === "docx") {
    const mammothModule = (await import("mammoth/mammoth.browser")) as {
      convertToHtml: (input: { arrayBuffer: ArrayBuffer }) => Promise<{ value: string }>;
    };
    const arrayBuffer = await file.arrayBuffer();
    const { value: html } = await mammothModule.convertToHtml({ arrayBuffer });
    return markdownFileFromText(file.name, htmlToMarkdown(html));
  }

  return null;
};

const loadImageElementFromFile = async (file: File): Promise<HTMLImageElement> => {
  const src = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("Failed to decode image"));
      img.src = src;
    });
    return image;
  } finally {
    URL.revokeObjectURL(src);
  }
};

const dynamicTargetSize = (originalBytes: number) => {
  if (originalBytes <= 600 * 1024) return originalBytes;
  if (originalBytes <= 2 * 1024 * 1024) return 420 * 1024;
  if (originalBytes <= 8 * 1024 * 1024) return 900 * 1024;
  return 1600 * 1024;
};

const compressImageFileDynamic = async (file: File): Promise<File> => {
  const image = await loadImageElementFromFile(file);

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return file;

  const mimeType = "image/webp";
  const targetBytes = dynamicTargetSize(file.size);

  let width = image.naturalWidth;
  let height = image.naturalHeight;
  let quality = 0.9;
  let bestBlob: Blob | null = null;

  const encode = async () => {
    canvas.width = Math.max(1, Math.round(width));
    canvas.height = Math.max(1, Math.round(height));
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((b) => resolve(b), mimeType, quality);
    });
    return blob;
  };

  for (let i = 0; i < 9; i += 1) {
    const blob = await encode();
    if (!blob) break;

    if (!bestBlob || blob.size < bestBlob.size) {
      bestBlob = blob;
    }

    if (blob.size <= targetBytes) {
      bestBlob = blob;
      break;
    }

    const ratio = Math.sqrt(targetBytes / blob.size);
    const scale = Math.max(0.55, Math.min(0.92, ratio));
    width = Math.max(720, Math.floor(width * scale));
    height = Math.max(720, Math.floor(height * scale));
    quality = Math.max(0.5, quality - 0.08);
  }

  if (!bestBlob || bestBlob.size >= file.size) {
    return file;
  }

  const convertedName = withExtension(file.name, "webp");
  return new File([bestBlob], convertedName, { type: mimeType });
};

const preprocessUploadFile = async (file: File): Promise<File> => {
  if (file.type.startsWith("image/")) {
    return compressImageFileDynamic(file);
  }

  const markdownFile = await convertDocumentToMarkdownFile(file);
  if (markdownFile) {
    return markdownFile;
  }

  return file;
};

const fileToDataUrl = async (file: File): Promise<string> => {
  const arrayBuffer = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(arrayBuffer);
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  const base64 = btoa(binary);
  const mime = file.type || "application/octet-stream";
  return `data:${mime};base64,${base64}`;
};

const materialPayloadFromFile = async (
  file: File,
  folderId?: number,
): Promise<{
  title: string;
  type: "text" | "file_ref";
  folder_id?: number | null;
  raw_content?: string;
  meta_data: Record<string, unknown>;
}> => {
  const ext = getExtension(file.name);
  const isMarkdownLike =
    MARKDOWN_EXTENSIONS.has(ext) || file.type.startsWith("text/") || file.type === "text/markdown";

  const rawContent = isMarkdownLike ? await file.text() : await fileToDataUrl(file);

  return {
    title: file.name,
    type: isMarkdownLike ? "text" : "file_ref",
    folder_id: folderId ?? null,
    raw_content: rawContent,
    meta_data: {
      size_bytes: file.size,
      content_type: file.type || "application/octet-stream",
      original_name: file.name,
      storage: "inline_fallback",
    },
  };
};

export const useKnowledgeStore = defineStore("knowledge", () => {
  const authStore = useAuthStore();
  const workspaces = ref<KnowledgeWorkspace[]>([]);
  const isLoading = ref(false);

  let mockIdSeed = -10000;
  const nextMockId = () => mockIdSeed--;

  const parseKnowledgeChildren = (
    nodes: UserDataNode[],
    sessionFolderIds: Set<number>,
  ): KnowledgeNode[] => {
    const result: KnowledgeNode[] = [];
    for (const node of nodes) {
      if (node.type === "folder") {
        if (sessionFolderIds.has(node.id)) {
          continue;
        }
        result.push({
          id: node.id,
          name: node.name,
          type: "folder",
          fileType: null,
          filePath: null,
          children: node.children ? parseKnowledgeChildren(node.children, sessionFolderIds) : [],
        });
      } else if (node.type === "file") {
        result.push({
          id: node.id,
          name: node.name,
          type: "file",
          fileType: node.file_type ?? null,
          filePath: node.file_path ?? null,
          children: [],
        });
      }
    }
    return result;
  };

  /**
   * Sync knowledge workspaces from sidebar's cached userdata tree.
   * Does NOT fetch — reads from sidebarStore.rawUserDataTree.
   */
  const syncWithSessionWorkspaces = (sessionProjects: SidebarProject[]) => {
    if (!authStore.isAuthenticated()) {
      workspaces.value = [];
      return;
    }

    if (useFrontendMockData) {
      const existing = new Map(workspaces.value.map((w) => [w.workspaceId, w]));
      workspaces.value = sessionProjects.map((workspace) => {
        const prev = existing.get(workspace.id);
        return {
          workspaceId: workspace.id,
          workspaceName: workspace.name,
          items: prev?.items ?? [],
        };
      });
      return;
    }

    const sidebarStore = useSidebarStore();
    const tree: UserDataNode[] = sidebarStore.rawUserDataTree as UserDataNode[];

    const result: KnowledgeWorkspace[] = [];
    for (const node of tree) {
      if (node.type === "workspace" && sessionProjects.some((p) => p.id === node.id)) {
        const sessionFolderIds = toIdSet(node.extra_data?.session_folder_ids);
        result.push({
          workspaceId: node.id,
          workspaceName: node.name,
          items: node.children ? parseKnowledgeChildren(node.children, sessionFolderIds) : [],
        });
      }
    }
    workspaces.value = result;
  };

  const createKnowledgeItem = async (payload: {
    workspaceId: number;
    parentId?: number;
    name: string;
    isDirectory: boolean;
  }) => {
    if (useFrontendMockData) {
      const targetWorkspace = workspaces.value.find((w) => w.workspaceId === payload.workspaceId);
      if (!targetWorkspace) return false;
      const node: KnowledgeNode = {
        id: nextMockId(),
        name: payload.name,
        type: payload.isDirectory ? "folder" : "file",
        fileType: payload.isDirectory ? null : "file_ref",
        filePath: null,
        children: [],
      };
      if (!payload.parentId) {
        targetWorkspace.items.push(node);
        return true;
      }
      const stack = [...targetWorkspace.items];
      while (stack.length > 0) {
        const current = stack.shift()!;
        if (current.id === payload.parentId && current.type === "folder") {
          current.children.push(node);
          return true;
        }
        if (current.type === "folder") {
          stack.push(...current.children);
        }
      }
      return false;
    }

    if (payload.isDirectory) {
      const response = await fetch(
        `${authStore.effectiveBackendUrl}/api/workspaces/${payload.workspaceId}/folders`,
        {
          method: "POST",
          headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            name: payload.name,
            parent_id: payload.parentId ?? null,
          }),
        },
      );
      if (!response.ok) {
        throw new Error(`Failed to create knowledge folder: ${response.status}`);
      }
    } else {
      const response = await fetch(
        `${authStore.effectiveBackendUrl}/api/workspaces/${payload.workspaceId}/materials`,
        {
          method: "POST",
          headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            title: payload.name,
            type: "file_ref",
            folder_id: payload.parentId ?? null,
          }),
        },
      );
      if (!response.ok) {
        throw new Error(`Failed to create material: ${response.status}`);
      }
    }
    return true;
  };

  const renameKnowledgeItem = async (id: number, name: string, type: KnowledgeNodeType) => {
    if (useFrontendMockData) {
      for (const workspace of workspaces.value) {
        const stack = [...workspace.items];
        while (stack.length > 0) {
          const current = stack.shift()!;
          if (current.id === id) {
            current.name = name;
            return true;
          }
          if (current.type === "folder") stack.push(...current.children);
        }
      }
      return false;
    }

    if (type === "folder") {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/folders/${id}`, {
        method: "PUT",
        headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ name }),
      });
      if (!response.ok) {
        throw new Error(`Failed to rename knowledge folder: ${response.status}`);
      }
    } else {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/materials/${id}`, {
        method: "PUT",
        headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ title: name }),
      });
      if (!response.ok) {
        throw new Error(`Failed to rename material: ${response.status}`);
      }
    }
    return true;
  };

  const deleteKnowledgeItem = async (id: number, type: KnowledgeNodeType) => {
    if (useFrontendMockData) {
      const removeFrom = (nodes: KnowledgeNode[]): boolean => {
        const index = nodes.findIndex((n) => n.id === id);
        if (index >= 0) {
          nodes.splice(index, 1);
          return true;
        }
        for (const n of nodes) {
          if (n.type === "folder" && removeFrom(n.children)) return true;
        }
        return false;
      };
      for (const workspace of workspaces.value) {
        if (removeFrom(workspace.items)) return true;
      }
      return false;
    }

    if (type === "folder") {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/folders/${id}`, {
        method: "DELETE",
        headers: authStore.getAuthHeaders(),
      });
      if (!response.ok) {
        throw new Error(`Failed to delete knowledge folder: ${response.status}`);
      }
    } else {
      const response = await fetch(`${authStore.effectiveBackendUrl}/api/materials/${id}`, {
        method: "DELETE",
        headers: authStore.getAuthHeaders(),
      });
      if (!response.ok) {
        throw new Error(`Failed to delete material: ${response.status}`);
      }
    }
    return true;
  };

  const uploadKnowledgeFile = async (payload: {
    file: File;
    workspaceId?: number;
    folderId?: number;
    materialId?: number;
  }) => {
    if (useFrontendMockData) {
      return true;
    }

    const processedFile = await preprocessUploadFile(payload.file);

    const formData = new FormData();
    formData.append("file", processedFile);

    if (payload.materialId) {
      const response = await fetch(
        `${authStore.effectiveBackendUrl}/api/materials/${payload.materialId}/upload`,
        {
          method: "PUT",
          headers: authStore.getAuthHeaders(),
          body: formData,
        },
      );
      if (!response.ok && response.status !== 404) {
        throw new Error(`Failed to upload material file: ${response.status}`);
      }
      if (response.status === 404) {
        const fallbackPayload = await materialPayloadFromFile(processedFile);
        const fallbackResponse = await fetch(
          `${authStore.effectiveBackendUrl}/api/materials/${payload.materialId}`,
          {
            method: "PUT",
            headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({
              title: fallbackPayload.title,
              raw_content: fallbackPayload.raw_content,
              meta_data: fallbackPayload.meta_data,
            }),
          },
        );
        if (!fallbackResponse.ok) {
          throw new Error(
            `Failed to upload material file via fallback: ${fallbackResponse.status}`,
          );
        }
      }
      return true;
    }

    if (!payload.workspaceId) {
      throw new Error("workspaceId is required when uploading as a new file");
    }

    if (payload.folderId) {
      formData.append("folder_id", String(payload.folderId));
    }

    const response = await fetch(
      `${authStore.effectiveBackendUrl}/api/workspaces/${payload.workspaceId}/materials/upload`,
      {
        method: "POST",
        headers: authStore.getAuthHeaders(),
        body: formData,
      },
    );
    if (!response.ok && response.status !== 404) {
      throw new Error(`Failed to upload material file: ${response.status}`);
    }

    if (response.status === 404) {
      const fallbackPayload = await materialPayloadFromFile(processedFile, payload.folderId);
      const fallbackResponse = await fetch(
        `${authStore.effectiveBackendUrl}/api/workspaces/${payload.workspaceId}/materials`,
        {
          method: "POST",
          headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify(fallbackPayload),
        },
      );
      if (!fallbackResponse.ok) {
        throw new Error(`Failed to upload material file via fallback: ${fallbackResponse.status}`);
      }
    }
    return true;
  };

  return {
    workspaces,
    isLoading,
    syncWithSessionWorkspaces,
    createKnowledgeItem,
    renameKnowledgeItem,
    deleteKnowledgeItem,
    uploadKnowledgeFile,
  };
});
