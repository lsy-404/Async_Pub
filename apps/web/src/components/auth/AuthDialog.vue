<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useAuthStore } from "@/stores/auth";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlertCircle, Loader2 } from "lucide-vue-next";

const props = defineProps<{
  open: boolean;
  initialError?: string;
}>();

const emit = defineEmits<{
  (e: "update:open", value: boolean): void;
  (e: "saved"): void;
}>();

const { t } = useI18n();
const authStore = useAuthStore();

const backendUrl = ref(authStore.backendUrl);
const tab = ref<"login" | "register">("login");
const isSubmitting = ref(false);
const errorMessage = ref("");
const loginUsername = ref("");
const loginPassword = ref("");
const registerUsername = ref("");
const registerPassword = ref("");
const registerEmail = ref("");
const registerInviteToken = ref("");
const touched = ref<Record<string, boolean>>({});
const serverErrorField = ref<{
  loginCredentials?: boolean;
  registerUsername?: boolean;
  registerInviteToken?: boolean;
}>({});

const usernamePattern = /^[a-zA-Z0-9_-]{3,64}$/;
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const loginUsernameInvalid = computed(
  () =>
    (touched.value.loginUsername && !usernamePattern.test(loginUsername.value.trim())) ||
    !!serverErrorField.value.loginCredentials,
);
const loginPasswordInvalid = computed(
  () =>
    (touched.value.loginPassword && loginPassword.value.length < 6) ||
    !!serverErrorField.value.loginCredentials,
);

const registerUsernameInvalid = computed(
  () =>
    (touched.value.registerUsername && !usernamePattern.test(registerUsername.value.trim())) ||
    !!serverErrorField.value.registerUsername,
);
const registerPasswordInvalid = computed(
  () => touched.value.registerPassword && registerPassword.value.length < 6,
);
const registerEmailInvalid = computed(
  () =>
    touched.value.registerEmail &&
    !!registerEmail.value.trim() &&
    !emailPattern.test(registerEmail.value.trim()),
);
const registerInviteInvalid = computed(
  () =>
    (touched.value.registerInviteToken && !registerInviteToken.value.trim()) ||
    !!serverErrorField.value.registerInviteToken,
);

const canSubmitLogin = computed(
  () =>
    usernamePattern.test(loginUsername.value.trim()) &&
    loginPassword.value.length >= 6 &&
    !isSubmitting.value,
);
const canSubmitRegister = computed(
  () =>
    usernamePattern.test(registerUsername.value.trim()) &&
    registerPassword.value.length >= 6 &&
    !!registerInviteToken.value.trim() &&
    (!registerEmail.value.trim() || emailPattern.test(registerEmail.value.trim())) &&
    !isSubmitting.value,
);

const normalizedBackendUrlInput = computed(() => backendUrl.value.trim());
const canSaveBackendUrl = computed(
  () => !isSubmitting.value && normalizedBackendUrlInput.value !== authStore.backendUrl,
);

watch(
  () => props.open,
  (newVal) => {
    if (newVal) {
      backendUrl.value = authStore.backendUrl;
      errorMessage.value = props.initialError || "";
      touched.value = {};
      serverErrorField.value = {};
    }
  },
);

const markLoginTouched = () => {
  touched.value.loginUsername = true;
  touched.value.loginPassword = true;
};

const markRegisterTouched = () => {
  touched.value.registerUsername = true;
  touched.value.registerPassword = true;
  touched.value.registerEmail = true;
  touched.value.registerInviteToken = true;
};

const submitLogin = async () => {
  markLoginTouched();
  if (!canSubmitLogin.value) return;

  isSubmitting.value = true;
  errorMessage.value = "";
  serverErrorField.value = {};
  authStore.setBackendUrl(backendUrl.value.trim());

  const result = await authStore.login({
    username: loginUsername.value.trim(),
    password: loginPassword.value,
  });

  if (!result.success) {
    if (result.error === "invalidCredentials") {
      serverErrorField.value.loginCredentials = true;
    }
    errorMessage.value = t(`auth.${result.error || "loginFailed"}`);
    isSubmitting.value = false;
    return;
  }

  const verifyResult = await authStore.validateToken();
  if (!verifyResult.success) {
    errorMessage.value = t(`auth.${verifyResult.error || "invalidToken"}`);
    isSubmitting.value = false;
    return;
  }

  isSubmitting.value = false;
  emit("saved");
  emit("update:open", false);
};

const submitRegister = async () => {
  markRegisterTouched();
  if (!canSubmitRegister.value) return;

  isSubmitting.value = true;
  errorMessage.value = "";
  serverErrorField.value = {};
  authStore.setBackendUrl(backendUrl.value.trim());

  const result = await authStore.register({
    username: registerUsername.value.trim(),
    password: registerPassword.value,
    email: registerEmail.value.trim() || undefined,
    invite_token: registerInviteToken.value.trim(),
  });

  if (!result.success) {
    if (result.error === "invalidInviteToken") {
      serverErrorField.value.registerInviteToken = true;
    }
    if (result.error === "usernameTaken") {
      serverErrorField.value.registerUsername = true;
    }
    errorMessage.value = t(`auth.${result.error || "registerFailed"}`);
    isSubmitting.value = false;
    return;
  }

  const verifyResult = await authStore.validateToken();
  if (!verifyResult.success) {
    errorMessage.value = t(`auth.${verifyResult.error || "invalidToken"}`);
    isSubmitting.value = false;
    return;
  }

  isSubmitting.value = false;
  emit("saved");
  emit("update:open", false);
};

const logout = () => {
  authStore.clearAuth();
  emit("saved");
  emit("update:open", false);
};

const saveBackendUrl = () => {
  authStore.setBackendUrl(normalizedBackendUrlInput.value);
  backendUrl.value = authStore.backendUrl;
  emit("saved");
};

const onUpdateOpen = (value: boolean) => {
  // If not authenticated, don't allow closing the dialog
  if (!authStore.isAuthenticated() && !value) {
    return;
  }
  emit("update:open", value);
};
</script>

<template>
  <Dialog :open="props.open" @update:open="onUpdateOpen">
    <DialogContent class="sm:max-w-[500px]" :close-disabled="!authStore.isAuthenticated()">
      <DialogHeader>
        <DialogTitle>{{ t("auth.title") }}</DialogTitle>
        <DialogDescription>
          {{ t("auth.description") }}
        </DialogDescription>
      </DialogHeader>

      <div class="grid gap-4 py-4">
        <div class="grid gap-2">
          <Label for="url">{{ t("auth.urlLabel") }}</Label>
          <Input
            id="url"
            v-model="backendUrl"
            :placeholder="t('auth.urlPlaceholder')"
            :disabled="isSubmitting"
          />
        </div>

        <template v-if="authStore.currentUser">
          <div class="rounded-md border p-3 text-sm space-y-1">
            <div>
              <span class="text-muted-foreground">{{ t("auth.user.username") }}：</span>
              <span class="font-medium">{{ authStore.currentUser.username }}</span>
            </div>
            <div>
              <span class="text-muted-foreground">{{ t("auth.user.email") }}：</span>
              <span>{{ authStore.currentUser.email || t("auth.user.empty") }}</span>
            </div>
          </div>
        </template>

        <Tabs v-else v-model="tab" class="w-full">
          <TabsList class="grid w-full grid-cols-2">
            <TabsTrigger value="login">{{ t("auth.tabs.login") }}</TabsTrigger>
            <TabsTrigger value="register">{{ t("auth.tabs.register") }}</TabsTrigger>
          </TabsList>

          <TabsContent value="login" class="space-y-3 mt-3">
            <div class="grid gap-2">
              <Label for="login-username">{{ t("auth.usernameLabel") }}</Label>
              <Input
                id="login-username"
                v-model="loginUsername"
                :placeholder="t('auth.loginUsernamePlaceholder')"
                :disabled="isSubmitting"
                :class="{
                  'border-destructive focus-visible:ring-destructive/40': loginUsernameInvalid,
                }"
                @blur="touched.loginUsername = true"
                @input="serverErrorField.loginCredentials = false"
                @keydown.enter="submitLogin"
              />
            </div>
            <div class="grid gap-2">
              <Label for="login-password">{{ t("auth.passwordLabel") }}</Label>
              <Input
                id="login-password"
                v-model="loginPassword"
                type="password"
                :placeholder="t('auth.loginPasswordPlaceholder')"
                :disabled="isSubmitting"
                :class="{
                  'border-destructive focus-visible:ring-destructive/40': loginPasswordInvalid,
                }"
                @blur="touched.loginPassword = true"
                @input="serverErrorField.loginCredentials = false"
                @keydown.enter="submitLogin"
              />
            </div>
          </TabsContent>

          <TabsContent value="register" class="space-y-3 mt-3">
            <div class="grid gap-2">
              <Label for="register-username">{{ t("auth.usernameLabel") }}</Label>
              <Input
                id="register-username"
                v-model="registerUsername"
                :placeholder="t('auth.usernamePlaceholder')"
                :disabled="isSubmitting"
                :class="{
                  'border-destructive focus-visible:ring-destructive/40': registerUsernameInvalid,
                }"
                @blur="touched.registerUsername = true"
                @input="serverErrorField.registerUsername = false"
              />
            </div>
            <div class="grid gap-2">
              <Label for="register-password">{{ t("auth.passwordLabel") }}</Label>
              <Input
                id="register-password"
                v-model="registerPassword"
                type="password"
                :placeholder="t('auth.passwordPlaceholder')"
                :disabled="isSubmitting"
                :class="{
                  'border-destructive focus-visible:ring-destructive/40': registerPasswordInvalid,
                }"
                @blur="touched.registerPassword = true"
              />
            </div>
            <div class="grid gap-2">
              <Label for="register-email">{{ t("auth.emailLabel") }}</Label>
              <Input
                id="register-email"
                v-model="registerEmail"
                :placeholder="t('auth.emailPlaceholder')"
                :disabled="isSubmitting"
                :class="{
                  'border-destructive focus-visible:ring-destructive/40': registerEmailInvalid,
                }"
                @blur="touched.registerEmail = true"
              />
            </div>
            <div class="grid gap-2">
              <Label for="register-invite">{{ t("auth.inviteLabel") }}</Label>
              <Input
                id="register-invite"
                v-model="registerInviteToken"
                :placeholder="t('auth.invitePlaceholder')"
                :disabled="isSubmitting"
                :class="{
                  'border-destructive focus-visible:ring-destructive/40': registerInviteInvalid,
                }"
                @blur="touched.registerInviteToken = true"
                @input="serverErrorField.registerInviteToken = false"
                @keydown.enter="submitRegister"
              />
            </div>
          </TabsContent>
        </Tabs>

        <div v-if="errorMessage" class="flex items-center gap-2 text-sm text-destructive mt-1">
          <AlertCircle class="h-4 w-4" />
          {{ errorMessage }}
        </div>
      </div>
      <DialogFooter>
        <template v-if="authStore.currentUser">
          <Button type="button" @click="saveBackendUrl" :disabled="!canSaveBackendUrl">{{
            t("common.save")
          }}</Button>
          <Button type="button" variant="outline" @click="logout">{{ t("auth.logout") }}</Button>
        </template>
        <template v-else>
          <Button
            v-if="tab === 'login'"
            type="button"
            @click="submitLogin"
            :disabled="!canSubmitLogin"
          >
            <Loader2 v-if="isSubmitting" class="mr-2 h-4 w-4 animate-spin" />
            {{ isSubmitting ? t("auth.submitting") : t("auth.login") }}
          </Button>
          <Button v-else type="button" @click="submitRegister" :disabled="!canSubmitRegister">
            <Loader2 v-if="isSubmitting" class="mr-2 h-4 w-4 animate-spin" />
            {{ isSubmitting ? t("auth.submitting") : t("auth.register") }}
          </Button>
        </template>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
