import { defineStore } from "pinia";
import { ref, computed } from "vue";

export type ContextItemType = "workspace" | "folder" | "session" | "file";

export interface ContextItem {
  id: number;
  name: string;
  type: ContextItemType;
  /** Estimated token count (rough: 1 char ≈ 1 token for CJK, 0.25 for Latin) */
  estimatedTokens: number;
}

/**
 * Rough token estimation based on name length and node type.
 * This is a placeholder — real estimation would inspect file content.
 */
const estimateTokens = (name: string, type: ContextItemType): number => {
  const base = name.length;
  switch (type) {
    case "workspace":
      return base * 500; // workspace contains many files
    case "folder":
      return base * 200; // folder contains several files
    case "session":
      return base * 100; // a session has conversation history
    case "file":
      return base * 50; // a single document
    default:
      return base;
  }
};

export const useContextStore = defineStore("context", () => {
  const items = ref<ContextItem[]>([]);

  const totalEstimatedTokens = computed(() =>
    items.value.reduce((sum, item) => sum + item.estimatedTokens, 0),
  );

  const hasItems = computed(() => items.value.length > 0);

  const isAdded = (id: number, type: ContextItemType) =>
    items.value.some((item) => item.id === id && item.type === type);

  const addItem = (id: number, name: string, type: ContextItemType) => {
    if (isAdded(id, type)) return;
    items.value.push({
      id,
      name,
      type,
      estimatedTokens: estimateTokens(name, type),
    });
  };

  const removeItem = (id: number, type: ContextItemType) => {
    items.value = items.value.filter(
      (item) => !(item.id === id && item.type === type),
    );
  };

  const clearAll = () => {
    items.value = [];
  };

  return {
    items,
    totalEstimatedTokens,
    hasItems,
    isAdded,
    addItem,
    removeItem,
    clearAll,
  };
});
