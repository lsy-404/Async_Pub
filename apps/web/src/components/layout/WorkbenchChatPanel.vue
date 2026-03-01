<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useClipboard } from "@vueuse/core";
import MarkdownIt from "markdown-it";
import texmath from "markdown-it-texmath";
import katex from "katex";
import "katex/dist/katex.min.css";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { InputGroup, InputGroupAddon, InputGroupButton } from "@/components/ui/input-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import WorkbenchToolCallDisplay, {
  type WorkbenchToolCall,
} from "@/components/layout/WorkbenchToolCallDisplay.vue";
import {
  Copy,
  Pencil,
  RefreshCw,
  Send,
  Square,
  Trash2,
  Check,
  MessageCircle,
} from "lucide-vue-next";

interface ChatMessage {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  tool_calls?: WorkbenchToolCall[];
}

interface AssistantRenderPart {
  html: string;
  toolCalls: WorkbenchToolCall[];
}

const props = defineProps<{
  messages: ChatMessage[];
  loading: boolean;
  modelValue: string;
  placeholder: string;
  emptyText: string;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "send"): void;
  (e: "ask-hallucination", text: string): void;
  (e: "edit", payload: { id: number | string; content: string }): void;
  (e: "delete", payload: { id: number | string }): void;
  (e: "regenerate", payload: { id: number | string }): void;
  (e: "stop"): void;
}>();

const { t } = useI18n();

const scrollAreaRef = ref<InstanceType<typeof ScrollArea> | null>(null);
const editingMessageId = ref<number | string | null>(null);
const editDraft = ref("");
const markdownCache = new Map<string, { key: string; html: string }>();

const { copy } = useClipboard({ legacy: true });
const copiedMessageId = ref<number | string | null>(null);
const isComposing = ref(false);
const hallucTooltipOpen = ref(false);
const hallucTooltipRect = ref({ top: 0, left: 0, width: 0, height: 0 });
const hoveredHallucinationText = ref("");
let hallucTooltipTimer: ReturnType<typeof setTimeout> | null = null;

const SCROLL_THRESHOLD = 80;
const SCROLL_THROTTLE_MS = 50;
const isAutoScrollLocked = ref(false);
let scrollThrottleTimer: number | null = null;
let touchStartY = 0;
let viewportEl: HTMLElement | null = null;

let currentScrollAnimation: {
  startTime: number;
  startScrollTop: number;
  targetScrollTop: number;
  duration: number;
  animationFrameId: number | null;
} | null = null;

const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true,
});

md.use(texmath as never, {
  engine: katex,
  delimiters: ["dollars", "brackets"],
  katexOptions: {
    throwOnError: false,
  },
});

const escapeHtml = (value: string) =>
  value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");

type FenceToken = { info?: string; content?: string };

md.renderer.rules.fence = (tokens: FenceToken[], idx: number) => {
  const token = tokens[idx];
  if (!token) return "";

  const lang = token.info?.trim() || "text";
  const code = token.content || "";

  const copyIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;

  return `
    <div class="wb-code-block">
      <div class="wb-code-header">
        <span>${escapeHtml(lang)}</span>
        <button class="wb-copy-code" data-code="${escapeHtml(code)}" type="button">${copyIcon}</button>
      </div>
      <pre><code>${escapeHtml(code)}</code></pre>
    </div>
  `;
};

const renderedMessages = computed(() =>
  props.messages.map((msg) => {
    const key = `${msg.id}-${msg.content}`;
    const cached = markdownCache.get(String(msg.id));
    if (cached?.key === key) {
      return { id: msg.id, html: cached.html };
    }
    const html = renderMarkdown(msg.content || "");
    markdownCache.set(String(msg.id), { key, html });
    return { id: msg.id, html };
  }),
);

const renderedHtmlById = computed(() => {
  const map = new Map<number | string, string>();
  for (const row of renderedMessages.value) {
    map.set(row.id, row.html);
  }
  return map;
});

const assistantRenderPartsById = computed(() => {
  const map = new Map<number | string, AssistantRenderPart[]>();

  for (const msg of props.messages) {
    if (msg.role !== "assistant") continue;

    const allCalls = Array.isArray(msg.tool_calls) ? msg.tool_calls : [];
    const positionedCalls = allCalls
      .filter((tc) => typeof tc.position === "number" && Number.isFinite(tc.position))
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
    const unpositionedCalls = allCalls.filter(
      (tc) => !(typeof tc.position === "number" && Number.isFinite(tc.position)),
    );

    if (positionedCalls.length === 0) {
      map.set(msg.id, [
        {
          html: renderedHtmlById.value.get(msg.id) || "",
          toolCalls: unpositionedCalls,
        },
      ]);
      continue;
    }

    const groupedByPosition = new Map<number, WorkbenchToolCall[]>();
    for (const tc of positionedCalls) {
      const rawPos = Number(tc.position ?? 0);
      const clampedPos = Math.max(0, Math.min(msg.content.length, rawPos));
      const group = groupedByPosition.get(clampedPos) || [];
      group.push(tc);
      groupedByPosition.set(clampedPos, group);
    }

    const positions = Array.from(groupedByPosition.keys()).sort((a, b) => a - b);
    const parts: AssistantRenderPart[] = [];
    let cursor = 0;

    for (const pos of positions) {
      const chunk = msg.content.slice(cursor, pos);
      parts.push({
        html: renderMarkdown(chunk || ""),
        toolCalls: groupedByPosition.get(pos) || [],
      });
      cursor = pos;
    }

    const tail = msg.content.slice(cursor);
    parts.push({
      html: renderMarkdown(tail || ""),
      toolCalls: unpositionedCalls,
    });

    map.set(msg.id, parts);
  }

  return map;
});

const lastMessageMeta = computed(() => {
  const last = props.messages[props.messages.length - 1];
  return {
    id: last?.id,
    role: last?.role,
    content: last?.content || "",
  };
});

const toolCallRenderSignal = computed(() =>
  props.messages
    .map((msg) => {
      const tcs = Array.isArray(msg.tool_calls) ? msg.tool_calls : [];
      const sig = tcs
        .map((tc) => {
          const resultKey = tc.result === undefined ? "" : JSON.stringify(tc.result);
          return `${tc.id}:${tc.status}:${tc.position ?? ""}:${resultKey}`;
        })
        .join("|");
      return `${msg.id}:${sig}`;
    })
    .join("||"),
);

const getViewport = () => {
  if (viewportEl && document.body.contains(viewportEl)) {
    return viewportEl;
  }
  const el = scrollAreaRef.value?.$el?.querySelector(
    "[data-slot='scroll-area-viewport']",
  ) as HTMLElement | null;
  viewportEl = el;
  return viewportEl;
};

const easeOutQuint = (t: number) => 1 - Math.pow(1 - t, 5);

const isAtBottom = () => {
  const viewport = getViewport();
  if (!viewport) return true;
  const { scrollTop, scrollHeight, clientHeight } = viewport;
  return scrollHeight - clientHeight - scrollTop < SCROLL_THRESHOLD;
};

const stopCurrentScrollAnimation = () => {
  const animation = currentScrollAnimation;
  if (!animation) return;
  if (animation.animationFrameId !== null) {
    cancelAnimationFrame(animation.animationFrameId);
  }
  animation.animationFrameId = null;
};

const runScrollAnimation = (targetScrollTop: number) => {
  const viewport = getViewport();
  if (!viewport) return;

  const now = performance.now();
  const duration = 600;

  if (Math.abs(viewport.scrollTop - targetScrollTop) < 0.5) {
    viewport.scrollTop = targetScrollTop;
    return;
  }

  if (currentScrollAnimation && currentScrollAnimation.animationFrameId !== null) {
    cancelAnimationFrame(currentScrollAnimation.animationFrameId);
    const elapsed = now - currentScrollAnimation.startTime;
    const progress = Math.min(elapsed / currentScrollAnimation.duration, 1);
    const easedProgress = easeOutQuint(progress);
    const currentScrollTop =
      currentScrollAnimation.startScrollTop +
      (currentScrollAnimation.targetScrollTop - currentScrollAnimation.startScrollTop) *
        easedProgress;

    currentScrollAnimation = {
      startTime: now,
      startScrollTop: currentScrollTop,
      targetScrollTop,
      duration,
      animationFrameId: null,
    };
  } else {
    currentScrollAnimation = {
      startTime: now,
      startScrollTop: viewport.scrollTop,
      targetScrollTop,
      duration,
      animationFrameId: null,
    };
  }

  const animate = (time: number) => {
    const currentViewport = getViewport();
    if (!currentViewport || !currentScrollAnimation) return;

    const elapsed = time - currentScrollAnimation.startTime;
    const progress = Math.min(elapsed / currentScrollAnimation.duration, 1);
    const easedProgress = easeOutQuint(progress);
    const nextScrollTop =
      currentScrollAnimation.startScrollTop +
      (currentScrollAnimation.targetScrollTop - currentScrollAnimation.startScrollTop) *
        easedProgress;

    currentViewport.scrollTop = nextScrollTop;

    if (progress < 1) {
      currentScrollAnimation.animationFrameId = requestAnimationFrame(animate);
    } else {
      currentScrollAnimation.animationFrameId = null;
    }
  };

  currentScrollAnimation.animationFrameId = requestAnimationFrame(animate);
};

const scrollToBottom = async () => {
  await nextTick();
  const viewport = getViewport();
  if (!viewport || isAutoScrollLocked.value) {
    return;
  }
  const target = Math.max(0, viewport.scrollHeight - viewport.clientHeight + 1);
  runScrollAnimation(target);
};

const scrollToBottomThrottled = () => {
  if (scrollThrottleTimer !== null) return;
  scrollThrottleTimer = window.setTimeout(() => {
    scrollThrottleTimer = null;
    scrollToBottom();
  }, SCROLL_THROTTLE_MS);
};

const handleManualWheel = (event: WheelEvent) => {
  stopCurrentScrollAnimation();
  if (event.deltaY < 0) {
    isAutoScrollLocked.value = true;
  }
};

const handleManualTouchStart = (event: TouchEvent) => {
  touchStartY = event.touches[0]?.clientY ?? 0;
  stopCurrentScrollAnimation();
};

const handleManualTouchMove = (event: TouchEvent) => {
  const currentY = event.touches[0]?.clientY ?? 0;
  if (currentY > touchStartY + 5) {
    isAutoScrollLocked.value = true;
  }
};

const handleViewportScroll = () => {
  if (isAtBottom()) {
    isAutoScrollLocked.value = false;
  }
};

const bindViewportListeners = () => {
  const viewport = getViewport();
  if (!viewport) return;
  viewport.addEventListener("scroll", handleViewportScroll, { passive: true });
  viewport.addEventListener("wheel", handleManualWheel, { passive: true });
  viewport.addEventListener("touchstart", handleManualTouchStart, { passive: true });
  viewport.addEventListener("touchmove", handleManualTouchMove, { passive: true });
};

const unbindViewportListeners = () => {
  const viewport = viewportEl;
  if (!viewport) return;
  viewport.removeEventListener("scroll", handleViewportScroll);
  viewport.removeEventListener("wheel", handleManualWheel);
  viewport.removeEventListener("touchstart", handleManualTouchStart);
  viewport.removeEventListener("touchmove", handleManualTouchMove);
};

watch(
  () => props.messages.length,
  (newLen, oldLen) => {
    const last = props.messages[newLen - 1];
    const isNewUserMsg =
      !!last && last.role === "user" && (oldLen === undefined || newLen > oldLen);
    if (isNewUserMsg) {
      isAutoScrollLocked.value = false;
    }
    scrollToBottom();
  },
  { immediate: true },
);

watch(
  () => lastMessageMeta.value.content,
  () => {
    scrollToBottomThrottled();
  },
);

watch(toolCallRenderSignal, () => {
  scrollToBottomThrottled();
});

onMounted(() => {
  bindViewportListeners();
});

onUnmounted(() => {
  unbindViewportListeners();
  stopCurrentScrollAnimation();
  if (scrollThrottleTimer !== null) {
    clearTimeout(scrollThrottleTimer);
    scrollThrottleTimer = null;
  }
});

const startEdit = (msg: ChatMessage) => {
  if (props.loading || msg.role !== "user") return;
  editingMessageId.value = msg.id;
  editDraft.value = msg.content;
};

const cancelEdit = () => {
  editingMessageId.value = null;
  editDraft.value = "";
};

const saveEdit = () => {
  if (editingMessageId.value === null) return;
  const content = editDraft.value.trim();
  if (!content) return;
  emit("edit", { id: editingMessageId.value, content });
  cancelEdit();
};

const formatTime = (value?: string) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

const copyMessage = async (msg: ChatMessage) => {
  await copy(msg.content);
  copiedMessageId.value = msg.id;
  setTimeout(() => {
    copiedMessageId.value = null;
  }, 1200);
};

const handleMarkdownClick = (event: MouseEvent) => {
  const target = event.target as HTMLElement;
  const btn = target.closest(".wb-copy-code") as HTMLElement | null;
  if (!btn) return;
  const code = btn.getAttribute("data-code");
  if (!code) return;

  const textarea = document.createElement("textarea");
  textarea.innerHTML = code;
  copy(textarea.value);
};

const renderMarkdown = (content: string) => {
  let rendered = md.render(content);
  const highlightSpan = '<span class="hallucination-target">$1</span>';
  rendered = rendered.replace(/<maybe>([\s\S]*?)<\/maybe>/g, highlightSpan);
  rendered = rendered.replace(/&lt;maybe&gt;([\s\S]*?)&lt;\/maybe&gt;/g, highlightSpan);
  rendered = rendered.replace(/<\/?maybe>/g, "");
  rendered = rendered.replace(/&lt;\/?maybe&gt;/g, "");
  return rendered;
};

const handleInputCompositionStart = () => {
  isComposing.value = true;
};

const handleInputCompositionEnd = () => {
  isComposing.value = false;
};

const handleInputKeydown = (event: KeyboardEvent) => {
  if (event.key !== "Enter" || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) {
    return;
  }

  const nativeEvent = event as KeyboardEvent & { isComposing?: boolean; keyCode?: number };
  if (isComposing.value || nativeEvent.isComposing || nativeEvent.keyCode === 229) {
    return;
  }

  event.preventDefault();
  emit("send");
};

const handleHallucinationMouseMove = (event: MouseEvent) => {
  const target = event.target as HTMLElement | null;
  if (!target?.classList.contains("hallucination-target")) {
    return;
  }

  if (hallucTooltipTimer) {
    clearTimeout(hallucTooltipTimer);
    hallucTooltipTimer = null;
  }

  hoveredHallucinationText.value = target.innerText || target.textContent || "";
  if (!hoveredHallucinationText.value) return;

  const rects = target.getClientRects();
  if (!rects || rects.length === 0) return;

  let rect = rects[0]!;
  if (rects.length > 1) {
    let minDistance = Infinity;
    for (let i = 0; i < rects.length; i += 1) {
      const r = rects[i];
      if (!r) continue;
      const cy = r.top + r.height / 2;
      const dist = Math.abs(cy - event.clientY);
      if (dist < minDistance) {
        minDistance = dist;
        rect = r;
      }
    }
  }

  hallucTooltipRect.value = {
    top: rect.top,
    left: rect.left,
    width: rect.width,
    height: rect.height,
  };
  hallucTooltipOpen.value = true;
};

const handleHallucinationMouseOut = (event: MouseEvent) => {
  const target = event.target as HTMLElement | null;
  if (!target?.classList.contains("hallucination-target")) {
    return;
  }

  hallucTooltipTimer = setTimeout(() => {
    hallucTooltipOpen.value = false;
  }, 100);
};

const handleTooltipMouseEnter = () => {
  if (hallucTooltipTimer) {
    clearTimeout(hallucTooltipTimer);
    hallucTooltipTimer = null;
  }
};

const handleHallucinationAsk = () => {
  const text = hoveredHallucinationText.value.trim();
  if (!text) return;
  hallucTooltipOpen.value = false;
  emit("ask-hallucination", text);
};

const canSend = computed(() => !props.loading && !!props.modelValue.trim());

const canStop = computed(() => props.loading);
</script>

<template>
  <div class="relative flex h-full min-h-0 flex-col overflow-hidden bg-background">
    <TooltipProvider :delay-duration="100">
      <Tooltip :open="hallucTooltipOpen">
        <TooltipTrigger as-child>
          <div
            class="fixed pointer-events-none z-50"
            :style="{
              top: `${hallucTooltipRect.top}px`,
              left: `${hallucTooltipRect.left}px`,
              width: `${hallucTooltipRect.width}px`,
              height: `${hallucTooltipRect.height}px`,
            }"
          />
        </TooltipTrigger>
        <TooltipContent
          side="top"
          :side-offset="4"
          class="text-xs flex items-center gap-2 p-1.5 px-2.5 pointer-events-auto shadow-md"
          @mouseenter="handleTooltipMouseEnter"
          @mouseleave="hallucTooltipOpen = false"
        >
          <span class="text-background/90">{{ t("workbench.chat.aiUncertain") }}</span>
          <div class="w-[1px] h-3 bg-background/20 mx-0.5"></div>
          <button
            class="flex items-center gap-1.5 text-background/90 hover:text-background font-medium transition-colors cursor-pointer"
            @click="handleHallucinationAsk"
          >
            <MessageCircle class="size-3.5" />
            <span>{{ t("workbench.chat.askHallucination") }}</span>
          </button>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>

    <ScrollArea
      ref="scrollAreaRef"
      class="min-h-0 flex-1 px-2 py-6"
      @click="handleMarkdownClick"
      @mousemove="handleHallucinationMouseMove"
      @mouseout="handleHallucinationMouseOut"
    >
      <div class="mx-auto flex px-4 max-w-none flex-col gap-5 pb-28">
        <template v-if="messages.length === 0">
          <div class="py-16 text-center text-sm text-muted-foreground/70">
            {{ emptyText }}
          </div>
        </template>

        <template v-for="msg in messages" :key="msg.id">
          <div class="group relative w-full md:pb-7">
            <div
              class="w-full text-sm leading-relaxed"
              :class="msg.role === 'user' ? 'flex justify-end' : 'text-left text-foreground'"
            >
              <div
                v-if="msg.role === 'user'"
                class="max-w-[92%] rounded-2xl border border-border/70 bg-muted/55 px-3.5 py-2.5 text-foreground shadow-[0_1px_0_hsl(var(--border)/0.35)]"
              >
                <template v-if="editingMessageId === msg.id">
                  <div class="space-y-2">
                    <Textarea v-model="editDraft" class="min-h-24 bg-background text-foreground" />
                    <div class="flex justify-end gap-2">
                      <Button size="sm" variant="ghost" @click="cancelEdit">Cancel</Button>
                      <Button size="sm" @click="saveEdit">Save</Button>
                    </div>
                  </div>
                </template>

                <template v-else>
                  <div
                    class="wb-markdown text-sm leading-relaxed text-foreground"
                    v-html="renderedHtmlById.get(msg.id)"
                  />
                </template>
              </div>

              <div v-else class="max-w-full">
                <template
                  v-for="(part, partIndex) in assistantRenderPartsById.get(msg.id) || [
                    { html: renderedHtmlById.get(msg.id) || '', toolCalls: msg.tool_calls || [] },
                  ]"
                  :key="`${msg.id}-part-${partIndex}`"
                >
                  <div
                    v-if="part.html"
                    class="wb-markdown text-sm leading-relaxed text-foreground"
                    v-html="part.html"
                  />

                  <div v-if="part.toolCalls.length > 0" class="my-4 space-y-2">
                    <WorkbenchToolCallDisplay
                      v-for="tc in part.toolCalls"
                      :key="`${msg.id}-${partIndex}-${tc.id}`"
                      :tool-call="tc"
                    />
                  </div>
                </template>
              </div>
            </div>

            <div
              class="flex items-center gap-4 md:gap-2 text-sm text-muted-foreground transition-all duration-200 mt-3 md:mt-0 md:absolute md:bottom-0 md:z-10 md:text-muted-foreground/0 md:group-hover:text-muted-foreground/50"
              :class="[
                msg.role === 'user' ? 'justify-end md:right-0' : 'justify-start md:left-0',
                'w-full md:w-auto',
              ]"
            >
              <template v-if="msg.role === 'assistant'">
                <span>{{ formatTime(msg.created_at) }}</span>
                <Button
                  size="icon"
                  variant="ghost"
                  class="h-7 w-7 p-1.5 -m-1.5 hover:text-foreground"
                  @click="copyMessage(msg)"
                >
                  <Check v-if="copiedMessageId === msg.id" class="h-3.5 w-3.5" />
                  <Copy v-else class="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  class="h-7 w-7 p-1.5 -m-1.5 hover:text-foreground"
                  :disabled="loading"
                  @click="emit('regenerate', { id: msg.id })"
                >
                  <RefreshCw class="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  class="h-7 w-7 p-1.5 -m-1.5 hover:text-destructive"
                  :disabled="loading"
                  @click="emit('delete', { id: msg.id })"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </Button>
              </template>

              <template v-else>
                <Button
                  size="icon"
                  variant="ghost"
                  class="h-7 w-7 p-1.5 -m-1.5 hover:text-foreground"
                  :disabled="loading"
                  @click="startEdit(msg)"
                >
                  <Pencil class="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  class="h-7 w-7 p-1.5 -m-1.5 hover:text-foreground"
                  @click="copyMessage(msg)"
                >
                  <Check v-if="copiedMessageId === msg.id" class="h-3.5 w-3.5" />
                  <Copy v-else class="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  class="h-7 w-7 p-1.5 -m-1.5 hover:text-destructive"
                  :disabled="loading"
                  @click="emit('delete', { id: msg.id })"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                </Button>
                <span>{{ formatTime(msg.created_at) }}</span>
              </template>
            </div>
          </div>
        </template>
      </div>
    </ScrollArea>

    <div class="absolute inset-x-4 bottom-4 flex justify-center pointer-events-none">
      <div class="pointer-events-auto w-full max-w-3xl">
        <InputGroup
          class="w-full bg-background/80 shadow-sm shadow-black/5 backdrop-blur-md !rounded-md border-input overflow-hidden"
        >
          <textarea
            :value="modelValue"
            data-slot="input-group-control"
            :placeholder="placeholder"
            class="flex field-sizing-content min-h-0 w-full resize-none bg-transparent px-3 py-2 text-base transition-[color,box-shadow] outline-none md:text-sm"
            rows="1"
            @input="
              (event) => emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
            "
            @compositionstart="handleInputCompositionStart"
            @compositionend="handleInputCompositionEnd"
            @keydown="handleInputKeydown"
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              v-if="canStop"
              size="icon-sm"
              variant="destructive"
              class="rounded-sm"
              @click="emit('stop')"
            >
              <Square class="h-4 w-4" />
            </InputGroupButton>
            <InputGroupButton
              v-else
              size="icon-sm"
              variant="default"
              class="rounded-sm"
              :disabled="!canSend"
              @click="emit('send')"
            >
              <Send class="h-4 w-4" />
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wb-markdown :deep(p) {
  margin: 0.25rem 0;
}

.wb-markdown :deep(ul),
.wb-markdown :deep(ol) {
  padding-left: 1rem;
  margin: 0.4rem 0;
}

.wb-markdown :deep(blockquote) {
  border-left: 2px solid hsl(var(--border));
  padding-left: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.wb-markdown :deep(pre) {
  overflow-x: auto;
  border-radius: 0.5rem;
  margin: 0.5rem 0;
}

.wb-markdown :deep(code) {
  font-family:
    ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New",
    monospace;
}

.wb-markdown :deep(:not(pre) > code) {
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.wb-markdown :deep(.katex-display) {
  overflow-x: auto;
  overflow-y: hidden;
}

.wb-markdown :deep(.hallucination-target) {
  background: color-mix(in srgb, hsl(46 100% 50%) 16%, transparent);
  border-radius: 0.2rem;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, hsl(46 100% 50%) 28%, transparent);
  padding: 0 2px;
  transition:
    background-color 0.2s ease,
    box-shadow 0.2s ease;
  cursor: help;
}

.wb-markdown :deep(.hallucination-target:hover) {
  background: color-mix(in srgb, hsl(46 100% 50%) 24%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, hsl(46 100% 50%) 42%, transparent);
}

.wb-code-block {
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;
  overflow: hidden;
  background: hsl(var(--muted) / 0.35);
}

.wb-code-block pre {
  margin: 0;
  padding: 0.75rem;
}

.wb-code-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: hsl(var(--muted-foreground));
  padding: 0.35rem 0.6rem;
  border-bottom: 1px solid hsl(var(--border));
}

.wb-copy-code {
  background: transparent;
  border: none;
  cursor: pointer;
  color: inherit;
  display: inline-flex;
  align-items: center;
}
</style>
