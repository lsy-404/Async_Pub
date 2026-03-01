<script setup lang="ts">
import { useI18n } from "vue-i18n";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { ChevronRight, FileText, Folder, FolderPlus, Paperclip, Pencil, Trash2 } from "lucide-vue-next";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { KnowledgeNode } from "@/stores/knowledge";
import { useContextStore } from "@/stores/context";

defineOptions({ name: "KnowledgeTreeNode" });

const props = defineProps<{
  node: KnowledgeNode;
  level?: number;
}>();

const emit = defineEmits<{
  (e: "request-rename", payload: { id: number; name: string; type: "folder" | "file" }): void;
  (e: "request-delete", payload: { id: number; name: string; type: "folder" | "file" }): void;
  (e: "add-folder", payload: { parentId: number }): void;
  (e: "add-file", payload: { parentId: number }): void;
  (e: "upload", payload: { id: number }): void;
}>();

const { t } = useI18n();
const contextStore = useContextStore();
const level = props.level ?? 0;
</script>

<template>
  <Collapsible v-if="node.type === 'folder'" default-open as-child class="group/knowledge-folder">
    <li>
      <ContextMenu>
        <ContextMenuTrigger as-child>
          <CollapsibleTrigger as-child>
            <button
              class="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent/40"
              :style="{ paddingLeft: `${8 + level * 12}px` }"
            >
              <Folder class="h-4 w-4" />
              <span class="truncate">{{ node.name }}</span>
              <ChevronRight
                class="ml-auto h-4 w-4 transition-transform duration-200 group-data-[state=open]/knowledge-folder:rotate-90"
              />
            </button>
          </CollapsibleTrigger>
        </ContextMenuTrigger>
        <ContextMenuContent class="w-44">
          <ContextMenuItem @select="emit('add-folder', { parentId: node.id })">
            <FolderPlus class="h-4 w-4" />
            {{ t("sidebar.addFolder") }}
          </ContextMenuItem>
          <ContextMenuItem @select="emit('add-file', { parentId: node.id })">
            <FileText class="h-4 w-4" />
            {{ t("sidebar.knowledge.addFile") }}
          </ContextMenuItem>
          <ContextMenuItem
            @select="emit('request-rename', { id: node.id, name: node.name, type: 'folder' })"
          >
            <Pencil class="h-4 w-4" />
            {{ t("sidebar.menu.rename") }}
          </ContextMenuItem>
          <ContextMenuItem
            class="text-destructive focus:text-destructive"
            @select="emit('request-delete', { id: node.id, name: node.name, type: 'folder' })"
          >
            <Trash2 class="h-4 w-4" />
            {{ t("sidebar.menu.delete") }}
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem @select="contextStore.addItem(node.id, node.name, 'folder')">
            <Paperclip class="h-4 w-4" />
            {{ t("sidebar.menu.addToContext") }}
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>

      <CollapsibleContent>
        <ul class="space-y-0.5">
          <KnowledgeTreeNode
            v-for="child in node.children"
            :key="child.id"
            :node="child"
            :level="level + 1"
            @request-rename="emit('request-rename', $event)"
            @request-delete="emit('request-delete', $event)"
            @add-folder="emit('add-folder', $event)"
            @add-file="emit('add-file', $event)"
            @upload="emit('upload', $event)"
          />
        </ul>
      </CollapsibleContent>
    </li>
  </Collapsible>

  <li v-else>
    <ContextMenu>
      <ContextMenuTrigger as-child>
        <button
          class="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent/40"
          :style="{ paddingLeft: `${8 + level * 12}px` }"
        >
          <FileText class="h-4 w-4" />
          <span class="truncate">{{ node.name }}</span>
        </button>
      </ContextMenuTrigger>
      <ContextMenuContent class="w-44">
        <ContextMenuItem
          @select="emit('request-rename', { id: node.id, name: node.name, type: 'file' })"
        >
          <Pencil class="h-4 w-4" />
          {{ t("sidebar.menu.rename") }}
        </ContextMenuItem>
        <ContextMenuItem
          class="text-destructive focus:text-destructive"
          @select="emit('request-delete', { id: node.id, name: node.name, type: 'file' })"
        >
          <Trash2 class="h-4 w-4" />
          {{ t("sidebar.menu.delete") }}
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem @select="contextStore.addItem(node.id, node.name, 'file')">
          <Paperclip class="h-4 w-4" />
          {{ t("sidebar.menu.addToContext") }}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  </li>
</template>
