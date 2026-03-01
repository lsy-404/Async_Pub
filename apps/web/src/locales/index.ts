import { createI18n } from "vue-i18n";
import { useLocalStorage } from "@vueuse/core";
import zhCN from "./zh-CN";
import enUS from "./en-US";

const messages = {
  "zh-CN": zhCN,
  "en-US": enUS,
};

// 使用 localStorage 持久化语言设置
const savedLocale = useLocalStorage("app-locale", "zh-CN");

const i18n = createI18n({
  legacy: false, // 使用 Composition API 必须设置为 false
  locale: savedLocale.value, // 初始语言从 localStorage 读取
  fallbackLocale: "en-US", // 回退语言
  messages,
  globalInjection: true, // 全局注入 $t
});

export default i18n;
