<script setup lang="ts">
import { onUnmounted, ref, watch, computed } from "vue";
import { useI18n } from "vue-i18n";
import MarkdownIt from "markdown-it";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { InputGroup, InputGroupAddon, InputGroupButton } from "@/components/ui/input-group";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Combobox,
  ComboboxAnchor,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxItemIndicator,
  ComboboxList,
  ComboboxTrigger,
  ComboboxViewport,
} from "@/components/ui/combobox";
import {
  Check,
  ChevronDown,
  Mic,
  Pause,
  Play,
  AudioLines,
  MessageSquare,
  Languages,
  Columns2,
  PanelBottom,
  RefreshCw,
  Loader2,
} from "lucide-vue-next";
import { Slider } from "@/components/ui/slider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import WorkbenchChatPanel from "@/components/layout/WorkbenchChatPanel.vue";
import type { WorkbenchToolCall } from "@/components/layout/WorkbenchToolCallDisplay.vue";
import { useSidebarStore } from "@/stores/sidebar";
import { useAuthStore } from "@/stores/auth";
import { GOOGLE_TRANSLATE_LANGUAGES, type GoogleLanguageCode } from "@/lib/google-languages";

type TranscriptionLanguageCode = GoogleLanguageCode | "auto";
type TranslationMode = "side-by-side" | "separate";

interface Message {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  tool_calls?: WorkbenchToolCall[];
}

interface TranscriptWord {
  word: string;
  start: number;
  end: number;
}

interface TranscriptSentence {
  id: string;
  text: string;
  start: number;
  end: number;
}

const { t } = useI18n();
const sidebarStore = useSidebarStore();
const authStore = useAuthStore();

const TOOL_CALL_CACHE_KEY = "workbench-tool-calls-v1";
type ToolCallCache = Record<string, Record<string, WorkbenchToolCall[]>>;

const loadToolCallCache = (): ToolCallCache => {
  try {
    const raw = window.localStorage.getItem(TOOL_CALL_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as ToolCallCache;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
};

const saveToolCallCache = (cache: ToolCallCache) => {
  try {
    window.localStorage.setItem(TOOL_CALL_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // no-op: storage may be unavailable or full
  }
};

const getMessageToolCallsFromCache = (
  sessionId: number | null,
  messageId: number | string | undefined,
): WorkbenchToolCall[] => {
  if (!sessionId || messageId === undefined) return [];
  const cache = loadToolCallCache();
  return cache[String(sessionId)]?.[String(messageId)] ?? [];
};

const setMessageToolCallsToCache = (
  sessionId: number | null,
  messageId: number | string,
  toolCalls: WorkbenchToolCall[],
) => {
  if (!sessionId || toolCalls.length === 0) return;
  const cache = loadToolCallCache();
  const sid = String(sessionId);
  if (!cache[sid]) cache[sid] = {};
  cache[sid]![String(messageId)] = toolCalls;
  saveToolCallCache(cache);
};

const removeMessageToolCallsFromCache = (sessionId: number | null, messageId: number | string) => {
  if (!sessionId) return;
  const cache = loadToolCallCache();
  const sid = String(sessionId);
  if (!cache[sid]) return;
  delete cache[sid]![String(messageId)];
  saveToolCallCache(cache);
};

const WAVE_BARS = 100;
const MIN_BAR_HEIGHT = 3;
const MAX_BAR_HEIGHT = 28;

const createInitialWave = () => Array.from({ length: WAVE_BARS }, () => MIN_BAR_HEIGHT);

const messages = ref<Message[]>([]);
const transcription = ref("");
const transcriptWords = ref<TranscriptWord[]>([]);
const transcriptSentences = ref<TranscriptSentence[]>([]);
const activeSentenceIndex = ref(-1);
const isTranscribingUpload = ref(false);

const liveFinalChunks = ref<string[]>([]);
const liveInterimChunk = ref("");
const selectedAudioFile = ref<File | null>(null);

// Translation state: maps sentence id -> translated text
const sentenceTranslations = ref<Record<string, string>>({});
const translatingIds = ref<Set<string>>(new Set());

const sessionTabState = ref<Record<string, "chat" | "summary">>({});

const SUMMARY_THRESHOLD_CHARS = 800;
const SUMMARY_OVERLAP_CHARS = 200;
const summaryMarkdown = new MarkdownIt({ html: false, linkify: true, breaks: true });

const stripAiIndexTags = (raw: string) =>
  raw
    .replace(/<ai_index\b[^>]*\/>/gi, "")
    .replace(/<ai_index\b[^>]*>[\s\S]*?<\/ai_index>/gi, "")
    .trim();

const summaryHtml = computed(() => {
  const sid = sidebarStore.currentSessionId;
  if (!sid) return "";
  const summary = sidebarStore.sessionSummaries[sid]?.summary || "";
  const readableSummary = stripAiIndexTags(summary);
  return readableSummary ? summaryMarkdown.render(readableSummary) : "";
});

const summaryState = computed(() => {
  const sid = sidebarStore.currentSessionId;
  if (!sid) return { summary: "", index: [], loading: false };
  return sidebarStore.sessionSummaries[sid] || { summary: "", index: [], loading: false };
});

const activeSessionTab = computed({
  get: () => {
    const sid = sidebarStore.currentSessionId;
    if (!sid) return "chat" as const;
    return sessionTabState.value[String(sid)] ?? "chat";
  },
  set: (tab: string | number | null) => {
    const normalized = tab === "summary" ? "summary" : "chat";
    const sid = sidebarStore.currentSessionId;
    if (!sid) return;
    sessionTabState.value = {
      ...sessionTabState.value,
      [String(sid)]: normalized,
    };
  },
});

// Upload-mode playback state
const isPlaying = ref(false);
const playbackProgress = ref(0); // 0-100
const audioDuration = ref(0);
const playbackCurrentTime = ref(0);
let uploadAudioEl: HTMLAudioElement | null = null;
let uploadAudioUrl: string | null = null;

const seenWordKeys = new Set<string>();
let mediaRecorder: MediaRecorder | null = null;
let liveWebSocket: WebSocket | null = null;
let liveResponseTask: Promise<void> | null = null;

const cleanupUploadAudio = () => {
  if (uploadAudioEl) {
    uploadAudioEl.pause();
    uploadAudioEl.removeAttribute("src");
    uploadAudioEl = null;
  }
  if (uploadAudioUrl) {
    URL.revokeObjectURL(uploadAudioUrl);
    uploadAudioUrl = null;
  }
  isPlaying.value = false;
  playbackProgress.value = 0;
  playbackCurrentTime.value = 0;
  audioDuration.value = 0;
};

const formatTime = (seconds: number): string => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
};

const splitPlainTextIntoSentences = (text: string): TranscriptSentence[] => {
  const normalized = text.trim();
  if (!normalized) return [];

  const parts = normalized
    .match(/[^。！？.!?\n]+[。！？.!?]?|\n+/g)
    ?.map((part) => part.trim())
    .filter((part) => !!part && part !== "\n") || [normalized];

  return parts.map((part, idx) => ({
    id: `plain-${idx}`,
    text: part,
    start: idx,
    end: idx + 1,
  }));
};

const joinWordsWithSpacing = (words: string[]): string => {
  let output = "";
  for (const nextWord of words) {
    if (!output) {
      output = nextWord;
      continue;
    }

    const prevChar = output[output.length - 1] ?? "";
    const nextChar = nextWord[0] ?? "";
    const shouldInsertSpace = /[a-zA-Z0-9]/.test(prevChar) && /[a-zA-Z0-9]/.test(nextChar);
    output += shouldInsertSpace ? ` ${nextWord}` : nextWord;
  }
  return output;
};

const buildSentencesFromWords = (words: TranscriptWord[]): TranscriptSentence[] => {
  if (words.length === 0) return [];

  const sorted = [...words].sort((a, b) => a.start - b.start);
  const sentences: TranscriptSentence[] = [];

  let currentWords: TranscriptWord[] = [];
  let sentenceStart = sorted[0]!.start;

  const flushSentence = () => {
    if (currentWords.length === 0) return;
    const start = currentWords[0]!.start;
    const end = currentWords[currentWords.length - 1]!.end;
    const text = joinWordsWithSpacing(currentWords.map((item) => item.word).filter(Boolean));
    if (text.trim()) {
      sentences.push({
        id: `seg-${sentences.length}-${start.toFixed(3)}-${end.toFixed(3)}`,
        text: text.trim(),
        start,
        end,
      });
    }
    currentWords = [];
  };

  for (let i = 0; i < sorted.length; i += 1) {
    const item = sorted[i]!;
    const prev = sorted[i - 1];

    if (currentWords.length === 0) {
      sentenceStart = item.start;
      currentWords.push(item);
      continue;
    }

    const gap = item.start - (prev?.end ?? sentenceStart);
    const hasSentencePunctuation = /[。！？.!?]$/.test(prev?.word ?? "");
    const shouldSplitByGap = gap > 1.0;

    if (hasSentencePunctuation || shouldSplitByGap) {
      flushSentence();
      sentenceStart = item.start;
    }

    currentWords.push(item);
  }

  flushSentence();
  return sentences;
};

const setActiveSentenceByTime = (timeInSeconds: number) => {
  if (transcriptSentences.value.length === 0) {
    activeSentenceIndex.value = -1;
    return;
  }

  const directHit = transcriptSentences.value.findIndex(
    (sentence) => timeInSeconds >= sentence.start && timeInSeconds <= sentence.end,
  );
  if (directHit >= 0) {
    activeSentenceIndex.value = directHit;
    return;
  }

  const lastBefore = [...transcriptSentences.value]
    .map((sentence, index) => ({ sentence, index }))
    .filter(({ sentence }) => sentence.end <= timeInSeconds)
    .pop();

  activeSentenceIndex.value = lastBefore?.index ?? 0;
};

const rebuildSentenceView = () => {
  if (transcriptWords.value.length > 0) {
    transcriptSentences.value = buildSentencesFromWords(transcriptWords.value);
    return;
  }

  transcriptSentences.value = splitPlainTextIntoSentences(transcription.value);
  activeSentenceIndex.value = transcriptSentences.value.length > 0 ? 0 : -1;
};

const resetTranscriptState = () => {
  transcription.value = "";
  transcriptWords.value = [];
  transcriptSentences.value = [];
  activeSentenceIndex.value = -1;
  liveFinalChunks.value = [];
  liveInterimChunk.value = "";
  seenWordKeys.clear();
  sentenceTranslations.value = {};
  translatingIds.value.clear();
  cleanupUploadAudio();
};

const persistSessionMetadata = async () => {
  if (!sidebarStore.currentSessionId) return;
  await sidebarStore.updateSessionMetadata(sidebarStore.currentSessionId, {
    ai_context: sidebarStore.currentSessionMetadata?.ai_context || [],
    transcription: transcription.value,
  });
};

const canonicalizeTranscriptText = (text: string) =>
  text
    .trim()
    .replace(/\s+/g, " ")
    .replace(/\s*([,.;:!?，。！？；：])\s*/g, "$1")
    .toLowerCase();

const sliceAfterCanonicalPrefix = (prefixText: string, fullText: string): string => {
  const prefixCanonical = canonicalizeTranscriptText(prefixText);
  const fullCanonical = canonicalizeTranscriptText(fullText);

  if (!prefixCanonical) return fullText.trim();
  if (!fullCanonical.startsWith(prefixCanonical)) return fullText.trim();
  if (fullCanonical === prefixCanonical) return "";

  for (let index = 0; index <= fullText.length; index += 1) {
    if (canonicalizeTranscriptText(fullText.slice(0, index)) === prefixCanonical) {
      return fullText.slice(index).trim();
    }
  }

  return fullText.trim();
};

const computeAppendDelta = (currentText: string, incomingText: string) => {
  const incoming = incomingText.trim();
  if (!currentText) return incoming;
  if (!incoming) return "";

  // Canonical comparison first: tolerant to punctuation spacing differences
  // such as "delivered.You'll" vs "delivered. You'll".
  const currentCanonical = canonicalizeTranscriptText(currentText);
  const incomingCanonical = canonicalizeTranscriptText(incoming);
  if (incomingCanonical === currentCanonical) {
    return "";
  }
  if (incomingCanonical.startsWith(currentCanonical)) {
    return sliceAfterCanonicalPrefix(currentText, incoming);
  }

  if (currentText.endsWith(incomingText)) return "";

  if (incoming.startsWith(currentText)) {
    return incoming.slice(currentText.length).trim();
  }

  const maxOverlap = Math.min(currentText.length, incoming.length);
  for (let overlap = maxOverlap; overlap >= 1; overlap--) {
    if (currentText.slice(-overlap) === incoming.slice(0, overlap)) {
      return incoming.slice(overlap).trim();
    }
  }

  return incoming;
};

const appendChunkToDocument = (textChunk: string) => {
  const normalized = textChunk.trim();
  if (!normalized) return;
  const current = transcription.value.trim();
  const delta = computeAppendDelta(current, normalized);
  if (!delta) return;

  if (!current) {
    transcription.value = delta;
    return;
  }

  // Add a space only when both boundaries are Latin/number characters.
  const needsSpace = /[A-Za-z0-9]$/.test(current) && /^[A-Za-z0-9]/.test(delta);
  transcription.value = `${current}${needsSpace ? " " : ""}${delta}`;
};

const resetLiveStreamState = () => {
  liveFinalChunks.value = [];
  liveInterimChunk.value = "";
};

const refreshSummary = async () => {
  if (!sidebarStore.currentSessionId) return;
  await sidebarStore.fetchSessionSummary(sidebarStore.currentSessionId);
};

const maybeSendSummaryChunk = async () => {
  const sid = sidebarStore.currentSessionId;
  if (!sid) return;
  const text = transcription.value;
  const cursor = sidebarStore.summaryCursors?.[sid] ?? 0;
  const delta = text.length - cursor;
  if (delta < SUMMARY_THRESHOLD_CHARS) return;

  const start = Math.max(0, cursor - SUMMARY_OVERLAP_CHARS);
  const chunk = text.slice(start);

  sidebarStore.summaryCursors = {
    ...sidebarStore.summaryCursors,
    [sid]: Math.max(0, text.length - SUMMARY_OVERLAP_CHARS),
  } as typeof sidebarStore.summaryCursors;

  await sidebarStore.enqueueSummaryJob(sid, {
    chunk,
    chunk_offset: start,
    chunk_length: chunk.length,
    total_length: text.length,
  });
};

const normalizeToolCalls = (calls: unknown): WorkbenchToolCall[] => {
  if (!Array.isArray(calls)) return [];

  return calls.reduce<WorkbenchToolCall[]>((acc, call, index) => {
    if (!call || typeof call !== "object") return acc;
    const obj = call as Record<string, unknown>;
    const rawStatus = obj.status;
    const status: WorkbenchToolCall["status"] =
      rawStatus === "pending" ||
        rawStatus === "executing" ||
        rawStatus === "success" ||
        rawStatus === "error"
        ? rawStatus
        : "success";

    acc.push({
      id: String(obj.id ?? `tool-${index}`),
      name: String(obj.name ?? "tool"),
      position: typeof obj.position === "number" ? obj.position : undefined,
      status,
      args: (obj.args as Record<string, unknown> | undefined) ?? undefined,
      result: obj.result,
    });
    return acc;
  }, []);
};

const inputQuery = ref("");
const isAiTyping = ref(false);
const streamAbortController = ref<AbortController | null>(null);
const transcriptionSettingsPopoverOpen = ref(false);
const transcriptionLanguageCode = ref<TranscriptionLanguageCode>("auto");
const translationEnabled = ref(false);
const translationTargetLanguageCode = ref<GoogleLanguageCode>("en");
const translationMode = ref<TranslationMode>("side-by-side");
const translationActive = computed(() => translationEnabled.value);

const findLanguageMeta = (code: string) => GOOGLE_TRANSLATE_LANGUAGES.find((lang) => lang[0] === code);
const languageSearchValue = (code: string, english: string, native: string) => `${code} ${english} ${native}`;

const transcriptionLanguageLabel = computed(() => {
  if (transcriptionLanguageCode.value === "auto") return t("workbench.transcript.languageAuto");
  const entry = findLanguageMeta(transcriptionLanguageCode.value);
  return entry ? `${entry[2]} (${entry[1]})` : transcriptionLanguageCode.value;
});

const translationTargetLanguageLabel = computed(() => {
  const entry = findLanguageMeta(translationTargetLanguageCode.value);
  return entry ? `${entry[2]} (${entry[1]})` : translationTargetLanguageCode.value;
});

const translateSentence = async (sentenceId: string, text: string) => {
  if (!authStore.effectiveBackendUrl || !translationActive.value) return;
  if (!text.trim()) return;

  // Avoid duplicate calls
  if (translatingIds.value.has(sentenceId)) return;
  translatingIds.value.add(sentenceId);

  try {
    const langEntry = GOOGLE_TRANSLATE_LANGUAGES.find(
      ([code]) => code === translationTargetLanguageCode.value,
    );
    const langName = langEntry ? langEntry[1] : translationTargetLanguageCode.value;

    const response = await fetch(`${authStore.effectiveBackendUrl}/v1/translate`, {
      method: "POST",
      headers: authStore.getAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        text: text.trim(),
        to: langName,
      }),
    });

    if (!response.ok) {
      console.warn(`Translation failed for sentence ${sentenceId}: HTTP ${response.status}`);
      return;
    }

    const data = (await response.json()) as { translation?: string };
    if (data.translation) {
      sentenceTranslations.value = {
        ...sentenceTranslations.value,
        [sentenceId]: data.translation,
      };
    }
  } catch (err) {
    console.warn(`Translation error for sentence ${sentenceId}:`, err);
  } finally {
    translatingIds.value.delete(sentenceId);
  }
};

const translateAllSentences = () => {
  for (const sentence of transcriptSentences.value) {
    if (!sentenceTranslations.value[sentence.id]) {
      translateSentence(sentence.id, sentence.text);
    }
  }
};

const translateAllLiveChunks = () => {
  for (let idx = 0; idx < liveFinalChunks.value.length; idx += 1) {
    const sentenceId = `live-${idx}`;
    if (!sentenceTranslations.value[sentenceId]) {
      const chunk = liveFinalChunks.value[idx];
      if (chunk) translateSentence(sentenceId, chunk);
    }
  }
};

watch(translationActive, (active) => {
  if (!active) return;
  translateAllSentences();
  translateAllLiveChunks();
});

watch(translationTargetLanguageCode, () => {
  sentenceTranslations.value = {};
  if (!translationActive.value) return;
  translateAllSentences();
  translateAllLiveChunks();
});

watch(transcriptSentences, () => {
  if (!translationActive.value) return;
  translateAllSentences();
});
// Watch for session changes to update local content
watch(
  () => sidebarStore.currentSessionMetadata,
  (newVal) => {
    if (isAiTyping.value) {
      if (newVal?.transcription) {
        transcription.value = newVal.transcription;
      }
      return;
    }

    cleanupUploadAudio();
    if (newVal) {
      const sid = sidebarStore.currentSessionId;
      messages.value = newVal.ai_context
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m, idx) => ({
          id: m.id ?? `local-${idx}`,
          role: m.role as "user" | "assistant",
          content: m.content,
          created_at: m.created_at,
          tool_calls: normalizeToolCalls(m.tool_calls ?? getMessageToolCallsFromCache(sid, m.id)),
        }));
      transcription.value = newVal.transcription;
      transcriptWords.value = [];
      transcriptSentences.value = splitPlainTextIntoSentences(newVal.transcription || "");
      activeSentenceIndex.value = transcriptSentences.value.length > 0 ? 0 : -1;
      resetLiveStreamState();
      seenWordKeys.clear();
    } else {
      messages.value = [];
      transcription.value = "";
      transcriptWords.value = [];
      transcriptSentences.value = [];
      activeSentenceIndex.value = -1;
      resetLiveStreamState();
      seenWordKeys.clear();
    }
  },
  { immediate: true },
);

const isRecording = ref(false);
const hasUploadedWaveform = ref(false);
const fileInputRef = ref<HTMLInputElement | null>(null);
const inputMode = ref<"realtime" | "system" | "upload">("realtime");
const waveformHeights = ref<number[]>(createInitialWave());

let mediaStream: MediaStream | null = null;
let monoRecordingStream: MediaStream | null = null; // mono-downmixed stream for MediaRecorder
let audioContext: AudioContext | null = null;
let analyserNode: AnalyserNode | null = null;
let sourceNode: MediaStreamAudioSourceNode | null = null;
let animationFrameId: number | null = null;
let canvasResizeObserver: ResizeObserver | null = null;
const canvasRef = ref<HTMLCanvasElement | null>(null);

const inputModeLabelMap = {
  realtime: () => t("workbench.recording.modeRealtime"),
  system: () => t("workbench.recording.modeSystem"),
  upload: () => t("workbench.recording.modeUpload"),
} as const;

const resetWaveform = () => {
  waveformHeights.value = createInitialWave();
};

const pushWaveLevel = (normalizedLevel: number) => {
  const clamped = Math.max(0, Math.min(1, normalizedLevel));
  const nextHeight = Math.round(MIN_BAR_HEIGHT + clamped * (MAX_BAR_HEIGHT - MIN_BAR_HEIGHT));
  waveformHeights.value = [...waveformHeights.value.slice(1), nextHeight];
};

const stopWaveAnimation = () => {
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
};

const stopCurrentStream = () => {
  mediaStream?.getTracks().forEach((track) => track.stop());
  mediaStream = null;
  // monoRecordingStream tracks are derived from AudioContext destination; just null it
  monoRecordingStream = null;
};

const stopAudioGraph = async () => {
  stopWaveAnimation();
  sourceNode?.disconnect();
  analyserNode?.disconnect();
  sourceNode = null;
  analyserNode = null;

  if (audioContext && audioContext.state !== "closed") {
    await audioContext.close();
  }
  audioContext = null;
};

const attachStreamToAnalyzer = async (stream: MediaStream) => {
  await stopAudioGraph();
  stopCurrentStream();

  mediaStream = stream;
  audioContext = new AudioContext();
  analyserNode = audioContext.createAnalyser();
  analyserNode.fftSize = 1024;
  analyserNode.smoothingTimeConstant = 0.78;
  sourceNode = audioContext.createMediaStreamSource(stream);
  sourceNode.connect(analyserNode);

  // Create a mono-downmixed stream for MediaRecorder
  // This ensures we always send single-channel audio regardless of input
  const dest = audioContext.createMediaStreamDestination();
  // Force mono: merge all channels into one
  const channelMerger = audioContext.createChannelMerger(1);
  sourceNode.connect(channelMerger);
  channelMerger.connect(dest);
  monoRecordingStream = dest.stream;
};

const drawWaveform = () => {
  const canvas = canvasRef.value;
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const width = canvas.width / dpr;
  const height = canvas.height / dpr;

  ctx.clearRect(0, 0, width, height);

  const barWidth = 2;
  const gap = 2;
  const totalBarWidth = barWidth + gap;
  const maxBars = Math.floor(width / totalBarWidth);

  const primaryColor =
    getComputedStyle(document.documentElement).getPropertyValue("--primary").trim() || "#000";
  ctx.fillStyle = primaryColor;

  const heights = waveformHeights.value;

  for (let i = 0; i < maxBars; i++) {
    const j = heights.length - maxBars + i;
    const h = j >= 0 && j < heights.length ? (heights[j] ?? MIN_BAR_HEIGHT) : MIN_BAR_HEIGHT;
    const x = i * totalBarWidth;
    const y = (height - h) / 2;

    ctx.beginPath();
    ctx.roundRect(x, y, barWidth, h, 1);
    ctx.fill();
  }
};

const resizeCanvasToDisplaySize = () => {
  const canvas = canvasRef.value;
  if (!canvas) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const displayWidth = Math.max(1, Math.floor(rect.width));
  const displayHeight = Math.max(1, Math.floor(rect.height));
  const targetWidth = Math.floor(displayWidth * dpr);
  const targetHeight = Math.floor(displayHeight * dpr);

  if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
    canvas.width = targetWidth;
    canvas.height = targetHeight;
  }

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
};

const bindCanvasResizeObserver = (canvas: HTMLCanvasElement) => {
  canvasResizeObserver?.disconnect();
  canvasResizeObserver = new ResizeObserver(() => {
    resizeCanvasToDisplaySize();
    drawWaveform();
  });
  canvasResizeObserver.observe(canvas);
};

const initializeWaveCanvas = () => {
  const canvas = canvasRef.value;
  if (!canvas) return;
  resizeCanvasToDisplaySize();
  drawWaveform();
  bindCanvasResizeObserver(canvas);
};

const startWaveAnimation = () => {
  if (!analyserNode) return;
  const buffer = new Uint8Array(analyserNode.fftSize);

  const tick = () => {
    if (!isRecording.value || !analyserNode) return;

    analyserNode.getByteTimeDomainData(buffer);
    let sum = 0;
    for (let i = 0; i < buffer.length; i += 1) {
      const centered = (buffer[i]! - 128) / 128;
      sum += centered * centered;
    }

    const rms = Math.sqrt(sum / buffer.length);
    pushWaveLevel(Math.min(1, rms * 2.8));
    drawWaveform();
    animationFrameId = requestAnimationFrame(tick);
  };

  animationFrameId = requestAnimationFrame(tick);
};

// Canvas can appear after initial mount (e.g. session restored async on full reload),
// so initialize when the ref is actually bound instead of only onMounted.
watch(
  canvasRef,
  (canvas) => {
    if (!canvas) {
      canvasResizeObserver?.disconnect();
      canvasResizeObserver = null;
      return;
    }
    initializeWaveCanvas();
  },
  { immediate: true },
);

watch(
  waveformHeights,
  () => {
    if (!isRecording.value) {
      drawWaveform();
    }
  },
  { deep: true },
);

watch(
  () => sidebarStore.currentSessionId,
  (sid) => {
    if (sid) {
      sidebarStore.fetchSessionSummary(sid);
      sidebarStore.summaryCursors = {
        ...sidebarStore.summaryCursors,
        [sid]: transcription.value.length,
      } as typeof sidebarStore.summaryCursors;
    }
  },
  { immediate: true },
);

watch(transcription, () => {
  maybeSendSummaryChunk();
});

watch(activeSessionTab, (tab) => {
  if (tab === "summary") {
    refreshSummary();
  }
});

const requestMicStream = async () => {
  if (!navigator.mediaDevices?.getUserMedia) return;
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  await attachStreamToAnalyzer(stream);
};

const requestSystemAudioStream = async () => {
  if (!navigator.mediaDevices?.getDisplayMedia) return;
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
  await attachStreamToAnalyzer(stream);
};

const extractWaveFromAudioFile = async (file: File) => {
  const decodeContext = new AudioContext();
  try {
    const raw = await file.arrayBuffer();
    const audioBuffer = await decodeContext.decodeAudioData(raw.slice(0));
    const channelData = audioBuffer.getChannelData(0);
    const bucketSize = Math.max(1, Math.floor(channelData.length / WAVE_BARS));
    const nextHeights: number[] = [];

    for (let i = 0; i < WAVE_BARS; i += 1) {
      const start = i * bucketSize;
      const end = Math.min(channelData.length, start + bucketSize);
      let peak = 0;

      for (let p = start; p < end; p += 1) {
        peak = Math.max(peak, Math.abs(channelData[p] ?? 0));
      }

      const height = Math.round(MIN_BAR_HEIGHT + peak * (MAX_BAR_HEIGHT - MIN_BAR_HEIGHT));
      nextHeights.push(Math.max(MIN_BAR_HEIGHT, height));
    }

    waveformHeights.value = nextHeights;
    hasUploadedWaveform.value = true;
  } finally {
    await decodeContext.close();
  }
};

const chooseInputMode = async (mode: "realtime" | "system" | "upload") => {
  try {
    if (isRecording.value) {
      await stopLiveTranscription();
    }
    cleanupUploadAudio();

    if (mode === "realtime") {
      await requestMicStream();
      inputMode.value = mode;
      hasUploadedWaveform.value = false;
      selectedAudioFile.value = null;
    } else if (mode === "system") {
      await requestSystemAudioStream();
      inputMode.value = mode;
      hasUploadedWaveform.value = false;
      selectedAudioFile.value = null;
    } else {
      inputMode.value = mode;
      fileInputRef.value?.click();
    }
  } catch (error) {
    console.warn("Failed to switch input mode", error);
  }
};

const onAudioFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;

  await stopAudioGraph();
  stopCurrentStream();
  await extractWaveFromAudioFile(file);
  selectedAudioFile.value = file;
  inputMode.value = "upload";
  input.value = "";
};

const handleWsMessage = async (payload: {
  text?: string;
  is_final?: boolean;
  words?: Array<{ word?: string; start?: number; end?: number }>;
  error?: string;
  metadata?: { result_end_time?: number };
  end_time?: number;
}) => {
  if (payload.error) {
    console.error("Transcription error from server:", payload.error);
    return;
  }

  const textChunk = (payload.text || "").trim();
  const isFinal = !!payload.is_final;

  if (isFinal && textChunk) {
    liveFinalChunks.value.push(textChunk);
    liveInterimChunk.value = "";
    appendChunkToDocument(textChunk);

    // Auto-translate the final chunk if translation is active
    if (translationActive.value) {
      const chunkIdx = liveFinalChunks.value.length - 1;
      const sentenceId = `live-${chunkIdx}`;
      translateSentence(sentenceId, textChunk);
    }
  } else if (!isFinal) {
    const interimDelta = computeAppendDelta(transcription.value.trim(), textChunk);
    liveInterimChunk.value = interimDelta;
  }

  if (isFinal) {
    await persistSessionMetadata();
  }
};

const startLiveTranscription = async () => {
  if (!authStore.effectiveBackendUrl) {
    console.warn("No backend URL configured for streaming transcription");
    return;
  }

  if (!mediaStream) {
    if (inputMode.value === "realtime") {
      await requestMicStream();
    } else {
      await requestSystemAudioStream();
    }
  }

  if (!mediaStream) {
    console.warn("No media stream available for live transcription");
    return;
  }

  resetLiveStreamState();

  if (!authStore.token) {
    console.warn("Missing auth token for live transcription WebSocket");
    return;
  }

  // Build WebSocket URL from the backend URL (http→ws, https→wss)
  // MediaRecorder produces WebM container with Opus codec, so encoding=webm
  const wsParams = new URLSearchParams({
    token: authStore.token,
    encoding: "webm",
    sample_rate: "48000",
  });
  if (transcriptionLanguageCode.value !== "auto") {
    wsParams.set("language", transcriptionLanguageCode.value);
  }
  if (translationEnabled.value) {
    wsParams.set("enable_translation", "true");
    wsParams.set("translation_language", translationTargetLanguageCode.value);
  }
  if (sidebarStore.currentSessionId) {
    wsParams.set("session_id", String(sidebarStore.currentSessionId));
  }
  const wsUrl =
    authStore.effectiveBackendUrl.replace(/^http/, "ws") +
    `/v1/audio/transcriptions/ws?${wsParams.toString()}`;

  const ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";
  liveWebSocket = ws;

  // Wait for the socket to open before starting the recorder
  await new Promise<void>((resolve, reject) => {
    ws.onopen = () => resolve();
    ws.onerror = () => reject(new Error("WebSocket connection failed"));
    // If close event arrives before open, also reject
    ws.onclose = () => reject(new Error("WebSocket closed before open"));
  });

  // Clear the one-shot handlers set above and wire the real ones
  ws.onerror = null;
  ws.onclose = null;

  liveResponseTask = new Promise<void>((resolve) => {
    ws.onmessage = async (event: MessageEvent) => {
      const raw = typeof event.data === "string" ? event.data : "";
      if (raw === "[DONE]") return; // completion marker handled via onclose
      try {
        const payload = JSON.parse(raw);
        await handleWsMessage(payload);
      } catch {
        // ignore unparseable frames
      }
    };

    ws.onclose = async () => {
      isRecording.value = false;
      stopWaveAnimation();
      liveInterimChunk.value = "";
      liveWebSocket = null;
      mediaRecorder = null;
      await stopAudioGraph();
      stopCurrentStream();
      resolve();
    };

    ws.onerror = () => {
      console.error("WebSocket error during live transcription");
    };
  });

  const recorderMimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : "audio/webm";

  // Use the mono-downmixed stream for recording (falls back to raw mediaStream)
  const streamForRecorder = monoRecordingStream || mediaStream;
  mediaRecorder = new MediaRecorder(streamForRecorder, { mimeType: recorderMimeType });
  mediaRecorder.ondataavailable = async (event: BlobEvent) => {
    if (!event.data || event.data.size === 0) return;
    if (!liveWebSocket || liveWebSocket.readyState !== WebSocket.OPEN) return;

    const chunk = await event.data.arrayBuffer();
    liveWebSocket.send(chunk);
  };
  mediaRecorder.onstop = () => {
    // Close the WebSocket when recording stops so the server knows we're done
    if (liveWebSocket && liveWebSocket.readyState === WebSocket.OPEN) {
      liveWebSocket.close();
    }
  };

  mediaRecorder.start(100);
  isRecording.value = true;
  startWaveAnimation();
};

const stopLiveTranscription = async () => {
  isRecording.value = false;
  stopWaveAnimation();

  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  } else if (liveWebSocket && liveWebSocket.readyState === WebSocket.OPEN) {
    liveWebSocket.close();
  }

  if (liveResponseTask) {
    await liveResponseTask;
    liveResponseTask = null;
  }

  await persistSessionMetadata();
};

const runUploadTranscription = async () => {
  if (!selectedAudioFile.value) {
    fileInputRef.value?.click();
    return;
  }

  if (!authStore.effectiveBackendUrl) {
    console.warn("No backend URL configured for upload transcription");
    return;
  }

  isTranscribingUpload.value = true;
  resetTranscriptState();
  cleanupUploadAudio();

  try {
    const formData = new FormData();
    formData.append("file", selectedAudioFile.value);
    formData.append("model", "default");
    if (sidebarStore.currentSessionId) {
      formData.append("session_id", String(sidebarStore.currentSessionId));
    }
    if (transcriptionLanguageCode.value !== "auto") {
      formData.append("language", transcriptionLanguageCode.value);
    }
    if (translationEnabled.value) {
      formData.append("enable_translation", "true");
      formData.append("translation_language", translationTargetLanguageCode.value);
    }
    formData.append("response_format", "verbose_json");
    formData.append("timestamp_granularities", "word");
    formData.append("timestamp_granularities", "segment");

    const response = await fetch(`${authStore.effectiveBackendUrl}/v1/audio/transcriptions`, {
      method: "POST",
      headers: authStore.getAuthHeaders(),
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload transcription failed: ${response.status}`);
    }

    const payload = (await response.json()) as {
      text?: string;
      words?: Array<{ word?: string; start?: number; end?: number }>;
    };

    transcription.value = (payload.text || "").trim();

    const words = (payload.words || [])
      .filter(
        (word): word is { word: string; start: number; end: number } =>
          typeof word.word === "string" &&
          typeof word.start === "number" &&
          typeof word.end === "number",
      )
      .map((word) => ({ word: word.word, start: word.start, end: word.end }));

    transcriptWords.value = words;
    seenWordKeys.clear();
    for (const word of words) {
      seenWordKeys.add(`${word.word}|${word.start.toFixed(3)}|${word.end.toFixed(3)}`);
    }

    rebuildSentenceView();

    // Auto-translate all sentences after upload transcription
    if (translationActive.value) {
      translateAllSentences();
    }

    // Create Audio element for playback
    uploadAudioUrl = URL.createObjectURL(selectedAudioFile.value);
    uploadAudioEl = new Audio(uploadAudioUrl);
    uploadAudioEl.addEventListener("loadedmetadata", () => {
      const duration = uploadAudioEl?.duration ?? 0;
      audioDuration.value = Number.isFinite(duration) && duration > 0 ? duration : 0;
    });
    uploadAudioEl.addEventListener("timeupdate", () => {
      if (!uploadAudioEl) return;
      const duration =
        Number.isFinite(uploadAudioEl.duration) && uploadAudioEl.duration > 0
          ? uploadAudioEl.duration
          : audioDuration.value;
      if (duration > 0 && duration !== audioDuration.value) {
        audioDuration.value = duration;
      }
      playbackCurrentTime.value = uploadAudioEl.currentTime;
      if (duration > 0) {
        playbackProgress.value = Math.max(
          0,
          Math.min(100, (uploadAudioEl.currentTime / duration) * 100),
        );
      }
      setActiveSentenceByTime(uploadAudioEl.currentTime);
    });
    uploadAudioEl.addEventListener("ended", () => {
      isPlaying.value = false;
      playbackProgress.value = 100;
      activeSentenceIndex.value = transcriptSentences.value.length - 1;
    });

    await persistSessionMetadata();
  } catch (error) {
    console.error("Upload transcription failed", error);
  } finally {
    isTranscribingUpload.value = false;
  }
};

const toggleUploadPlayback = () => {
  if (!uploadAudioEl) return;
  if (isPlaying.value) {
    uploadAudioEl.pause();
    isPlaying.value = false;
  } else {
    uploadAudioEl.play();
    isPlaying.value = true;
  }
};

const onSliderSeek = (value: number[] | undefined) => {
  if (!uploadAudioEl || !value) return;
  const duration =
    Number.isFinite(uploadAudioEl.duration) && uploadAudioEl.duration > 0
      ? uploadAudioEl.duration
      : audioDuration.value;
  if (duration <= 0) return;

  const pct = Math.max(0, Math.min(100, value[0] ?? 0));
  const newTime = (pct / 100) * duration;
  uploadAudioEl.currentTime = newTime;
  playbackProgress.value = pct;
  playbackCurrentTime.value = newTime;
  setActiveSentenceByTime(newTime);
};

const toggleRecording = async () => {
  if (inputMode.value === "upload") {
    // In upload mode: if transcription already done, toggle play/pause
    if (uploadAudioEl && transcription.value) {
      toggleUploadPlayback();
      return;
    }
    // Otherwise trigger transcription or file pick
    if (!hasUploadedWaveform.value) {
      fileInputRef.value?.click();
      return;
    }
    await runUploadTranscription();
    return;
  }

  // Live modes (realtime / system)
  if (isRecording.value) {
    await stopLiveTranscription();
    return;
  }

  await startLiveTranscription();
};

const sendMessage = async () => {
  const text = inputQuery.value.trim();
  const sessionId = sidebarStore.currentSessionId;
  if (!text || isAiTyping.value || !sessionId) return;

  const userTempId = `temp-user-${Date.now()}`;
  const assistantTempId = `temp-assistant-${Date.now()}`;

  messages.value.push({ id: userTempId, role: "user", content: text });
  messages.value.push({ id: assistantTempId, role: "assistant", content: "", tool_calls: [] });
  removeMessageToolCallsFromCache(sessionId, assistantTempId);
  inputQuery.value = "";

  isAiTyping.value = true;
  streamAbortController.value = new AbortController();
  const toolCalls = new Map<string, WorkbenchToolCall>();

  const syncToolCallsToAssistant = () => {
    const target = messages.value.find((msg) => msg.id === assistantTempId);
    if (!target) return;
    const calls = Array.from(toolCalls.values());
    target.tool_calls = calls;
    setMessageToolCallsToCache(sidebarStore.currentSessionId, target.id, calls);
  };

  try {
    await sidebarStore.streamSessionChatCompletion(
      sessionId,
      {
        content: text,
        transcription: transcription.value,
        stream: true,
        enable_tools: true,
      },
      {
        onChunk: (chunk) => {
          const delta = chunk.choices?.[0]?.delta;
          const toolInfo = delta?.tool_call_info;
          if (toolInfo?.id) {
            const id = String(toolInfo.id);
            const existing = toolCalls.get(id) ?? {
              id,
              name: toolInfo.name || "tool",
              status: "pending",
              position: typeof toolInfo.position === "number" ? toolInfo.position : undefined,
              args: toolInfo.args,
            };

            if (toolInfo.name) {
              existing.name = toolInfo.name;
            }
            if (typeof toolInfo.position === "number") {
              existing.position = toolInfo.position;
            }
            if (toolInfo.args) {
              existing.args = toolInfo.args;
            }
            if (toolInfo.result !== undefined) {
              existing.result = toolInfo.result;
              const hasError =
                typeof toolInfo.result === "object" &&
                toolInfo.result !== null &&
                "error" in (toolInfo.result as Record<string, unknown>);
              existing.status = hasError ? "error" : "success";
            } else if (toolInfo.status === "pending" || toolInfo.status === "executing") {
              existing.status = toolInfo.status;
            } else {
              existing.status = "executing";
            }

            toolCalls.set(id, existing);
            syncToolCallsToAssistant();
          }

          if (!delta?.content) return;
          const target = messages.value.find((msg) => msg.id === assistantTempId);
          if (target) {
            target.content += delta.content;
          }
        },
        onError: (error) => {
          const target = messages.value.find((msg) => msg.id === assistantTempId);
          if (target && !target.content.trim()) {
            target.content = `${t("workbench.chat.errorPrefix")} ${error}`;
          }
        },
      },
      streamAbortController.value.signal,
    );
  } catch (err) {
    if (!(err instanceof DOMException && err.name === "AbortError")) {
      console.error("session chat stream failed", err);
    }
  } finally {
    isAiTyping.value = false;
    streamAbortController.value = null;
    await sidebarStore.fetchSessionMetadata(sessionId);

    const finalToolCalls = Array.from(toolCalls.values());
    if (finalToolCalls.length > 0) {
      const latestAssistant = [...messages.value].reverse().find((m) => m.role === "assistant");
      if (latestAssistant) {
        latestAssistant.tool_calls = finalToolCalls;
        setMessageToolCallsToCache(
          sidebarStore.currentSessionId,
          latestAssistant.id,
          finalToolCalls,
        );
      }
    }
  }
};

const stopGeneration = () => {
  if (!streamAbortController.value) return;
  streamAbortController.value.abort();
};

const removeMessagesFrom = async (messageId: number | string) => {
  const sessionId = sidebarStore.currentSessionId;
  const context = sidebarStore.currentSessionMetadata?.ai_context ?? [];
  if (!sessionId || context.length === 0) return;

  const startIndex = context.findIndex((m) => m.id === messageId);
  if (startIndex === -1) return;

  for (let i = context.length - 1; i >= startIndex; i -= 1) {
    const id = context[i]?.id;
    if (typeof id === "number") {
      removeMessageToolCallsFromCache(sessionId, id);
      await sidebarStore.deleteSessionMessage(id);
    }
  }

  await sidebarStore.fetchSessionMetadata(sessionId);
};

const handleDeleteMessage = async ({ id }: { id: number | string }) => {
  if (isAiTyping.value) return;
  await removeMessagesFrom(id);
};

const handleEditMessage = async ({ id, content }: { id: number | string; content: string }) => {
  if (isAiTyping.value) return;
  await removeMessagesFrom(id);
  inputQuery.value = content;
  await sendMessage();
};

const handleRegenerateMessage = async ({ id }: { id: number | string }) => {
  if (isAiTyping.value) return;

  const targetIndex = messages.value.findIndex((m) => m.id === id && m.role === "assistant");
  if (targetIndex <= 0) return;

  let previousUser: Message | null = null;
  for (let i = targetIndex - 1; i >= 0; i -= 1) {
    const candidate = messages.value[i];
    if (candidate?.role === "user") {
      previousUser = candidate;
      break;
    }
  }
  if (!previousUser) return;

  await removeMessagesFrom(id);
  inputQuery.value = previousUser.content;
  await sendMessage();
};

const handleHallucinationAsk = async (text: string) => {
  if (isAiTyping.value || !text.trim()) return;
  inputQuery.value = t("workbench.chat.askHallucinationPrompt", { text: text.trim() });
  await sendMessage();
};

onUnmounted(async () => {
  canvasResizeObserver?.disconnect();
  canvasResizeObserver = null;
  cleanupUploadAudio();
  if (isRecording.value) {
    await stopLiveTranscription();
  }
  if (streamAbortController.value) {
    streamAbortController.value.abort();
    streamAbortController.value = null;
  }
  stopWaveAnimation();
  await stopAudioGraph();
  stopCurrentStream();
  resetWaveform();
});
</script>

<template>
  <div class="h-full w-full">
    <div v-if="!sidebarStore.currentSessionId"
      class="h-full flex flex-col items-center justify-center p-8 text-center animate-in fade-in duration-500">
      <div class="w-16 h-16 rounded-2xl bg-muted/30 flex items-center justify-center mb-6">
        <MessageSquare class="h-8 w-8 text-muted-foreground/40" />
      </div>
      <h2 class="text-xl font-semibold mb-2">{{ t("workbench.empty.title") }}</h2>
      <p class="text-muted-foreground max-w-[280px] leading-relaxed">
        {{ t("workbench.empty.description") }}
      </p>
    </div>

    <ResizablePanelGroup v-else direction="horizontal" class="h-full w-full">
      <!-- 主工作区域 -->
      <ResizablePanel :default-size="75" :min-size="30" class="min-h-0 overflow-hidden">
        <div class="h-full min-h-0 overflow-hidden flex flex-col">
          <div class="shrink-0 border-b bg-muted/30 px-4 flex items-center py-2">
            <Tabs v-model="activeSessionTab" class="w-full">
              <TabsList class="h-8">
                <TabsTrigger value="chat" class="h-7 px-2.5 text-xs font-medium">
                  {{ t("workbench.chat.title") || "Chat" }}
                </TabsTrigger>
                <TabsTrigger value="summary" class="h-7 px-2.5 text-xs font-medium">
                  {{ t("workbench.summary.title") || "Summary" }}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div class="flex-1 min-h-0 overflow-hidden">
            <div v-if="activeSessionTab === 'chat'" class="h-full">
              <WorkbenchChatPanel v-model="inputQuery" :messages="messages" :loading="isAiTyping"
                :placeholder="t('workbench.chat.inputPlaceholder')" :empty-text="t('workbench.chat.noMessages')"
                @send="sendMessage" @ask-hallucination="handleHallucinationAsk" @stop="stopGeneration"
                @edit="handleEditMessage" @delete="handleDeleteMessage" @regenerate="handleRegenerateMessage" />
            </div>

            <div v-else class="h-full min-h-0 flex flex-col text-sm text-muted-foreground">
              <div class="shrink-0 border-b px-6 py-4 bg-background/70">
                <div class="flex items-center justify-between gap-3">
                  <div class="flex flex-col gap-1">
                    <div class="font-semibold text-foreground">
                      {{ t("workbench.summary.header") }}
                    </div>
                    <div class="text-xs opacity-70">{{ t("workbench.summary.autoHint") }}</div>
                    <div v-if="summaryState.updated_at" class="text-[11px] text-muted-foreground">
                      {{ t("workbench.summary.updatedAt", { time: summaryState.updated_at }) }}
                    </div>
                  </div>
                  <div class="flex items-center gap-2">
                    <span v-if="summaryState.loading" class="flex items-center gap-1.5 text-xs text-primary">
                      <Loader2 class="h-4 w-4 animate-spin" />
                      <span>{{ t("workbench.summary.generating") }}</span>
                    </span>
                    <Button size="sm" variant="ghost" :disabled="summaryState.loading" class="gap-1"
                      @click="refreshSummary">
                      <RefreshCw class="h-4 w-4" />
                      <span>{{ t("workbench.summary.refresh") }}</span>
                    </Button>
                  </div>
                </div>
              </div>

              <div class="flex-1 min-h-0 overflow-y-auto px-6 py-5">
                <div v-if="summaryState.loading" class="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 class="h-4 w-4 animate-spin" />
                  <span>{{ t("workbench.summary.generating") }}</span>
                </div>
                <div v-else-if="summaryState.summary" class="prose prose-sm max-w-none text-foreground"
                  v-html="summaryHtml"></div>
                <div v-else class="text-sm opacity-80">
                  {{ t("workbench.summary.empty") }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </ResizablePanel>

      <!-- 拖拽调节手柄 -->
      <ResizableHandle with-handle />

      <!-- 右侧工作面板 -->
      <ResizablePanel :default-size="100" :min-size="20" :max-size="45">
        <div class="flex h-full flex-col bg-muted/20">
          <div class="flex flex-col h-full bg-background border-l">
            <Card class="border-0 rounded-none h-full flex flex-col gap-0 shadow-none py-0">
              <CardHeader
                class="px-4 py-2.5 border-b [.border-b]:pb-2.5 shrink-0 bg-muted/30 flex items-center space-y-0 gap-0">
                <div class="flex w-full items-center gap-2">
                  <CardTitle class="text-sm font-semibold flex items-center gap-2 leading-none">
                    <AudioLines class="h-4 w-4 text-primary shrink-0" />
                    {{ t("workbench.transcript.title") }}
                  </CardTitle>
                  <div class="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                    <Popover :open="transcriptionSettingsPopoverOpen"
                      @update:open="(v: boolean) => { transcriptionSettingsPopoverOpen = v; }">
                      <PopoverTrigger as-child>
                        <Button variant="outline" size="sm" class="h-7 px-2 gap-1.5 text-xs">
                          <Languages class="h-3.5 w-3.5" />
                          <span>{{ t("workbench.transcript.settings") }}</span>
                          <ChevronDown class="h-3 w-3 opacity-60" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent side="bottom" align="end" class="w-80 p-3" :collision-padding="8">
                        <div class="space-y-3">
                          <div class="space-y-1.5">
                            <div class="text-xs font-medium text-foreground">{{ t("workbench.transcript.transcriptionLanguage") }}</div>
                            <Combobox v-model="transcriptionLanguageCode">
                              <ComboboxAnchor class="w-full">
                                <ComboboxTrigger as-child>
                                  <Button variant="outline" size="sm"
                                    class="w-full justify-between h-8 px-2 text-xs font-normal">
                                    <span class="truncate text-left">{{ transcriptionLanguageLabel }}</span>
                                    <ChevronDown class="h-3.5 w-3.5 opacity-60" />
                                  </Button>
                                </ComboboxTrigger>
                              </ComboboxAnchor>
                              <ComboboxList class="w-[--reka-combobox-trigger-width] p-0">
                                <ComboboxInput :placeholder="t('workbench.transcript.searchLanguage')" class="h-8 text-xs" />
                                <ComboboxEmpty class="text-xs">{{ t("sidebar.searchNoResults") }}</ComboboxEmpty>
                                <ComboboxViewport class="max-h-[260px]">
                                  <ComboboxItem value="auto" :text-value="languageSearchValue('auto', 'auto', t('workbench.transcript.languageAuto'))"
                                    class="text-xs">
                                    <span>{{ t("workbench.transcript.languageAuto") }}</span>
                                    <ComboboxItemIndicator>
                                      <Check class="h-4 w-4" />
                                    </ComboboxItemIndicator>
                                  </ComboboxItem>
                                  <ComboboxItem v-for="[code, english, native] in GOOGLE_TRANSLATE_LANGUAGES"
                                    :key="`transcript-${code}`" :value="code"
                                    :text-value="languageSearchValue(code, english, native)" class="text-xs">
                                    <span class="truncate">{{ native }}</span>
                                    <span class="ml-auto text-muted-foreground/70 truncate">{{ english }}</span>
                                    <ComboboxItemIndicator>
                                      <Check class="h-4 w-4" />
                                    </ComboboxItemIndicator>
                                  </ComboboxItem>
                                </ComboboxViewport>
                              </ComboboxList>
                            </Combobox>
                          </div>

                          <!-- Translation toggle hidden -->
                          <template v-if="false">
                          <div class="flex items-center justify-between rounded-md border px-2.5 py-2">
                            <span class="text-xs font-medium text-foreground">{{ t("workbench.transcript.translate") }}</span>
                            <Switch v-model="translationEnabled" />
                          </div>

                          <div v-if="translationEnabled" class="space-y-1.5">
                            <div class="text-xs font-medium text-foreground">{{ t("workbench.transcript.translateTo") }}</div>
                            <Combobox v-model="translationTargetLanguageCode">
                              <ComboboxAnchor class="w-full">
                                <ComboboxTrigger as-child>
                                  <Button variant="outline" size="sm"
                                    class="w-full justify-between h-8 px-2 text-xs font-normal">
                                    <span class="truncate text-left">{{ translationTargetLanguageLabel }}</span>
                                    <ChevronDown class="h-3.5 w-3.5 opacity-60" />
                                  </Button>
                                </ComboboxTrigger>
                              </ComboboxAnchor>
                              <ComboboxList class="w-[--reka-combobox-trigger-width] p-0">
                                <ComboboxInput :placeholder="t('workbench.transcript.searchLanguage')" class="h-8 text-xs" />
                                <ComboboxEmpty class="text-xs">{{ t("sidebar.searchNoResults") }}</ComboboxEmpty>
                                <ComboboxViewport class="max-h-[260px]">
                                  <ComboboxItem v-for="[code, english, native] in GOOGLE_TRANSLATE_LANGUAGES"
                                    :key="`translation-${code}`" :value="code"
                                    :text-value="languageSearchValue(code, english, native)" class="text-xs">
                                    <span class="truncate">{{ native }}</span>
                                    <span class="ml-auto text-muted-foreground/70 truncate">{{ english }}</span>
                                    <ComboboxItemIndicator>
                                      <Check class="h-4 w-4" />
                                    </ComboboxItemIndicator>
                                  </ComboboxItem>
                                </ComboboxViewport>
                              </ComboboxList>
                            </Combobox>

                            <div class="pt-1">
                              <div class="text-xs font-medium text-foreground mb-1.5">{{ t("workbench.transcript.viewMode") }}</div>
                              <ToggleGroup
                                type="single"
                                :model-value="translationMode"
                                @update:model-value="(value) => { if (value === 'side-by-side' || value === 'separate') translationMode = value; }"
                                variant="outline"
                                size="sm"
                                class="h-8 w-full"
                              >
                                <ToggleGroupItem
                                  value="side-by-side"
                                  class="h-8 flex-1 gap-1.5 px-2 text-xs data-[state=on]:!bg-primary data-[state=on]:!text-primary-foreground"
                                  :aria-label="t('workbench.transcript.translateSideBySide')"
                                >
                                  <Columns2 class="h-3.5 w-3.5" />
                                  <span>{{ t("workbench.transcript.translateSideBySide") }}</span>
                                </ToggleGroupItem>
                                <ToggleGroupItem
                                  value="separate"
                                  class="h-8 flex-1 gap-1.5 px-2 text-xs data-[state=on]:!bg-primary data-[state=on]:!text-primary-foreground"
                                  :aria-label="t('workbench.transcript.translateSeparate')"
                                >
                                  <PanelBottom class="h-3.5 w-3.5" />
                                  <span>{{ t("workbench.transcript.translateSeparate") }}</span>
                                </ToggleGroupItem>
                              </ToggleGroup>
                            </div>
                          </div>
                          </template>
                        </div>
                      </PopoverContent>
                    </Popover>
                  </div>
                </div>
              </CardHeader>

              <ResizablePanelGroup direction="vertical" class="flex-1 min-h-0">
                <ResizablePanel :default-size="100" :min-size="30">
                  <CardContent class="h-full min-h-0 bg-background/50 relative text-sm p-0 overflow-hidden">
                    <div class="h-full overflow-y-auto px-4 py-4 pb-28">
                      <template v-if="!transcription && !liveInterimChunk">
                        <div class="h-full flex flex-col items-center justify-center text-center opacity-40 px-6">
                          <AudioLines class="h-10 w-10 mb-4" />
                          <p>{{ t("workbench.transcript.empty") }}</p>
                        </div>
                      </template>

                      <!-- Upload mode: sentence-level highlight during playback -->
                      <div v-else-if="inputMode === 'upload' && transcriptSentences.length > 0"
                        class="leading-relaxed text-muted-foreground/90 whitespace-pre-wrap min-h-full">
                        <div class="space-y-1">
                          <div v-for="(sentence, index) in transcriptSentences" :key="sentence.id">
                            <span
                              class="rounded-sm px-1 py-0.5 transition-colors duration-150 leading-8" :class="index === activeSentenceIndex ? 'bg-primary/15 text-foreground' : ''
                                ">
                              {{ sentence.text }}
                            </span>
                            <div v-if="translationMode === 'side-by-side' && sentenceTranslations[sentence.id]"
                              class="pl-1 text-xs text-primary/70 italic leading-6">
                              {{ sentenceTranslations[sentence.id] }}
                            </div>
                            <div v-else-if="translationMode === 'side-by-side' && translatingIds.has(sentence.id)"
                              class="pl-1 text-xs text-muted-foreground/50 italic leading-6">
                              {{ t("workbench.transcript.translating") }}
                            </div>
                          </div>
                        </div>
                      </div>

                      <!-- Live mode: streaming text display with per-chunk translation -->
                      <div v-else class="leading-relaxed text-muted-foreground/90 whitespace-pre-wrap min-h-full">
                        <template v-if="transcription || liveInterimChunk">
                          <template v-if="translationMode === 'side-by-side' && liveFinalChunks.length > 0">
                            <div class="space-y-1">
                              <div v-for="(chunk, idx) in liveFinalChunks" :key="`live-${idx}`">
                                <span class="leading-8">{{ chunk }}</span>
                                <div v-if="sentenceTranslations[`live-${idx}`]"
                                  class="text-xs text-primary/70 italic leading-6">
                                  {{ sentenceTranslations[`live-${idx}`] }}
                                </div>
                                <div v-else-if="translatingIds.has(`live-${idx}`)"
                                  class="text-xs text-muted-foreground/50 italic leading-6">
                                  {{ t("workbench.transcript.translating") }}
                                </div>
                              </div>
                              <span v-if="liveInterimChunk" class="text-muted-foreground/50 leading-8">{{ liveInterimChunk }}</span>
                            </div>
                          </template>
                          <template v-else>
                            <span>{{ transcription }}</span>
                            <span v-if="liveInterimChunk" class="text-muted-foreground/50">{{
                              transcription ? ` ${liveInterimChunk}` : liveInterimChunk
                              }}</span>
                          </template>
                        </template>
                        <template v-else>
                          {{ transcription }}
                        </template>
                      </div>
                    </div>

                    <!-- Floating Control Bar (overlay on transcript, not tied to transcript scroll) -->
                    <div class="pointer-events-none absolute inset-x-4 bottom-4 z-10 flex flex-col gap-2 justify-center">
                      <!-- Upload playback: seekable slider + time -->
                      <div v-if="inputMode === 'upload' && uploadAudioEl && audioDuration > 0"
                        class="pointer-events-auto flex items-center gap-3 rounded-md px-3 py-1.5 bg-background/45 backdrop-blur-sm">
                        <span class="text-xs tabular-nums text-muted-foreground w-8 text-right">{{
                          formatTime(playbackCurrentTime)
                          }}</span>
                        <Slider :model-value="[playbackProgress]" :max="100" :step="0.1" class="flex-1"
                          @update:model-value="onSliderSeek" />
                        <span class="text-xs tabular-nums text-muted-foreground w-8">{{
                          formatTime(audioDuration)
                          }}</span>
                      </div>

                      <InputGroup
                        class="pointer-events-auto relative w-full h-[42px] bg-background/65 shadow-sm shadow-black/5 backdrop-blur-md !rounded-md border-input overflow-hidden">
                        <InputGroupAddon align="inline-start">
                          <DropdownMenu>
                            <DropdownMenuTrigger as-child>
                              <Button variant="ghost" size="sm"
                                class="h-8 rounded-sm px-2 hover:bg-muted font-medium text-xs gap-1.5 transition-colors">
                                {{ inputModeLabelMap[inputMode]() }}
                                <ChevronDown class="h-3.5 w-3.5 opacity-60" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start" class="w-48 rounded-md p-1 shadow-lg">
                              <DropdownMenuItem @select="chooseInputMode('realtime')" class="rounded-sm py-2">
                                <span class="mr-2 inline-flex w-4 justify-center">
                                  <Check class="h-4 w-4"
                                    :class="inputMode === 'realtime' ? 'opacity-100' : 'opacity-0'" />
                                </span>
                                <span>{{ t("workbench.recording.modeRealtime") }}</span>
                              </DropdownMenuItem>
                              <DropdownMenuItem @select="chooseInputMode('system')" class="rounded-sm py-2">
                                <span class="mr-2 inline-flex w-4 justify-center">
                                  <Check class="h-4 w-4"
                                    :class="inputMode === 'system' ? 'opacity-100' : 'opacity-0'" />
                                </span>
                                <span>{{ t("workbench.recording.modeSystem") }}</span>
                              </DropdownMenuItem>
                              <DropdownMenuItem @select="chooseInputMode('upload')" class="rounded-sm py-2">
                                <span class="mr-2 inline-flex w-4 justify-center">
                                  <Check class="h-4 w-4"
                                    :class="inputMode === 'upload' ? 'opacity-100' : 'opacity-0'" />
                                </span>
                                <span>{{ t("workbench.recording.modeUpload") }}</span>
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </InputGroupAddon>

                        <Separator orientation="vertical" class="h-4 my-auto shrink-0 opacity-50" />

                        <div class="flex-1 min-w-0 pointer-events-none flex items-center justify-center px-2">
                          <div class="w-full max-w-[360px]">
                            <canvas ref="canvasRef" class="w-full h-8 block" />
                          </div>
                        </div>

                        <InputGroupAddon align="inline-end">
                          <!-- Upload mode with transcript ready: play/pause button -->
                          <InputGroupButton v-if="inputMode === 'upload' && uploadAudioEl && transcription"
                            size="icon-sm" :variant="isPlaying ? 'destructive' : 'default'" class="rounded-sm"
                            @click="toggleUploadPlayback">
                            <Pause v-if="isPlaying" class="h-4 w-4" />
                            <Play v-else class="h-4 w-4" />
                          </InputGroupButton>
                          <!-- Upload mode: transcribing or not yet transcribed -->
                          <InputGroupButton v-else-if="inputMode === 'upload'" size="icon-sm" variant="default"
                            class="rounded-sm" @click="toggleRecording" :disabled="isTranscribingUpload">
                            <Mic class="h-4 w-4" />
                          </InputGroupButton>
                          <!-- Live modes: record / stop -->
                          <InputGroupButton v-else size="icon-sm" :variant="isRecording ? 'destructive' : 'default'"
                            class="rounded-sm" @click="toggleRecording">
                            <Pause v-if="isRecording" class="h-4 w-4" />
                            <Mic v-else class="h-4 w-4" />
                          </InputGroupButton>
                        </InputGroupAddon>
                      </InputGroup>
                    </div>
                  </CardContent>
                </ResizablePanel>

                <template v-if="translationActive && translationMode === 'separate'">
                  <ResizableHandle with-handle />
                  <ResizablePanel :default-size="35" :min-size="20">
                    <div class="h-full border-t bg-background/30 flex flex-col">
                      <div class="px-4 py-2 border-b flex items-center gap-2 text-xs text-muted-foreground shrink-0">
                        <Languages class="h-3.5 w-3.5" />
                        <span class="font-medium">{{ translationTargetLanguageLabel }}</span>
                      </div>
                      <div class="flex-1 min-h-0 overflow-y-auto px-4 py-4 text-sm">
                        <!-- Separate panel: show all translations -->
                        <template v-if="inputMode === 'upload' && transcriptSentences.length > 0">
                          <div class="space-y-2">
                            <div v-for="sentence in transcriptSentences" :key="`sep-${sentence.id}`"
                              class="text-muted-foreground/90 leading-relaxed">
                              <template v-if="sentenceTranslations[sentence.id]">
                                {{ sentenceTranslations[sentence.id] }}
                              </template>
                              <template v-else-if="translatingIds.has(sentence.id)">
                                <span class="text-muted-foreground/50 italic">{{ t("workbench.transcript.translating") }}</span>
                              </template>
                              <template v-else>
                                <span class="text-muted-foreground/40 italic">—</span>
                              </template>
                            </div>
                          </div>
                        </template>
                        <template v-else-if="liveFinalChunks.length > 0">
                          <div class="space-y-2">
                            <div v-for="(_, idx) in liveFinalChunks" :key="`sep-live-${idx}`"
                              class="text-muted-foreground/90 leading-relaxed">
                              <template v-if="sentenceTranslations[`live-${idx}`]">
                                {{ sentenceTranslations[`live-${idx}`] }}
                              </template>
                              <template v-else-if="translatingIds.has(`live-${idx}`)">
                                <span class="text-muted-foreground/50 italic">{{ t("workbench.transcript.translating") }}</span>
                              </template>
                              <template v-else>
                                <span class="text-muted-foreground/40 italic">—</span>
                              </template>
                            </div>
                          </div>
                        </template>
                        <template v-else>
                          <div class="h-full flex items-center justify-center gap-2 text-muted-foreground">
                            <Info class="h-4 w-4" />
                            <span>{{ t("workbench.transcript.translateEmptyHint") }}</span>
                          </div>
                        </template>
                      </div>
                    </div>
                  </ResizablePanel>
                </template>
              </ResizablePanelGroup>
            </Card>
          </div>

          <input ref="fileInputRef" type="file" accept="audio/*" class="hidden" @change="onAudioFileChange" />
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  </div>
</template>
