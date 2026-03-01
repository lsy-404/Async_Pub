<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from "vue";
import { RouterView } from "vue-router";
import { useI18n } from "vue-i18n";
import { useLocalStorage } from "@vueuse/core";
import {
  SidebarProvider,
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarMenuSub,
  SidebarMenuSubItem,
  SidebarMenuSubButton,
  SidebarInset,
  SidebarTrigger,
  SidebarFooter,
} from "@/components/ui/sidebar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Search,
  Check,
  Folder,
  Loader2,
  ChevronRight,
  Briefcase,
  MessageSquare,
  Languages,
  SunMoon,
  Sun,
  Moon,
  Pencil,
  Trash2,
  FolderPlus,
  Plus,
  Database,
  FileText,
} from "lucide-vue-next";
import { useAuthStore, useFrontendMockData } from "@/stores/auth";
import { useSidebarStore } from "@/stores/sidebar";
import type { SidebarProject, SidebarSession, SidebarFolder } from "@/stores/sidebar";
import { useKnowledgeStore, type KnowledgeNode, type KnowledgeWorkspace } from "@/stores/knowledge";
import AuthDialog from "@/components/auth/AuthDialog.vue";
import KnowledgeTreeNode from "@/components/knowledge/KnowledgeTreeNode.vue";

const { locale, t } = useI18n();
const savedLocale = useLocalStorage("app-locale", "zh-CN");
const savedThemeMode = useLocalStorage<"system" | "light" | "dark">("app-theme-mode", "system");
const authStore = useAuthStore();
const sidebarStore = useSidebarStore();
const knowledgeStore = useKnowledgeStore();
const authDialogOpen = ref(false);
const initialErrorMessage = ref("");
const searchQuery = ref("");
const sidebarMode = ref<"session" | "knowledge">("session");
const selectedKnowledgeWorkspaceId = ref<number | null>(null);
const knowledgeUploadTargetMaterialId = ref<number | null>(null);
const knowledgeUploadTargetWorkspaceId = ref<number | null>(null);
const knowledgeUploadTargetFolderId = ref<number | null>(null);
const knowledgeUploadInputRef = ref<HTMLInputElement | null>(null);
const knowledgeCreateDialogOpen = ref(false);
const knowledgeCreateType = ref<"folder" | "file">("folder");
const knowledgeCreateWorkspaceId = ref<number | null>(null);
const knowledgeCreateParentId = ref<number | undefined>(undefined);
const knowledgeCreateName = ref("");
const knowledgeCreateSubmitting = ref(false);
const knowledgeRenameDialogOpen = ref(false);
const knowledgeRenameDraft = ref("");
const knowledgeRenameTarget = ref<{ id: number; name: string; type: "folder" | "file" } | null>(
  null,
);
const knowledgeDeleteDialogOpen = ref(false);
const pendingKnowledgeDelete = ref<{ id: number; name: string; type: "folder" | "file" } | null>(
  null,
);
const knowledgeUploadLocationDialogOpen = ref(false);
const knowledgeUploadSelectedWorkspaceId = ref<number | null>(null);
const knowledgeUploadSelectedFolderId = ref<number | null>(null);
const systemPrefersDark = ref(false);
let colorSchemeMediaQuery: MediaQueryList | null = null;

const resolvedThemeMode = computed<"light" | "dark">(() => {
  if (savedThemeMode.value === "light" || savedThemeMode.value === "dark") {
    return savedThemeMode.value;
  }
  return systemPrefersDark.value ? "dark" : "light";
});

interface KnowledgeUploadLocationOption {
  key: string;
  workspaceId: number;
  folderId: number | null;
  label: string;
  depth: number;
  kind: "workspace" | "folder";
}

const SYSTEM_USER_ROOT_WORKSPACE_NAME = "__USER_ROOT__";

const isSystemUserRootWorkspace = (name: string) => name === SYSTEM_USER_ROOT_WORKSPACE_NAME;

const displayWorkspaceName = (name: string) =>
  isSystemUserRootWorkspace(name) ? t("sidebar.rootDirectoryLabel") : name;

const canManageWorkspace = (name: string) => !isSystemUserRootWorkspace(name);

const showAuthDialog = () => {
  authDialogOpen.value = true;
};

const applyThemeMode = () => {
  if (typeof document === "undefined") return;
  const isDark = resolvedThemeMode.value === "dark";
  document.documentElement.classList.toggle("dark", isDark);
  document.documentElement.style.colorScheme = isDark ? "dark" : "light";
};

const setThemeMode = (mode: "system" | "light" | "dark") => {
  savedThemeMode.value = mode;
};

const handleSystemColorSchemeChange = (event: MediaQueryListEvent) => {
  systemPrefersDark.value = event.matches;
};

const initThemeMode = () => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    applyThemeMode();
    return;
  }

  colorSchemeMediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  systemPrefersDark.value = colorSchemeMediaQuery.matches;

  if (typeof colorSchemeMediaQuery.addEventListener === "function") {
    colorSchemeMediaQuery.addEventListener("change", handleSystemColorSchemeChange);
  } else {
    colorSchemeMediaQuery.addListener(handleSystemColorSchemeChange);
  }

  applyThemeMode();
};

const refreshAllStructures = async () => {
  await sidebarStore.fetchStructure();
  await knowledgeStore.syncWithSessionWorkspaces(sidebarStore.structure.projects);
  if (!selectedKnowledgeWorkspaceId.value && knowledgeStore.workspaces.length > 0) {
    selectedKnowledgeWorkspaceId.value = knowledgeStore.workspaces[0]!.workspaceId;
  }
};

const handleAuthSaved = async () => {
  if (!authStore.isAuthenticated()) {
    sidebarStore.structure.projects = [];
    knowledgeStore.workspaces = [];
    return;
  }
  await refreshAllStructures();
};

onMounted(async () => {
  initThemeMode();

  if (useFrontendMockData) {
    authDialogOpen.value = false;
    await refreshAllStructures();
    return;
  }

  // 1. 检查URL参数中是否有token（邀请链接场景）
  const urlParams = new URLSearchParams(window.location.search);
  const urlToken = urlParams.get("token");
  const urlBackend = urlParams.get("backend");

  if (urlToken) {
    // 保存URL中的token和backend URL（如果提供）
    authStore.setToken(urlToken);
    if (urlBackend) {
      authStore.setBackendUrl(urlBackend);
    }

    // 验证token
    const result = await authStore.validateToken();

    // 清除URL中的敏感参数，避免刷新时重复验证或token泄露
    const url = new URL(window.location.href);
    url.searchParams.delete("token");
    url.searchParams.delete("backend");
    window.history.replaceState({}, "", url.toString());

    // 根据验证结果决定是否显示认证对话框
    if (!result.success) {
      initialErrorMessage.value = t(`auth.${result.error}`);
      authDialogOpen.value = true;
      // 验证失败时清除无效token
      authStore.setToken("");
    } else {
      await refreshAllStructures();
    }
    // 验证成功则不显示对话框，直接进入应用
    return;
  }

  // 2. 如果URL中没有token，检查localStorage中是否有token
  if (!authStore.token) {
    authDialogOpen.value = true;
    return;
  }

  // 3. 验证localStorage中的token
  const result = await authStore.validateToken();
  if (result.success) {
    await refreshAllStructures();
  } else {
    initialErrorMessage.value = t(`auth.${result.error}`);
    authDialogOpen.value = true;
  }
});

onUnmounted(() => {
  if (!colorSchemeMediaQuery) return;
  if (typeof colorSchemeMediaQuery.removeEventListener === "function") {
    colorSchemeMediaQuery.removeEventListener("change", handleSystemColorSchemeChange);
  } else {
    colorSchemeMediaQuery.removeListener(handleSystemColorSchemeChange);
  }
  colorSchemeMediaQuery = null;
});

watch(resolvedThemeMode, () => {
  applyThemeMode();
});

watch(
  () => sidebarStore.structure.projects.map((p) => `${p.id}:${p.name}`).join("|"),
  async () => {
    if (!authStore.isAuthenticated()) return;
    await knowledgeStore.syncWithSessionWorkspaces(sidebarStore.structure.projects);
  },
);

const inlineRenameDraft = ref("");
const inlineRenameTarget = ref<
  | { type: "session"; projectId: number; folderId?: number; id: number }
  | { type: "project"; id: number }
  | { type: "folder"; projectId: number; id: number }
  | null
>(null);
const inlineRenameStartedAt = ref(0);

const focusActiveInlineRenameInput = () => {
  nextTick(() => {
    requestAnimationFrame(() => {
      const doFocus = () => {
        const input = document.querySelector<HTMLInputElement>(
          'input[data-inline-rename="active"]',
        );
        if (!input) return false;
        input.focus();
        input.select();
        return document.activeElement === input;
      };

      if (!doFocus()) {
        setTimeout(doFocus, 0);
        setTimeout(doFocus, 48);
      }
    });
  });
};

const deleteDialogOpen = ref(false);
const pendingDelete = ref<{
  projectId: number;
  folderId?: number;
  id: number;
  name: string;
} | null>(null);

const folderDeleteDialogOpen = ref(false);
const pendingFolderDelete = ref<{ projectId: number; id: number; name: string } | null>(null);

const projectDeleteDialogOpen = ref(false);
const pendingProjectDelete = ref<{ id: number; name: string } | null>(null);

const beginInlineRename = (
  target:
    | { type: "session"; projectId: number; folderId?: number; id: number; currentName: string }
    | { type: "project"; id: number; currentName: string }
    | { type: "folder"; projectId: number; id: number; currentName: string },
) => {
  inlineRenameTarget.value =
    target.type === "project"
      ? { type: "project", id: target.id }
      : target.type === "folder"
        ? { type: "folder", projectId: target.projectId, id: target.id }
        : {
          type: "session",
          projectId: target.projectId,
          folderId: target.folderId,
          id: target.id,
        };
  inlineRenameDraft.value = target.currentName;
  inlineRenameStartedAt.value = Date.now();
  focusActiveInlineRenameInput();
};

const saveInlineRename = async () => {
  const normalized = inlineRenameDraft.value.trim();
  if (!normalized || !inlineRenameTarget.value) {
    inlineRenameTarget.value = null;
    inlineRenameDraft.value = "";
    return;
  }

  const target = inlineRenameTarget.value;
  const targetId = target.id;

  // Map UI type → entity type for the batch API
  const entityType = target.type === "project" ? "workspace" : target.type;
  // Use filesystem API to update the item
  await sidebarStore.updateItem(
    entityType as "workspace" | "folder" | "session",
    targetId,
    normalized,
  );

  inlineRenameTarget.value = null;
  inlineRenameDraft.value = "";
};

const cancelInlineRename = () => {
  inlineRenameTarget.value = null;
  inlineRenameDraft.value = "";
};

const isImeComposingEnter = (event: KeyboardEvent) => {
  const imeKeyCode = (event as KeyboardEvent & { keyCode?: number; which?: number }).keyCode;
  const imeWhich = (event as KeyboardEvent & { keyCode?: number; which?: number }).which;
  return event.isComposing || imeKeyCode === 229 || imeWhich === 229;
};

const handleInlineRenameKeydown = async (event: KeyboardEvent) => {
  if (isImeComposingEnter(event)) return;

  if (event.key === "Enter") {
    event.preventDefault();
    await saveInlineRename();
  }
  if (event.key === "Escape") {
    event.preventDefault();
    cancelInlineRename();
  }
};

const handleInlineRenameBlur = async () => {
  if (!inlineRenameTarget.value) return;

  // ContextMenu 关闭时可能回抢焦点，短时间内 blur 直接忽略并重新聚焦
  if (Date.now() - inlineRenameStartedAt.value < 220) {
    focusActiveInlineRenameInput();
    return;
  }

  await saveInlineRename();
};

const isInlineRenaming = (
  target:
    | { type: "project"; id: number }
    | { type: "folder"; projectId: number; id: number }
    | { type: "session"; projectId: number; folderId?: number; id: number },
) => {
  if (!inlineRenameTarget.value) return false;
  const current = inlineRenameTarget.value;
  return (
    current.type === target.type &&
    current.id === target.id &&
    (current.type === "project" ||
      current.projectId === (target as { projectId: number }).projectId) &&
    (current.type !== "session" || current.folderId === (target as { folderId?: number }).folderId)
  );
};

const inlineRenameContainerClass = (isRenaming: boolean) =>
  isRenaming
    ? "border-transparent! shadow-none! bg-transparent! hover:bg-transparent! active:bg-transparent! focus-visible:ring-0!"
    : "";

const inlineRenameInputClass =
  "h-6 min-w-0 px-1 text-xs focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring/40";

const confirmDeleteSession = async () => {
  if (!pendingDelete.value) return;

  const { id } = pendingDelete.value;

  // Use filesystem API to delete the session
  const success = await sidebarStore.deleteItem("session", id);

  // If the deleted session is currently active, return to empty-state page.
  if (success && sidebarStore.currentSessionId === id) {
    sidebarStore.setCurrentSession(null);
  }

  deleteDialogOpen.value = false;
  pendingDelete.value = null;
};

const cancelDeleteSession = () => {
  deleteDialogOpen.value = false;
  pendingDelete.value = null;
};

const confirmDeleteFolder = async () => {
  if (!pendingFolderDelete.value) return;

  const { id } = pendingFolderDelete.value;

  // Use filesystem API to delete the folder
  await sidebarStore.deleteItem("folder", id);

  folderDeleteDialogOpen.value = false;
  pendingFolderDelete.value = null;
};

const cancelDeleteFolder = () => {
  folderDeleteDialogOpen.value = false;
  pendingFolderDelete.value = null;
};

const confirmDeleteProject = async () => {
  if (!pendingProjectDelete.value) return;

  const { id } = pendingProjectDelete.value;

  if (sidebarStore.currentSessionId) {
    const loc = sidebarStore.findSessionLocation(sidebarStore.currentSessionId);
    if (loc?.projectId === id) {
      sidebarStore.setCurrentSession(null);
    }
  }

  // Use filesystem API to delete the project (workspace)
  await sidebarStore.deleteItem("workspace", id);

  projectDeleteDialogOpen.value = false;
  pendingProjectDelete.value = null;
};

const cancelDeleteProject = () => {
  projectDeleteDialogOpen.value = false;
  pendingProjectDelete.value = null;
};

const addSession = async (projectId: number, folderId?: number) => {
  if (!projectId) return;

  const name = t("sidebar.newSession");
  // Use batch API to create a session in the database
  const result = await sidebarStore.createItem("session", name, folderId ?? projectId);

  if (!result.success || !result.createdId) return;

  const newSessionId = result.createdId;

  sidebarStore.setCurrentSession(newSessionId);
  nextTick(() => {
    beginInlineRename({
      type: "session",
      projectId,
      folderId,
      id: newSessionId,
      currentName: name,
    });
  });
};

const addFolder = async (projectId: number) => {
  if (!projectId) return;

  const name = t("sidebar.newFolder");
  // Use batch API to create a folder in the workspace
  const result = await sidebarStore.createItem("folder", name, projectId);

  if (!result.success || !result.createdId) return;

  const newFolderId = result.createdId;

  nextTick(() => {
    beginInlineRename({
      type: "folder",
      projectId,
      id: newFolderId,
      currentName: name,
    });
  });
};

const creationDialogOpen = ref(false);
const creationType = ref<"session" | "folder" | null>(null);
const creationSubmitting = ref(false);
const creationSubmittingLocationKey = ref<string | null>(null);

const handleAddRequest = async (type: "session" | "folder" | "workspace") => {
  if (type === "workspace") {
    const newProject = await sidebarStore.addProject();
    if (newProject) {
      nextTick(() => {
        beginInlineRename({
          type: "project",
          id: newProject.id,
          currentName: newProject.name,
        });
      });
    }
    return;
  }

  creationType.value = type;
  creationDialogOpen.value = true;
};

const selectLocationForCreation = async (projectId: number, folderId?: number) => {
  if (creationSubmitting.value) return;

  creationSubmitting.value = true;
  creationSubmittingLocationKey.value = folderId
    ? `folder:${projectId}:${folderId}`
    : `workspace:${projectId}`;

  try {
    if (creationType.value === "session") {
      await addSession(projectId, folderId);
    } else if (creationType.value === "folder") {
      await addFolder(projectId);
    }
    creationDialogOpen.value = false;
    creationType.value = null;
  } finally {
    creationSubmitting.value = false;
    creationSubmittingLocationKey.value = null;
  }
};

const normalizeSearch = (value: string) => value.trim().toLowerCase();

const filteredProjects = computed<SidebarProject[]>(() => {
  const q = normalizeSearch(searchQuery.value);
  if (!q) return sidebarStore.structure.projects;

  return sidebarStore.structure.projects
    .map((project) => {
      const projectMatched = normalizeSearch(displayWorkspaceName(project.name)).includes(q);

      if (projectMatched) {
        return {
          ...project,
          items: project.items.map((item) =>
            item.type === "folder" ? { ...item, children: [...item.children] } : { ...item },
          ),
        };
      }

      const filteredItems: (SidebarSession | SidebarFolder)[] = project.items
        .map((item) => {
          if (item.type === "session") {
            return normalizeSearch(item.name).includes(q) ? { ...item } : null;
          }

          const folderMatched = normalizeSearch(item.name).includes(q);
          if (folderMatched) {
            return { ...item, children: [...item.children] };
          }

          const matchedChildren = item.children.filter((child) =>
            normalizeSearch(child.name).includes(q),
          );
          return matchedChildren.length > 0 ? { ...item, children: matchedChildren } : null;
        })
        .filter((item): item is SidebarSession | SidebarFolder => item !== null);

      if (filteredItems.length === 0) return null;
      return {
        ...project,
        items: filteredItems,
      };
    })
    .filter((project): project is SidebarProject => project !== null);
});

const filterKnowledgeNodes = (nodes: KnowledgeNode[], q: string): KnowledgeNode[] => {
  return nodes
    .map((node) => {
      const nameMatched = normalizeSearch(node.name).includes(q);
      if (node.type === "file") {
        return nameMatched ? { ...node } : null;
      }
      if (nameMatched) {
        return { ...node, children: [...node.children] };
      }
      const filteredChildren = filterKnowledgeNodes(node.children, q);
      return filteredChildren.length > 0 ? { ...node, children: filteredChildren } : null;
    })
    .filter((n): n is KnowledgeNode => n !== null);
};

const filteredKnowledgeWorkspaces = computed<KnowledgeWorkspace[]>(() => {
  const q = normalizeSearch(searchQuery.value);
  if (!q) return knowledgeStore.workspaces;

  return knowledgeStore.workspaces
    .map((ws) => {
      const wsNameMatched = normalizeSearch(displayWorkspaceName(ws.workspaceName)).includes(q);
      if (wsNameMatched) {
        return { ...ws, items: [...ws.items] };
      }
      const filteredItems = filterKnowledgeNodes(ws.items, q);
      return filteredItems.length > 0 ? { ...ws, items: filteredItems } : null;
    })
    .filter((ws): ws is KnowledgeWorkspace => ws !== null);
});

const activeKnowledgeWorkspace = computed(() => {
  if (!selectedKnowledgeWorkspaceId.value) return knowledgeStore.workspaces[0] || null;
  return (
    knowledgeStore.workspaces.find((w) => w.workspaceId === selectedKnowledgeWorkspaceId.value) ||
    null
  );
});

const knowledgeRootWorkspaceOptions = computed(() => {
  if (knowledgeStore.workspaces.length > 0) {
    return knowledgeStore.workspaces.map((workspace) => ({
      workspaceId: workspace.workspaceId,
      workspaceName: displayWorkspaceName(workspace.workspaceName),
      items: workspace.items,
    }));
  }

  return sidebarStore.structure.projects.map((project) => ({
    workspaceId: project.id,
    workspaceName: displayWorkspaceName(project.name),
    items: [] as KnowledgeNode[],
  }));
});

const resolveKnowledgeWorkspaceId = (preferredWorkspaceId?: number | null) => {
  if (typeof preferredWorkspaceId === "number") {
    return preferredWorkspaceId;
  }
  if (selectedKnowledgeWorkspaceId.value !== null) {
    return selectedKnowledgeWorkspaceId.value;
  }
  if (activeKnowledgeWorkspace.value) {
    return activeKnowledgeWorkspace.value.workspaceId;
  }
  return knowledgeRootWorkspaceOptions.value[0]?.workspaceId ?? null;
};

const selectKnowledgeWorkspace = (workspaceId: number) => {
  selectedKnowledgeWorkspaceId.value = workspaceId;
};

const pushKnowledgeFolderLocationOptions = (
  nodes: KnowledgeNode[],
  workspaceId: number,
  depth: number,
  result: KnowledgeUploadLocationOption[],
) => {
  for (const node of nodes) {
    if (node.type !== "folder") continue;

    result.push({
      key: `folder:${workspaceId}:${node.id}`,
      workspaceId,
      folderId: node.id,
      label: node.name,
      depth,
      kind: "folder",
    });

    if (node.children.length > 0) {
      pushKnowledgeFolderLocationOptions(node.children, workspaceId, depth + 1, result);
    }
  }
};

const knowledgeUploadLocationOptions = computed<KnowledgeUploadLocationOption[]>(() => {
  const result: KnowledgeUploadLocationOption[] = [];

  for (const workspace of knowledgeRootWorkspaceOptions.value) {
    result.push({
      key: `workspace:${workspace.workspaceId}`,
      workspaceId: workspace.workspaceId,
      folderId: null,
      label: workspace.workspaceName,
      depth: 0,
      kind: "workspace",
    });

    pushKnowledgeFolderLocationOptions(workspace.items, workspace.workspaceId, 1, result);
  }

  return result;
});

const hasKnowledgeUploadLocationSelected = computed(
  () => knowledgeUploadSelectedWorkspaceId.value !== null,
);

const selectKnowledgeUploadLocation = (workspaceId: number, folderId: number | null = null) => {
  knowledgeUploadSelectedWorkspaceId.value = workspaceId;
  knowledgeUploadSelectedFolderId.value = folderId;
  selectedKnowledgeWorkspaceId.value = workspaceId;
};

const openKnowledgeUploadLocationDialog = (prefill?: {
  workspaceId?: number;
  folderId?: number | null;
}) => {
  const defaultWorkspaceId = resolveKnowledgeWorkspaceId(prefill?.workspaceId ?? null);

  if (defaultWorkspaceId === null) return;

  selectKnowledgeUploadLocation(defaultWorkspaceId, prefill?.folderId ?? null);
  knowledgeUploadLocationDialogOpen.value = true;
};

const closeKnowledgeUploadLocationDialog = () => {
  knowledgeUploadLocationDialogOpen.value = false;
};

const openKnowledgeCreateDialog = (
  type: "folder" | "file",
  parentId?: number,
  workspaceId?: number,
) => {
  const targetWorkspaceId = resolveKnowledgeWorkspaceId(workspaceId ?? null);
  if (targetWorkspaceId === null) return;

  knowledgeCreateType.value = type;
  knowledgeCreateWorkspaceId.value = targetWorkspaceId;
  selectedKnowledgeWorkspaceId.value = targetWorkspaceId;
  knowledgeCreateParentId.value = parentId;
  knowledgeCreateName.value = type === "folder" ? t("sidebar.newFolder") : "untitled.txt";
  knowledgeCreateDialogOpen.value = true;
};

const confirmKnowledgeCreate = async () => {
  if (knowledgeCreateSubmitting.value) return;
  if (knowledgeCreateWorkspaceId.value === null) return;

  const name = knowledgeCreateName.value.trim();
  if (!name) return;

  knowledgeCreateSubmitting.value = true;
  try {
    await knowledgeStore.createKnowledgeItem({
      workspaceId: knowledgeCreateWorkspaceId.value,
      parentId: knowledgeCreateParentId.value,
      name,
      isDirectory: knowledgeCreateType.value === "folder",
    });

    await refreshAllStructures();
    knowledgeCreateDialogOpen.value = false;
    knowledgeCreateWorkspaceId.value = null;
    knowledgeCreateParentId.value = undefined;
    knowledgeCreateName.value = "";
  } finally {
    knowledgeCreateSubmitting.value = false;
  }
};

const cancelKnowledgeCreate = () => {
  if (knowledgeCreateSubmitting.value) return;
  knowledgeCreateDialogOpen.value = false;
  knowledgeCreateWorkspaceId.value = null;
  knowledgeCreateParentId.value = undefined;
  knowledgeCreateName.value = "";
};

const requestKnowledgeRename = (payload: { id: number; name: string; type: "folder" | "file" }) => {
  knowledgeRenameTarget.value = payload;
  knowledgeRenameDraft.value = payload.name;
  knowledgeRenameDialogOpen.value = true;
};

const confirmKnowledgeRename = async () => {
  if (!knowledgeRenameTarget.value) return;

  const name = knowledgeRenameDraft.value.trim();
  if (!name) return;

  await knowledgeStore.renameKnowledgeItem(
    knowledgeRenameTarget.value.id,
    name,
    knowledgeRenameTarget.value.type,
  );
  await refreshAllStructures();
  knowledgeRenameDialogOpen.value = false;
  knowledgeRenameTarget.value = null;
  knowledgeRenameDraft.value = "";
};

const cancelKnowledgeRename = () => {
  knowledgeRenameDialogOpen.value = false;
  knowledgeRenameTarget.value = null;
  knowledgeRenameDraft.value = "";
};

const requestKnowledgeDelete = (payload: { id: number; name: string; type: "folder" | "file" }) => {
  pendingKnowledgeDelete.value = payload;
  knowledgeDeleteDialogOpen.value = true;
};

const confirmKnowledgeDelete = async () => {
  if (!pendingKnowledgeDelete.value) return;

  await knowledgeStore.deleteKnowledgeItem(
    pendingKnowledgeDelete.value.id,
    pendingKnowledgeDelete.value.type,
  );
  await refreshAllStructures();

  knowledgeDeleteDialogOpen.value = false;
  pendingKnowledgeDelete.value = null;
};

const cancelKnowledgeDelete = () => {
  knowledgeDeleteDialogOpen.value = false;
  pendingKnowledgeDelete.value = null;
};

const handleKnowledgeAddFolder = async (payload: { parentId: number }) => {
  openKnowledgeCreateDialog("folder", payload.parentId);
};

const handleKnowledgeAddFile = async (payload: { parentId: number }) => {
  const workspaceId = resolveKnowledgeWorkspaceId();
  if (workspaceId === null) return;
  openKnowledgeUploadLocationDialog({ workspaceId, folderId: payload.parentId });
};

const requestKnowledgeUpload = (payload: { id: number }) => {
  // Upload from file node context menu means replacing that material's file.
  knowledgeUploadTargetMaterialId.value = payload.id;
  knowledgeUploadTargetWorkspaceId.value = null;
  knowledgeUploadTargetFolderId.value = null;
  knowledgeUploadInputRef.value?.click();
};

const requestKnowledgeUploadToWorkspaceRoot = () => {
  const workspaceId = resolveKnowledgeWorkspaceId();
  if (workspaceId === null) return;
  openKnowledgeUploadLocationDialog({ workspaceId, folderId: null });
};

const triggerKnowledgeUploadBySelectedLocation = () => {
  if (
    !hasKnowledgeUploadLocationSelected.value ||
    knowledgeUploadSelectedWorkspaceId.value === null
  )
    return;

  knowledgeUploadTargetMaterialId.value = null;
  knowledgeUploadTargetWorkspaceId.value = knowledgeUploadSelectedWorkspaceId.value;
  knowledgeUploadTargetFolderId.value = knowledgeUploadSelectedFolderId.value;
  knowledgeUploadLocationDialogOpen.value = false;
  knowledgeUploadInputRef.value?.click();
};

const createSubFolderFromKnowledgeUploadLocation = () => {
  if (
    !hasKnowledgeUploadLocationSelected.value ||
    knowledgeUploadSelectedWorkspaceId.value === null
  )
    return;

  selectedKnowledgeWorkspaceId.value = knowledgeUploadSelectedWorkspaceId.value;
  openKnowledgeCreateDialog(
    "folder",
    knowledgeUploadSelectedFolderId.value ?? undefined,
    knowledgeUploadSelectedWorkspaceId.value,
  );
};

const onKnowledgeFileSelected = async (event: Event) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) {
    input.value = "";
    return;
  }

  if (knowledgeUploadTargetMaterialId.value) {
    await knowledgeStore.uploadKnowledgeFile({
      file,
      materialId: knowledgeUploadTargetMaterialId.value,
    });
  } else if (knowledgeUploadTargetWorkspaceId.value) {
    await knowledgeStore.uploadKnowledgeFile({
      file,
      workspaceId: knowledgeUploadTargetWorkspaceId.value,
      folderId: knowledgeUploadTargetFolderId.value ?? undefined,
    });
  } else {
    input.value = "";
    return;
  }

  await refreshAllStructures();

  knowledgeUploadTargetMaterialId.value = null;
  knowledgeUploadTargetWorkspaceId.value = null;
  knowledgeUploadTargetFolderId.value = null;
  input.value = "";
};

// 切换语言并持久化
function setLanguage(lang: string) {
  locale.value = lang;
  savedLocale.value = lang;
}
</script>

<template>
  <SidebarProvider class="h-svh overflow-hidden">
    <Sidebar>
      <SidebarContent>
        <SidebarGroup class="pb-1">
          <div class="px-2 pt-1 pb-0.5">
            <div class="relative">
              <Search class="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input v-model="searchQuery" :placeholder="t('common.searchPlaceholder')" class="h-8 pl-8" />
            </div>
          </div>
        </SidebarGroup>

        <SidebarGroup class="pt-0 pb-1">
          <div class="px-2">
            <Tabs v-model="sidebarMode" class="w-full">
              <TabsList class="grid w-full grid-cols-2 h-8">
                <TabsTrigger value="session" class="text-xs">{{
                  t("sidebar.tabs.sessions")
                }}</TabsTrigger>
                <TabsTrigger value="knowledge" class="text-xs">{{
                  t("sidebar.tabs.knowledge")
                }}</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </SidebarGroup>

        <SidebarGroup v-if="sidebarMode === 'session'" class="pt-0">
          <SidebarGroupLabel>{{ t("common.workspaces") }}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <template v-if="filteredProjects.length === 0">
                <SidebarMenuItem>
                  <div class="px-2 py-2 text-xs text-muted-foreground/80">
                    {{ t("sidebar.searchNoResults") }}
                  </div>
                </SidebarMenuItem>
              </template>
              <template v-for="project in filteredProjects" :key="project.id">
                <Collapsible default-open as-child class="group/project">
                  <SidebarMenuItem>
                    <ContextMenu>
                      <ContextMenuTrigger as-child>
                        <CollapsibleTrigger v-if="project.items.length > 0" as-child>
                          <SidebarMenuButton :class="inlineRenameContainerClass(
                            isInlineRenaming({ type: 'project', id: project.id }),
                          )
                            ">
                            <Briefcase class="h-4 w-4" />
                            <Input v-if="isInlineRenaming({ type: 'project', id: project.id })"
                              data-inline-rename="active" v-model="inlineRenameDraft" :class="inlineRenameInputClass"
                              @click.stop @mousedown.stop @keydown.stop="handleInlineRenameKeydown"
                              @blur="handleInlineRenameBlur" />
                            <span v-else class="min-w-0 truncate">{{
                              displayWorkspaceName(project.name)
                            }}</span>
                            <ChevronRight v-if="!isInlineRenaming({ type: 'project', id: project.id })"
                              class="ml-auto h-4 w-4 transition-transform duration-200 group-data-[state=open]/project:rotate-90" />
                          </SidebarMenuButton>
                        </CollapsibleTrigger>
                        <SidebarMenuButton v-else :class="inlineRenameContainerClass(
                          isInlineRenaming({ type: 'project', id: project.id }),
                        )
                          ">
                          <Briefcase class="h-4 w-4" />
                          <Input v-if="isInlineRenaming({ type: 'project', id: project.id })"
                            data-inline-rename="active" v-model="inlineRenameDraft" :class="inlineRenameInputClass"
                            @click.stop @mousedown.stop @keydown.stop="handleInlineRenameKeydown"
                            @blur="handleInlineRenameBlur" />
                          <span v-else class="min-w-0 truncate">{{
                            displayWorkspaceName(project.name)
                          }}</span>
                          <span v-if="!isInlineRenaming({ type: 'project', id: project.id })"
                            class="ml-auto text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                            {{ t("sidebar.emptyIndicator") }}
                          </span>
                        </SidebarMenuButton>
                      </ContextMenuTrigger>
                      <ContextMenuContent class="w-36">
                        <ContextMenuItem @select="addSession(project.id)">
                          <Plus class="h-4 w-4" />
                          {{ t("sidebar.menu.newSession") }}
                        </ContextMenuItem>
                        <ContextMenuItem v-if="canManageWorkspace(project.name)" @select="
                          beginInlineRename({
                            type: 'project',
                            id: project.id,
                            currentName: project.name,
                          })
                          ">
                          <Pencil class="h-4 w-4" />
                          {{ t("sidebar.menu.rename") }}
                        </ContextMenuItem>
                        <ContextMenuItem v-if="canManageWorkspace(project.name)"
                          class="text-destructive focus:text-destructive" @select="
                            pendingProjectDelete = {
                              id: project.id,
                              name: displayWorkspaceName(project.name),
                            };
                          projectDeleteDialogOpen = true;
                          ">
                          <Trash2 class="h-4 w-4" />
                          {{ t("sidebar.menu.delete") }}
                        </ContextMenuItem>
                      </ContextMenuContent>
                    </ContextMenu>
                    <CollapsibleContent v-if="project.items.length > 0">
                      <SidebarMenuSub>
                        <template v-for="item in project.items" :key="item.id">
                          <!-- Folder -->
                          <Collapsible v-if="item.type === 'folder'" default-open as-child class="group/folder">
                            <SidebarMenuSubItem>
                              <ContextMenu>
                                <ContextMenuTrigger as-child>
                                  <CollapsibleTrigger v-if="item.children.length > 0" as-child>
                                    <SidebarMenuSubButton :class="inlineRenameContainerClass(
                                      isInlineRenaming({
                                        type: 'folder',
                                        projectId: project.id,
                                        id: item.id,
                                      }),
                                    )
                                      ">
                                      <Folder class="h-4 w-4" />
                                      <Input v-if="
                                        isInlineRenaming({
                                          type: 'folder',
                                          projectId: project.id,
                                          id: item.id,
                                        })
                                      " data-inline-rename="active" v-model="inlineRenameDraft"
                                        :class="inlineRenameInputClass" @click.stop @mousedown.stop
                                        @keydown.stop="handleInlineRenameKeydown" @blur="handleInlineRenameBlur" />
                                      <span v-else class="min-w-0 truncate">{{ item.name }}</span>
                                      <ChevronRight v-if="
                                        !isInlineRenaming({
                                          type: 'folder',
                                          projectId: project.id,
                                          id: item.id,
                                        })
                                      "
                                        class="ml-auto h-4 w-4 transition-transform duration-200 group-data-[state=open]/folder:rotate-90" />
                                    </SidebarMenuSubButton>
                                  </CollapsibleTrigger>
                                  <SidebarMenuSubButton v-else :class="inlineRenameContainerClass(
                                    isInlineRenaming({
                                      type: 'folder',
                                      projectId: project.id,
                                      id: item.id,
                                    }),
                                  )
                                    ">
                                    <Folder class="h-4 w-4" />
                                    <Input v-if="
                                      isInlineRenaming({
                                        type: 'folder',
                                        projectId: project.id,
                                        id: item.id,
                                      })
                                    " data-inline-rename="active" v-model="inlineRenameDraft"
                                      :class="inlineRenameInputClass" @click.stop @mousedown.stop
                                      @keydown.stop="handleInlineRenameKeydown" @blur="handleInlineRenameBlur" />
                                    <span v-else class="min-w-0 truncate">{{ item.name }}</span>
                                    <span v-if="
                                      !isInlineRenaming({
                                        type: 'folder',
                                        projectId: project.id,
                                        id: item.id,
                                      })
                                    "
                                      class="ml-auto text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                                      {{ t("sidebar.emptyIndicator") }}
                                    </span>
                                  </SidebarMenuSubButton>
                                </ContextMenuTrigger>
                                <ContextMenuContent class="w-36">
                                  <ContextMenuItem @select="addSession(project.id, item.id)">
                                    <Plus class="h-4 w-4" />
                                    {{ t("sidebar.menu.newSession") }}
                                  </ContextMenuItem>
                                  <ContextMenuItem @select="
                                    beginInlineRename({
                                      type: 'folder',
                                      projectId: project.id,
                                      id: item.id,
                                      currentName: item.name,
                                    })
                                    ">
                                    <Pencil class="h-4 w-4" />
                                    {{ t("sidebar.menu.rename") }}
                                  </ContextMenuItem>
                                  <ContextMenuItem class="text-destructive focus:text-destructive" @select="
                                    pendingFolderDelete = {
                                      projectId: project.id,
                                      id: item.id,
                                      name: item.name,
                                    };
                                  folderDeleteDialogOpen = true;
                                  ">
                                    <Trash2 class="h-4 w-4" />
                                    {{ t("sidebar.menu.delete") }}
                                  </ContextMenuItem>
                                </ContextMenuContent>
                              </ContextMenu>
                              <CollapsibleContent v-if="item.children.length > 0">
                                <SidebarMenuSub>
                                  <SidebarMenuSubItem v-for="session in item.children" :key="session.id">
                                    <ContextMenu>
                                      <ContextMenuTrigger as-child>
                                        <SidebarMenuSubButton :class="inlineRenameContainerClass(
                                          isInlineRenaming({
                                            type: 'session',
                                            projectId: project.id,
                                            folderId: item.id,
                                            id: session.id,
                                          }),
                                        )
                                          " @click="sidebarStore.setCurrentSession(session.id)"
                                          :is-active="sidebarStore.currentSessionId === session.id">
                                          <MessageSquare class="h-4 w-4" />
                                          <Input v-if="
                                            isInlineRenaming({
                                              type: 'session',
                                              projectId: project.id,
                                              folderId: item.id,
                                              id: session.id,
                                            })
                                          " data-inline-rename="active" v-model="inlineRenameDraft"
                                            :class="inlineRenameInputClass" @click.stop @mousedown.stop
                                            @keydown.stop="handleInlineRenameKeydown" @blur="handleInlineRenameBlur" />
                                          <span v-else class="min-w-0 truncate">{{
                                            session.name
                                          }}</span>
                                        </SidebarMenuSubButton>
                                      </ContextMenuTrigger>
                                      <ContextMenuContent class="w-36">
                                        <ContextMenuItem @select="addSession(project.id, item.id)">
                                          <Plus class="h-4 w-4" />
                                          {{ t("sidebar.menu.newSession") }}
                                        </ContextMenuItem>
                                        <ContextMenuItem @select="
                                          beginInlineRename({
                                            type: 'session',
                                            projectId: project.id,
                                            folderId: item.id,
                                            id: session.id,
                                            currentName: session.name,
                                          })
                                          ">
                                          <Pencil class="h-4 w-4" />
                                          {{ t("sidebar.menu.rename") }}
                                        </ContextMenuItem>
                                        <ContextMenuItem class="text-destructive focus:text-destructive" @select="
                                          pendingDelete = {
                                            projectId: project.id,
                                            folderId: item.id,
                                            id: session.id,
                                            name: session.name,
                                          };
                                        deleteDialogOpen = true;
                                        ">
                                          <Trash2 class="h-4 w-4" />
                                          {{ t("sidebar.menu.delete") }}
                                        </ContextMenuItem>
                                      </ContextMenuContent>
                                    </ContextMenu>
                                  </SidebarMenuSubItem>
                                </SidebarMenuSub>
                              </CollapsibleContent>
                            </SidebarMenuSubItem>
                          </Collapsible>

                          <!-- Direct Session in Project -->
                          <SidebarMenuSubItem v-else>
                            <ContextMenu>
                              <ContextMenuTrigger as-child>
                                <SidebarMenuSubButton :class="inlineRenameContainerClass(
                                  isInlineRenaming({
                                    type: 'session',
                                    projectId: project.id,
                                    id: item.id,
                                  }),
                                )
                                  " @click="
                                    !isInlineRenaming({
                                      type: 'session',
                                      projectId: project.id,
                                      id: item.id,
                                    }) && sidebarStore.setCurrentSession(item.id)
                                    " :is-active="sidebarStore.currentSessionId === item.id">
                                  <MessageSquare class="h-4 w-4" />
                                  <Input v-if="
                                    isInlineRenaming({
                                      type: 'session',
                                      projectId: project.id,
                                      id: item.id,
                                    })
                                  " data-inline-rename="active" v-model="inlineRenameDraft"
                                    :class="inlineRenameInputClass" @click.stop @mousedown.stop
                                    @keydown.stop="handleInlineRenameKeydown" @blur="handleInlineRenameBlur" />
                                  <span v-else class="min-w-0 truncate">{{ item.name }}</span>
                                </SidebarMenuSubButton>
                              </ContextMenuTrigger>
                              <ContextMenuContent class="w-36">
                                <ContextMenuItem @select="addSession(project.id)">
                                  <Plus class="h-4 w-4" />
                                  {{ t("sidebar.menu.newSession") }}
                                </ContextMenuItem>
                                <ContextMenuItem @select="
                                  beginInlineRename({
                                    type: 'session',
                                    projectId: project.id,
                                    id: item.id,
                                    currentName: item.name,
                                  })
                                  ">
                                  <Pencil class="h-4 w-4" />
                                  {{ t("sidebar.menu.rename") }}
                                </ContextMenuItem>
                                <ContextMenuItem class="text-destructive focus:text-destructive" @select="
                                  pendingDelete = {
                                    projectId: project.id,
                                    id: item.id,
                                    name: item.name,
                                  };
                                deleteDialogOpen = true;
                                ">
                                  <Trash2 class="h-4 w-4" />
                                  {{ t("sidebar.menu.delete") }}
                                </ContextMenuItem>
                              </ContextMenuContent>
                            </ContextMenu>
                          </SidebarMenuSubItem>
                        </template>
                      </SidebarMenuSub>
                    </CollapsibleContent>
                  </SidebarMenuItem>
                </Collapsible>
              </template>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup v-else class="pt-0">
          <SidebarGroupLabel>{{ t("sidebar.tabs.knowledge") }}</SidebarGroupLabel>
          <SidebarGroupContent>
            <div v-if="knowledgeStore.isLoading" class="px-2 py-2 text-xs text-muted-foreground/80">
              {{ t("auth.verifying") }}
            </div>
            <div v-else :class="filteredKnowledgeWorkspaces.length === 0 ? 'space-y-2 pb-2' : 'space-y-2 px-1 pb-2'">
              <div v-for="workspace in filteredKnowledgeWorkspaces" :key="workspace.workspaceId"
                class="rounded-md border border-border/60 overflow-hidden">
                <button
                  class="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm font-medium hover:bg-accent/40"
                  :class="selectedKnowledgeWorkspaceId === workspace.workspaceId ? 'bg-accent/30' : ''
                    " @click="selectKnowledgeWorkspace(workspace.workspaceId)">
                  <Database class="h-4 w-4" />
                  <span class="truncate">{{ displayWorkspaceName(workspace.workspaceName) }}</span>
                </button>

                <ul
                  v-if="selectedKnowledgeWorkspaceId === workspace.workspaceId || normalizeSearch(searchQuery).length > 0"
                  class="space-y-0.5 pb-1">
                  <KnowledgeTreeNode v-for="node in workspace.items" :key="node.id" :node="node"
                    @request-rename="requestKnowledgeRename" @request-delete="requestKnowledgeDelete"
                    @add-folder="handleKnowledgeAddFolder" @add-file="handleKnowledgeAddFile"
                    @upload="requestKnowledgeUpload" />
                </ul>
              </div>

              <div v-if="filteredKnowledgeWorkspaces.length === 0" class="px-2 py-2 text-xs text-muted-foreground/80">
                {{ t("sidebar.searchNoResults") }}
              </div>
            </div>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter class="p-2 flex flex-col gap-1 bg-transparent border-none">
        <template v-if="sidebarMode === 'session'">
          <Button variant="ghost" size="sm"
            class="w-full justify-start gap-2 h-9 px-3 text-sm font-medium hover:bg-muted/80 transition-colors"
            @click="handleAddRequest('session')">
            <Plus class="h-4 w-4 text-primary" />
            {{ t("sidebar.addSession") }}
          </Button>
          <Button variant="ghost" size="sm"
            class="w-full justify-start gap-2 h-9 px-3 text-sm font-medium hover:bg-muted/80 transition-colors"
            @click="handleAddRequest('folder')">
            <FolderPlus class="h-4 w-4 text-primary" />
            {{ t("sidebar.addFolder") }}
          </Button>
          <Button variant="ghost" size="sm"
            class="w-full justify-start gap-2 h-9 px-3 text-sm font-medium hover:bg-muted/80 transition-colors"
            @click="handleAddRequest('workspace')">
            <Briefcase class="h-4 w-4 text-primary" />
            {{ t("sidebar.addWorkspace") }}
          </Button>
        </template>
        <template v-else>
          <Button variant="ghost" size="sm"
            class="w-full justify-start gap-2 h-9 px-3 text-sm font-medium hover:bg-muted/80 transition-colors"
            @click="requestKnowledgeUploadToWorkspaceRoot">
            <FileText class="h-4 w-4 text-primary" />
            {{ t("sidebar.knowledge.addFile") }}
          </Button>
          <Button variant="ghost" size="sm"
            class="w-full justify-start gap-2 h-9 px-3 text-sm font-medium hover:bg-muted/80 transition-colors"
            @click="openKnowledgeCreateDialog('folder')">
            <FolderPlus class="h-4 w-4 text-primary" />
            {{ t("sidebar.addFolder") }}
          </Button>
        </template>
      </SidebarFooter>
    </Sidebar>

    <SidebarInset>
      <header class="flex h-14 items-center border-b px-4 lg:h-[60px]">
        <SidebarTrigger />
        <div class="w-4"></div>
        <h1 class="text-lg font-semibold">
          {{ sidebarStore.currentSession?.name || t("common.projectName") }}
        </h1>

        <div class="flex-1"></div>

        <div class="flex items-center gap-2 mr-4">
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button variant="ghost" size="sm" class="h-8 w-8 px-0">
                <SunMoon class="h-4 w-4" />
                <span class="sr-only">{{ t("theme.switch") }}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem @click="setThemeMode('system')">
                <span class="mr-2 inline-flex w-4 justify-center">
                  <Check class="h-4 w-4" :class="savedThemeMode === 'system' ? 'opacity-100' : 'opacity-0'" />
                </span>
                <SunMoon class="mr-2 h-4 w-4" />
                {{ t("theme.system") }}
              </DropdownMenuItem>
              <DropdownMenuItem @click="setThemeMode('light')">
                <span class="mr-2 inline-flex w-4 justify-center">
                  <Check class="h-4 w-4" :class="savedThemeMode === 'light' ? 'opacity-100' : 'opacity-0'" />
                </span>
                <Sun class="mr-2 h-4 w-4" />
                {{ t("theme.light") }}
              </DropdownMenuItem>
              <DropdownMenuItem @click="setThemeMode('dark')">
                <span class="mr-2 inline-flex w-4 justify-center">
                  <Check class="h-4 w-4" :class="savedThemeMode === 'dark' ? 'opacity-100' : 'opacity-0'" />
                </span>
                <Moon class="mr-2 h-4 w-4" />
                {{ t("theme.dark") }}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button variant="ghost" size="sm" class="h-8 w-8 px-0">
                <Languages class="h-4 w-4" />
                <span class="sr-only">{{ t("language.switch") }}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem @click="setLanguage('zh-CN')">
                <span class="mr-2 inline-flex w-4 justify-center">
                  <Check class="h-4 w-4" :class="locale === 'zh-CN' ? 'opacity-100' : 'opacity-0'" />
                </span>
                {{ t("language.zh") }}
              </DropdownMenuItem>
              <DropdownMenuItem @click="setLanguage('en-US')">
                <span class="mr-2 inline-flex w-4 justify-center">
                  <Check class="h-4 w-4" :class="locale === 'en-US' ? 'opacity-100' : 'opacity-0'" />
                </span>
                {{ t("language.en") }}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div class="flex items-center gap-3">
          <button class="rounded-full" @click="showAuthDialog">
            <Avatar class="h-8 w-8 text-white">
              <AvatarImage src="" alt="User" />
              <AvatarFallback class="bg-primary">{{
                (authStore.currentUser?.username || t("common.username")).charAt(0).toUpperCase()
              }}</AvatarFallback>
            </Avatar>
          </button>
        </div>
      </header>

      <main class="flex min-h-0 flex-1 flex-col overflow-hidden">
        <RouterView />
      </main>
    </SidebarInset>

    <AlertDialog v-model:open="deleteDialogOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t("sidebar.dialogs.deleteSessionTitle") }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{
              t("sidebar.dialogs.deleteSessionDesc", {
                name: pendingDelete?.name ?? t("sidebar.fallbacks.session"),
              })
            }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="cancelDeleteSession">{{
            t("common.cancel")
          }}</AlertDialogCancel>
          <AlertDialogAction class="bg-destructive text-white hover:bg-destructive/90" @click="confirmDeleteSession">
            {{ t("sidebar.dialogs.deleteAction") }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <AlertDialog v-model:open="folderDeleteDialogOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t("sidebar.dialogs.deleteFolderTitle") }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{
              t("sidebar.dialogs.deleteFolderDesc", {
                name: pendingFolderDelete?.name ?? t("sidebar.fallbacks.folder"),
              })
            }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="cancelDeleteFolder">{{
            t("common.cancel")
          }}</AlertDialogCancel>
          <AlertDialogAction class="bg-destructive text-white hover:bg-destructive/90" @click="confirmDeleteFolder">
            {{ t("sidebar.dialogs.deleteFolderAction") }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <AlertDialog v-model:open="projectDeleteDialogOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t("sidebar.dialogs.deleteWorkspaceTitle") }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{
              t("sidebar.dialogs.deleteWorkspaceDesc", {
                name: pendingProjectDelete?.name ?? t("sidebar.fallbacks.workspace"),
              })
            }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="cancelDeleteProject">{{
            t("common.cancel")
          }}</AlertDialogCancel>
          <AlertDialogAction class="bg-destructive text-white hover:bg-destructive/90" @click="confirmDeleteProject">
            {{ t("sidebar.dialogs.deleteWorkspaceAction") }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <Dialog v-model:open="creationDialogOpen">
      <DialogContent class="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>{{ t("sidebar.selectLocationTitle") }}</DialogTitle>
          <DialogDescription>
            {{ t("sidebar.selectLocationDesc") }}
          </DialogDescription>
        </DialogHeader>
        <div class="flex flex-col gap-0.5 py-4 max-h-[350px] overflow-y-auto pr-1">
          <template v-for="project in sidebarStore.structure.projects" :key="project.id">
            <Button variant="ghost" class="justify-start h-9 px-2 hover:bg-accent/50 font-medium group"
              :disabled="creationSubmitting" @click="selectLocationForCreation(project.id)">
              <Loader2 v-if="
                creationSubmitting && creationSubmittingLocationKey === `workspace:${project.id}`
              " class="h-4 w-4 mr-2 animate-spin" />
              <Briefcase v-else class="h-4 w-4 mr-2 text-muted-foreground group-hover:text-primary transition-colors" />
              {{ displayWorkspaceName(project.name) }}
            </Button>
            <template v-for="item in project.items" :key="item.id">
              <div v-if="item.type === 'folder' && creationType === 'session'" class="relative ml-6">
                <!-- Tree line indicator -->
                <div class="absolute -left-3 top-0 bottom-0 w-px bg-border/50"></div>
                <Button variant="ghost"
                  class="w-full justify-start h-8 pl-2 pr-2 text-sm text-muted-foreground hover:text-foreground hover:bg-accent/30 group relative"
                  :disabled="creationSubmitting" @click="selectLocationForCreation(project.id, item.id)">
                  <Loader2 v-if="
                    creationSubmitting &&
                    creationSubmittingLocationKey === `folder:${project.id}:${item.id}`
                  " class="h-3.5 w-3.5 mr-2 animate-spin" />
                  <Folder v-else class="h-3.5 w-3.5 mr-2 opacity-70 group-hover:opacity-100 transition-opacity" />
                  {{ item.name }}
                </Button>
              </div>
            </template>
          </template>
        </div>
        <DialogFooter>
          <Button variant="ghost" :disabled="creationSubmitting" @click="creationDialogOpen = false">{{
            t("common.cancel")
          }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="knowledgeUploadLocationDialogOpen">
      <DialogContent class="sm:max-w-[430px]">
        <DialogHeader>
          <DialogTitle>{{ t("sidebar.knowledge.dialogs.uploadLocationTitle") }}</DialogTitle>
          <DialogDescription>
            {{ t("sidebar.knowledge.dialogs.uploadLocationDesc") }}
          </DialogDescription>
        </DialogHeader>
        <div class="flex flex-col gap-1 py-3 max-h-[360px] overflow-y-auto pr-1">
          <Button v-for="option in knowledgeUploadLocationOptions" :key="option.key" variant="ghost"
            class="justify-start h-9 px-2 hover:bg-accent/50" :class="knowledgeUploadSelectedWorkspaceId === option.workspaceId &&
              knowledgeUploadSelectedFolderId === option.folderId
              ? 'bg-accent/40 border border-border/60'
              : ''
              " :style="{ paddingLeft: `${8 + option.depth * 16}px` }"
            @click="selectKnowledgeUploadLocation(option.workspaceId, option.folderId)">
            <Briefcase v-if="option.kind === 'workspace'" class="h-4 w-4 mr-2 text-muted-foreground" />
            <Folder v-else class="h-4 w-4 mr-2 text-muted-foreground" />
            <span class="truncate">{{ option.label }}</span>
          </Button>
          <div v-if="knowledgeUploadLocationOptions.length === 0" class="px-2 py-2 text-xs text-muted-foreground/80">
            {{ t("sidebar.searchNoResults") }}
          </div>
        </div>
        <DialogFooter class="gap-2 sm:justify-between">
          <Button variant="ghost" @click="closeKnowledgeUploadLocationDialog">{{
            t("common.cancel")
          }}</Button>
          <div class="flex items-center gap-2">
            <Button variant="outline" :disabled="!hasKnowledgeUploadLocationSelected"
              @click="createSubFolderFromKnowledgeUploadLocation">
              {{ t("sidebar.knowledge.dialogs.createSubFolder") }}
            </Button>
            <Button :disabled="!hasKnowledgeUploadLocationSelected" @click="triggerKnowledgeUploadBySelectedLocation">
              <FileText class="h-4 w-4 mr-1" />
              {{ t("sidebar.knowledge.dialogs.uploadAction") }}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="knowledgeCreateDialogOpen">
      <DialogContent class="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>
            {{
              knowledgeCreateType === "folder"
                ? t("sidebar.knowledge.dialogs.createFolderTitle")
                : t("sidebar.knowledge.dialogs.createFileTitle")
            }}
          </DialogTitle>
          <DialogDescription>
            {{ t("sidebar.knowledge.dialogs.createDesc") }}
          </DialogDescription>
        </DialogHeader>
        <div class="py-2">
          <Input v-model="knowledgeCreateName" :placeholder="t('sidebar.dialogs.renamePlaceholder')"
            :disabled="knowledgeCreateSubmitting" @keydown.enter="confirmKnowledgeCreate" />
        </div>
        <DialogFooter>
          <Button variant="ghost" :disabled="knowledgeCreateSubmitting" @click="cancelKnowledgeCreate">{{
            t("common.cancel")
          }}</Button>
          <Button @click="confirmKnowledgeCreate" :disabled="!knowledgeCreateName.trim() || knowledgeCreateSubmitting">
            <Loader2 v-if="knowledgeCreateSubmitting" class="mr-2 h-4 w-4 animate-spin" />
            {{ t("common.confirm") }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="knowledgeRenameDialogOpen">
      <DialogContent class="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>{{ t("sidebar.dialogs.renameTitle") }}</DialogTitle>
          <DialogDescription>
            {{ t("sidebar.dialogs.renameDesc") }}
          </DialogDescription>
        </DialogHeader>
        <div class="py-2">
          <Input v-model="knowledgeRenameDraft" :placeholder="t('sidebar.dialogs.renamePlaceholder')"
            @keydown.enter="confirmKnowledgeRename" />
        </div>
        <DialogFooter>
          <Button variant="ghost" @click="cancelKnowledgeRename">{{ t("common.cancel") }}</Button>
          <Button @click="confirmKnowledgeRename" :disabled="!knowledgeRenameDraft.trim()">{{
            t("common.confirm")
          }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <AlertDialog v-model:open="knowledgeDeleteDialogOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t("sidebar.knowledge.dialogs.deleteTitle") }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{
              t("sidebar.knowledge.dialogs.deleteDesc", {
                name: pendingKnowledgeDelete?.name ?? t("sidebar.fallbacks.folder"),
              })
            }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="cancelKnowledgeDelete">{{
            t("common.cancel")
          }}</AlertDialogCancel>
          <AlertDialogAction class="bg-destructive text-white hover:bg-destructive/90" @click="confirmKnowledgeDelete">
            {{ t("sidebar.dialogs.deleteAction") }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <AuthDialog v-model:open="authDialogOpen" :initial-error="initialErrorMessage" @saved="handleAuthSaved" />

    <input ref="knowledgeUploadInputRef" type="file" class="hidden" @change="onKnowledgeFileSelected" />
  </SidebarProvider>
</template>

<style scoped></style>
