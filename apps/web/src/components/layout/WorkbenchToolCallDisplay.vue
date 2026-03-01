<script setup lang="ts">
import { computed, ref } from "vue";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  Search,
  FileText,
  AlertCircle,
} from "lucide-vue-next";

export interface WorkbenchToolCall {
  id: string;
  name: string;
  position?: number;
  status: "pending" | "executing" | "success" | "error";
  args?: Record<string, unknown>;
  result?: unknown;
}

const props = defineProps<{
  toolCall: WorkbenchToolCall;
}>();

const expanded = ref(false);

const toggle = () => {
  expanded.value = !expanded.value;
};

const title = computed(() => {
  switch (props.toolCall.name) {
    case "web_search":
      return "Web Search";
    case "search_context":
      return "Search Context";
    case "get_out_of_context_file":
      return "Get Out-of-Context File";
    case "python_interpreter":
      return "Python Interpreter";
    default:
      return props.toolCall.name;
  }
});

const icon = computed(() => {
  switch (props.toolCall.name) {
    case "web_search":
    case "search_context":
      return Search;
    default:
      return FileText;
  }
});

const resultText = computed(() => {
  const raw = props.toolCall.result;
  if (raw == null) return "";
  try {
    return JSON.stringify(raw, null, 2);
  } catch {
    return String(raw);
  }
});

const argsText = computed(() => {
  const raw = props.toolCall.args;
  if (!raw) return "";
  try {
    return JSON.stringify(raw, null, 2);
  } catch {
    return String(raw);
  }
});

const hasError = computed(() => {
  const result = props.toolCall.result;
  return (
    props.toolCall.status === "error" ||
    (typeof result === "object" && result !== null && "error" in result)
  );
});
</script>

<template>
  <div class="mt-3 rounded-md border border-border/60 bg-card/40 backdrop-blur-sm">
    <button
      type="button"
      class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-accent/30 transition-colors"
      @click="toggle"
    >
      <div class="flex items-center gap-2 min-w-0">
        <component :is="icon" class="h-3.5 w-3.5 text-muted-foreground/90" />
        <span class="truncate text-xs font-medium text-foreground/90">{{ title }}</span>
      </div>

      <div class="flex items-center gap-2">
        <span
          class="rounded px-1.5 py-0.5 text-[10px] leading-none border"
          :class="
            toolCall.status === 'pending' || toolCall.status === 'executing'
              ? 'border-primary/30 bg-primary/10 text-primary'
              : toolCall.status === 'success'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                : 'border-destructive/30 bg-destructive/10 text-destructive'
          "
        >
          {{
            toolCall.status === "pending" || toolCall.status === "executing"
              ? "Running"
              : toolCall.status === "success"
                ? "Done"
                : "Error"
          }}
        </span>

        <Loader2
          v-if="toolCall.status === 'pending' || toolCall.status === 'executing'"
          class="h-3.5 w-3.5 animate-spin text-primary"
        />
        <Check
          v-else-if="toolCall.status === 'success'"
          class="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400"
        />
        <AlertCircle v-else-if="hasError" class="h-3.5 w-3.5 text-destructive" />

        <ChevronDown v-if="expanded" class="h-3.5 w-3.5 text-muted-foreground" />
        <ChevronRight v-else class="h-3.5 w-3.5 text-muted-foreground" />
      </div>
    </button>

    <div v-if="expanded" class="border-t border-border/60 px-3 py-2 space-y-2">
      <div v-if="argsText" class="space-y-1">
        <div class="text-[11px] uppercase tracking-wide text-muted-foreground">Args</div>
        <pre
          class="max-h-48 overflow-auto rounded-md border border-border/50 bg-background/70 p-2 text-[11px] leading-relaxed"
        ><code>{{ argsText }}</code></pre>
      </div>

      <div v-if="resultText" class="space-y-1">
        <div class="text-[11px] uppercase tracking-wide text-muted-foreground">Result</div>
        <pre
          class="max-h-56 overflow-auto rounded-md border p-2 text-[11px] leading-relaxed"
          :class="
            hasError
              ? 'border-destructive/30 bg-destructive/10 text-destructive'
              : 'border-border/50 bg-background/70 text-foreground'
          "
        ><code>{{ resultText }}</code></pre>
      </div>
    </div>
  </div>
</template>
