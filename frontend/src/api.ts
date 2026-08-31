// Тонкий клиент REST API бэкенда.

export type Platform = "tiktok" | "youtube";
export type JobStatus = "pending" | "rendering" | "uploading" | "done" | "failed";
export type BannerType = "image" | "video";

export interface Account {
  id: number;
  name: string;
  platform: Platform;
  proxy_url: string | null;
  proxy_ok: boolean | null;
  proxy_ip: string | null;
  proxy_checked_at: string | null;
  uniqueize: boolean;
  active: boolean;
  has_cookies: boolean;
  created_at: string;
  // Автовход: пароли наружу не отдаются, только признаки
  tt_login: string | null;
  has_tt_credentials: boolean;
  mail_address: string | null;
  mail_kind: string | null;
  mail_connected: boolean;
  mail_connected_at: string | null;
  auto_login: boolean;
  last_login_at: string | null;
  login_error: string | null;
}

/** Поля профиля, которые можно задать при создании и правке. */
export interface AccountCredentials {
  tt_login: string | null;
  tt_password: string | null;
  mail_address: string | null;
  mail_password: string | null;
  mail_imap_host: string | null;
  mail_imap_port: number | null;
  auto_login: boolean;
}

export interface AutoLoginState {
  stage: "idle" | "starting" | "filling" | "waiting_code" | "submitting_code" | "done" | "captcha" | "error";
  message: string | null;
  screenshot: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface MailMessage {
  id: string;
  sender: string;
  subject: string;
  received_at: string | null;
  preview: string;
}

export interface MailConnect {
  user_code: string;
  verification_uri: string;
  expires_in: number;
}

export interface MailConnectState {
  state: "idle" | "pending" | "done" | "error";
  message: string | null;
}

export interface ProxyCheck {
  ok: boolean;
  ip: string | null;
  error: string | null;
}

export interface LoginStage {
  stage: "done" | "email_code" | "captcha" | "unknown";
  screenshot: string | null;
  message: string | null;
}

export interface Video {
  id: number;
  title: string;
  filename: string;
  width: number | null;
  height: number | null;
  duration: number | null;
  created_at: string;
}

export type Motion = "none" | "drift" | "bounce" | "slide";

export interface Banner {
  id: number;
  name: string;
  type: BannerType;
  filename: string;
  x: number;
  y: number;
  scale: number;
  opacity: number;
  motion: Motion;
  motion_speed: number;
  created_at: string;
}

/** Слой-баннер: ссылается на баннер по id, позиция/движение — доли кадра. */
export interface BannerOverlay {
  type: "banner";
  banner_id: number;
  x: number;
  y: number;
  scale: number;
  opacity: number;
  motion: Motion;
  motion_speed: number;
}

/** Текстовый слой: вжигается в видео через ffmpeg drawtext. */
export interface TextOverlayData {
  type: "text";
  text: string;
  x: number;
  y: number;
  font_size: number;   // доля высоты кадра (0..1) либо пиксели (>1)
  color: string;
  opacity: number;
}

export type Overlay = BannerOverlay | TextOverlayData;

export interface Job {
  id: number;
  /** Общий id пачки: одно видео, разосланное на несколько аккаунтов */
  group_id: string | null;
  account_id: number;
  video_id: number;
  banner_id: number | null;
  caption: string;
  banner_x: number | null;
  banner_y: number | null;
  banner_scale: number | null;
  overlays: string | null;   // JSON-строка со слоями (как хранит бэкенд)
  status: JobStatus;
  scheduled_at: string | null;
  output_filename: string | null;
  error: string | null;
  log: string;
  posted_url: string | null;
  created_at: string;
  updated_at: string;
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const b = await r.json();
      detail = b.detail || JSON.stringify(b);
    } catch {}
    throw new Error(detail);
  }
  return r.json();
}

export interface AuthMe {
  authenticated: boolean;
  username: string | null;
  tg_login: boolean;
}

export interface SystemVersion {
  version: string;
  update_status: string;
  update_requested: boolean;
  /** ok | auth_required (приватный репо без токена) | error | no_git | "" */
  git_status: string;
}

export interface SettingsData {
  admin_user: string;
  tg_bot_configured: boolean;
  tg_chat_id: string | null;
  tg_login_enabled: boolean;
  ms_client_id: string | null;
}

export const api = {
  health: () => fetch("/api/health").then((r) => j<any>(r)),

  // auth
  authMe: () => fetch("/api/auth/me").then((r) => j<AuthMe>(r)),
  login: (username: string, password: string) =>
    fetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }).then((r) => j<any>(r)),
  logout: () => fetch("/api/auth/logout", { method: "POST" }).then((r) => j<any>(r)),
  tgLoginRequest: () => fetch("/api/auth/telegram/request", { method: "POST" }).then((r) => j<any>(r)),
  tgLoginVerify: (code: string) =>
    fetch("/api/auth/telegram/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }).then((r) => j<any>(r)),

  // system
  systemVersion: () => fetch("/api/system/version").then((r) => j<SystemVersion>(r)),
  systemUpdate: () => fetch("/api/system/update", { method: "POST" }).then((r) => j<any>(r)),
  systemGitToken: (token: string) =>
    fetch("/api/system/git-token", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }).then((r) => j<{ ok: boolean; error?: string }>(r)),

  // settings
  getSettings: () => fetch("/api/settings").then((r) => j<SettingsData>(r)),
  updateSettings: (b: Partial<{ tg_bot_token: string; tg_chat_id: string; tg_login_enabled: boolean; new_password: string; ms_client_id: string }>) =>
    fetch("/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<SettingsData>(r)),

  // accounts
  accounts: () => fetch("/api/accounts").then((r) => j<Account[]>(r)),
  createAccount: (b: { name: string; platform: Platform; proxy_url?: string | null; uniqueize?: boolean } & Partial<AccountCredentials> & { start_login?: boolean }) =>
    fetch("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<Account>(r)),
  updateAccount: (id: number, b: Partial<{ name: string; proxy_url: string | null; active: boolean; uniqueize: boolean } & AccountCredentials>) =>
    fetch(`/api/accounts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<Account>(r)),
  deleteAccount: (id: number) => fetch(`/api/accounts/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  uploadCookies: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/accounts/${id}/cookies`, { method: "POST", body: fd }).then((r) => j<Account>(r));
  },
  checkProxy: (id: number) =>
    fetch(`/api/accounts/${id}/check-proxy`, { method: "POST" }).then((r) => j<ProxyCheck>(r)),
  loginCredentials: (id: number, b: { username: string; password: string }) =>
    fetch(`/api/accounts/${id}/login/credentials`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<LoginStage>(r)),
  loginCode: (id: number, code: string) =>
    fetch(`/api/accounts/${id}/login/code`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }).then((r) => j<LoginStage>(r)),
  loginCancel: () => fetch(`/api/accounts/login/cancel`, { method: "POST" }).then((r) => j<any>(r)),

  // автоматический вход: логин, пароль и код из почты — панель делает сама
  loginAuto: (id: number) =>
    fetch(`/api/accounts/${id}/login/auto`, { method: "POST" }).then((r) => j<AutoLoginState>(r)),
  loginState: (id: number) => fetch(`/api/accounts/${id}/login/state`).then((r) => j<AutoLoginState>(r)),

  // почта аккаунта
  mailList: (id: number, limit = 20) =>
    fetch(`/api/accounts/${id}/mail?limit=${limit}`).then((r) => j<MailMessage[]>(r)),
  mailBody: (id: number, msgId: string) =>
    fetch(`/api/accounts/${id}/mail/message/${encodeURIComponent(msgId)}`).then((r) => j<{ body: string }>(r)),
  mailCode: (id: number) =>
    fetch(`/api/accounts/${id}/mail/code`, { method: "POST" }).then((r) => j<{ code: string | null; message: string | null }>(r)),
  mailConnect: (id: number) =>
    fetch(`/api/accounts/${id}/mail/connect`, { method: "POST" }).then((r) => j<MailConnect>(r)),
  mailConnectState: (id: number) =>
    fetch(`/api/accounts/${id}/mail/connect/state`).then((r) => j<MailConnectState>(r)),

  // videos
  videos: () => fetch("/api/videos").then((r) => j<Video[]>(r)),
  uploadVideo: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/videos", { method: "POST", body: fd }).then((r) => j<Video>(r));
  },
  deleteVideo: (id: number) => fetch(`/api/videos/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  videoFileUrl: (id: number) => `/api/videos/${id}/file`,

  // banners
  banners: () => fetch("/api/banners").then((r) => j<Banner[]>(r)),
  uploadBanner: (file: File, name: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    return fetch("/api/banners", { method: "POST", body: fd }).then((r) => j<Banner>(r));
  },
  updateBanner: (id: number, b: Partial<Pick<Banner, "name" | "x" | "y" | "scale" | "opacity" | "motion" | "motion_speed">>) =>
    fetch(`/api/banners/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<Banner>(r)),
  deleteBanner: (id: number) => fetch(`/api/banners/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  bannerFileUrl: (id: number) => `/api/banners/${id}/file`,

  // jobs
  jobs: () => fetch("/api/jobs").then((r) => j<Job[]>(r)),
  createJob: (b: {
    account_id: number;
    video_id: number;
    banner_id?: number | null;
    caption?: string;
    banner_x?: number | null;
    banner_y?: number | null;
    banner_scale?: number | null;
    scheduled_at?: string | null;
    overlays?: Overlay[] | null;
  }) =>
    fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<Job>(r)),

  /** Одно видео на несколько аккаунтов: у каждого свой рендер и свой хеш */
  createJobsBulk: (b: {
    account_ids: number[];
    video_id: number;
    banner_id?: number | null;
    caption?: string;
    scheduled_at?: string | null;
    overlays?: Overlay[] | null;
    spread_min_minutes?: number;
    spread_max_minutes?: number;
    vary_caption?: boolean;
  }) =>
    fetch("/api/jobs/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<{ jobs: Job[]; skipped: string[] }>(r)),
  retryJob: (id: number) => fetch(`/api/jobs/${id}/retry`, { method: "POST" }).then((r) => j<Job>(r)),
  deleteJob: (id: number) => fetch(`/api/jobs/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
};
