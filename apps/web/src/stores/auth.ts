import { defineStore } from "pinia";
import { useLocalStorage } from "@vueuse/core";
import { computed, ref } from "vue";

export const useFrontendMockData = false;

export interface RegisterPayload {
  username: string;
  password: string;
  email?: string;
  invite_token: string;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  user_id: string;
  username: string;
}

export interface CurrentUser {
  id: string;
  username: string;
  email: string | null;
  created_at: string;
  last_login: string | null;
}

export const useAuthStore = defineStore("auth", () => {
  const token = useLocalStorage("auth-token", "");
  const backendUrl = useLocalStorage("auth-backend-url", "");
  const currentUser = ref<CurrentUser | null>(null);

  const normalizeUrl = (url: string) => {
    if (!url) return "";
    let normalized = url.trim();
    if (!/^https?:\/\//i.test(normalized)) {
      normalized = `https://${normalized}`;
    }
    return normalized.replace(/\/+$/, "");
  };

  const effectiveBackendUrl = computed(() => {
    const rawUrl = backendUrl.value || import.meta.env.VITE_BACKEND_URL || "";
    return normalizeUrl(rawUrl);
  });

  const setToken = (newToken: string) => {
    token.value = newToken;
  };

  const setBackendUrl = (newUrl: string) => {
    backendUrl.value = newUrl;
  };

  const clearAuth = () => {
    token.value = "";
    currentUser.value = null;
  };

  const getAuthHeaders = (extra?: Record<string, string>) => {
    const headers: Record<string, string> = {
      ...(extra || {}),
    };

    if (token.value) {
      headers.Authorization = `Bearer ${token.value}`;
      // Backward compatibility with legacy backend routes
      headers.auth = token.value;
    }

    return headers;
  };

  const login = async (payload: LoginPayload): Promise<{ success: boolean; error?: string }> => {
    const url = effectiveBackendUrl.value;
    if (!url) return { success: false, error: "serverUnreachable" };

    try {
      const response = await fetch(`${url}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        if (response.status === 401) return { success: false, error: "invalidCredentials" };
        return { success: false, error: "loginFailed" };
      }

      const data: AuthResponse = await response.json();
      token.value = data.access_token;
      return { success: true };
    } catch (err) {
      console.error("Login failed:", err);
      return { success: false, error: "serverUnreachable" };
    }
  };

  const register = async (
    payload: RegisterPayload,
  ): Promise<{ success: boolean; error?: string }> => {
    const url = effectiveBackendUrl.value;
    if (!url) return { success: false, error: "serverUnreachable" };

    try {
      const response = await fetch(`${url}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        if (response.status === 400) {
          const errBody = await response.json().catch(() => ({}));
          const detail = String(errBody?.detail || "").toLowerCase();
          if (detail.includes("invitation") || detail.includes("invite")) {
            return { success: false, error: "invalidInviteToken" };
          }
          if (detail.includes("username")) {
            return { success: false, error: "usernameTaken" };
          }
          return { success: false, error: "registerFailed" };
        }
        return { success: false, error: "registerFailed" };
      }

      const data: AuthResponse = await response.json();
      token.value = data.access_token;
      return { success: true };
    } catch (err) {
      console.error("Register failed:", err);
      return { success: false, error: "serverUnreachable" };
    }
  };

  const fetchCurrentUser = async (): Promise<{ success: boolean; error?: string }> => {
    if (!token.value) return { success: false, error: "tokenRequired" };

    const url = effectiveBackendUrl.value;
    if (!url) return { success: false, error: "serverUnreachable" };

    try {
      const response = await fetch(`${url}/api/auth/me`, {
        headers: getAuthHeaders(),
      });

      if (!response.ok) {
        if (response.status === 401) {
          clearAuth();
          return { success: false, error: "invalidToken" };
        }
        return { success: false, error: "serverUnreachable" };
      }

      currentUser.value = await response.json();
      return { success: true };
    } catch (err) {
      console.error("Fetch current user failed:", err);
      return { success: false, error: "serverUnreachable" };
    }
  };

  const validateToken = async (): Promise<{ success: boolean; error?: string }> => {
    if (!token.value) return { success: false, error: "tokenRequired" };

    const url = effectiveBackendUrl.value;
    if (!url) return { success: false, error: "serverUnreachable" };

    try {
      const response = await fetch(`${url}/api/auth/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token.value }),
      });

      if (response.ok) {
        const meResult = await fetchCurrentUser();
        if (!meResult.success) {
          return meResult;
        }
        return { success: true };
      } else {
        clearAuth();
        return { success: false, error: "invalidToken" };
      }
    } catch (err) {
      console.error("Auth verification failed:", err);
      return { success: false, error: "serverUnreachable" };
    }
  };

  const isAuthenticated = () => {
    return !!token.value;
  };

  return {
    token,
    backendUrl,
    currentUser,
    effectiveBackendUrl,
    setToken,
    setBackendUrl,
    clearAuth,
    getAuthHeaders,
    login,
    register,
    fetchCurrentUser,
    validateToken,
    isAuthenticated,
  };
});
