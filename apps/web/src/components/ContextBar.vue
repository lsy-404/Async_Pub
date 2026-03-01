<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useContextStore, type ContextItemType } from "@/stores/context";
import { Briefcase, Folder, MessageSquare, FileText, X, Trash2 } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const { t } = useI18n();
const contextStore = useContextStore();

const typeIcon = (type: ContextItemType) => {
  switch (type) {
    case "workspace":
      return Briefcase;
    case "folder":
      return Folder;
    case "session":
      return MessageSquare;
    case "file":
      return FileText;
  }
};

const typeLabel = (type: ContextItemType) => {
  return t(`workbench.context.${type}`);
};

const formatTokens = (tokens: number): string => {
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}k`;
  }
  return String(tokens);
};
</script>

<template>
  <div
    v-if="contextStore.hasItems"
    class="flex flex-col gap-1.5 px-3 py-2 rounded-t-md border border-b-0 border-input bg-muted/40 backdrop-blur-sm"
  >
    <!-- Header row: title + token count + clear all -->
    <div class="flex items-center justify-between text-xs text-muted-foreground">
      <span class="font-medium">{{ t("workbench.context.title") }}</span>
      <div class="flex items-center gap-2">
        <span class="tabular-nums">
          {{ t("workbench.context.estimatedTokens") }}: {{ formatTokens(contextStore.totalEstimatedTokens) }}
        </span>
        <Button
          variant="ghost"
          size="sm"
          class="h-5 px-1.5 text-xs text-muted-foreground hover:text-destructive"
          @click="contextStore.clearAll()"
        >
          <Trash2 class="h-3 w-3 mr-0.5" />
          {{ t("workbench.context.clearAll") }}
        </Button>
      </div>
    </div>

    <!-- Context item chips -->
    <div class="flex flex-wrap gap-1">
      <TooltipProvider :delay-duration="300">
        <Tooltip v-for="item in contextStore.items" :key="`${item.type}-${item.id}`">
          <TooltipTrigger as-child>
            <div
              class="inline-flex items-center gap-1 rounded-md border bg-background/80 px-2 py-0.5 text-xs text-foreground/80 transition-colors hover:bg-accent/40 group"
            >
              <component :is="typeIcon(item.type)" class="h-3 w-3 shrink-0 text-muted-foreground" />
              <span class="max-w-[120px] truncate">{{ item.name }}</span>
              <button
                class="ml-0.5 rounded-sm p-0 opacity-50 hover:opacity-100 hover:text-destructive transition-opacity"
                @click.stop="contextStore.removeItem(item.id, item.type)"
              >
                <X class="h-3 w-3" />
              </button>
            </div>
          </TooltipTrigger>
          <TooltipContent side="top" class="text-xs">
            {{ typeLabel(item.type) }}: {{ item.name }}
            <br />
            ~{{ formatTokens(item.estimatedTokens) }} tokens
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  </div>
</template>
