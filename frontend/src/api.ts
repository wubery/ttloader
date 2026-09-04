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
  /** Профиль уникализации, закреплённый за аккаунтом */
  uniq_profile_id: number | null;
  /** Группа-когорта аккаунта (см. AccountGroup). Не путать с Job.group_id — там пачка задач. */
  group_id: number | null;
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

/** Папка внутри библиотеки (видео / хуки / фоны).
 *  Пустой group_ids = папка ничего не ограничивает, просто полка. */
export interface AssetFolder {
  id: number;
  kind: FolderKind;
  name: string;
  group_ids: number[];
  items_count: number;
  created_at: string;
}

export type FolderKind = "video" | "hook" | "background";

/** Группа аккаунтов: когорта для проверки гипотез постинга. */
export interface AccountGroup {
  id: number;
  name: string;
  color: string | null;
  accounts_count: number;
  created_at: string;
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
  /** Папка библиотеки; null — файл доступен всем группам */
  folder_id: number | null;
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

export interface Hook {
  id: number;
  name: string;
  filename: string;
  width: number | null;
  height: number | null;
  duration: number | null;
  created_at: string;
  /** Папка библиотеки; null — файл доступен всем группам */
  folder_id: number | null;
}

export interface OverlayAsset {
  id: number;
  name: string;
  filename: string;
  created_at: string;
}

export interface AdClip {
  id: number;
  name: string;
  filename: string;
  width: number | null;
  height: number | null;
  duration: number | null;
  created_at: string;
}

export interface Background {
  id: number;
  name: string;
  filename: string;
  is_video: boolean;
  created_at: string;
  /** Папка библиотеки; null — файл доступен всем группам */
  folder_id: number | null;
}

/** Профиль уникализации: каждый параметр — диапазон [от, до]; равные границы = ручное значение */
export interface UniqProfile {
  id: number;
  name: string;
  params: Record<string, any>;
  is_default: boolean;
  created_at: string;
}

export interface Job {
  id: number;
  /** Общий id пачки: одно видео, разосланное на несколько аккаунтов */
  group_id: string | null;
  uniq_profile_id: number | null;
  part_index: number | null;
  part_total: number | null;
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

/**
 * Ролики крупнее порога заливаются кусками. Причина не в бэкенде: между браузером
 * и панелью почти всегда есть чужой прокси, который отбрасывает большое тело
 * запроса целиком (у Cloudflare это 100 МБ), и браузер показывает голое
 * «Failed to fetch». Куски по 8 МБ — обычные маленькие запросы, они проходят
 * везде, а обрыв стоит одного куска, который просто повторяется.
 */
const CHUNK_SIZE = 8 * 1024 * 1024;
const CHUNK_THRESHOLD = 16 * 1024 * 1024;
const CHUNK_RETRIES = 3;

/** Ошибка API с HTTP-кодом: по нему отличаем «нужно подтверждение» от отказа. */
export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const b = await r.json();
      detail = b.detail || JSON.stringify(b);
    } catch {}
    throw new ApiError(detail, r.status);
  }
  return r.json();
}

/**
 * Заливка файла через XHR, а не fetch: fetch не умеет отдавать прогресс отправки,
 * и длинный ролик заливался «вслепую», а обрыв показывался как «Failed to fetch»
 * без единой подробности.
 */
function upload<T>(url: string, fd: FormData, onProgress?: (percent: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let body: any = null;
      try { body = JSON.parse(xhr.responseText); } catch {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else reject(new ApiError(body?.detail || `Ошибка ${xhr.status}`, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError(
      "Соединение с сервером оборвалось во время загрузки. Файл не сохранён — " +
      "проверьте связь и свободное место на сервере.", 0));
    xhr.onabort = () => reject(new ApiError("Загрузка отменена", 0));
    xhr.ontimeout = () => reject(new ApiError("Сервер не ответил вовремя", 0));
    xhr.send(fd);
  });
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

async function uploadInChunks(file: File, onProgress?: (p: number) => void): Promise<Video> {
  const uploadId = Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
  const total = Math.ceil(file.size / CHUNK_SIZE);

  for (let i = 0; i < total; i++) {
    const blob = file.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
    const fd = new FormData();
    fd.append("upload_id", uploadId);
    fd.append("index", String(i));
    fd.append("file", blob, file.name);

    let lastErr: any = null;
    for (let attempt = 0; attempt < CHUNK_RETRIES; attempt++) {
      try {
        await upload<any>("/api/videos/chunk", fd, (p) =>
          onProgress?.(Math.round(((i + p / 100) / total) * 100)));
        lastErr = null;
        break;
      } catch (e: any) {
        lastErr = e;
        // Отказ по существу (нет места, неверный запрос) повторять бессмысленно
        if (e instanceof ApiError && e.status >= 400) break;
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
      }
    }
    if (lastErr) {
      fetch(`/api/videos/chunk/${uploadId}`, { method: "DELETE" }).catch(() => {});
      throw lastErr;
    }
  }

  return fetch("/api/videos/chunk/finish", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upload_id: uploadId, filename: file.name }),
  }).then((r) => j<Video>(r));
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
  createAccount: (b: { name: string; platform: Platform; proxy_url?: string | null; uniqueize?: boolean; group_id?: number | null } & Partial<AccountCredentials> & { start_login?: boolean }) =>
    fetch("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<Account>(r)),
  updateAccount: (id: number, b: Partial<{ name: string; proxy_url: string | null; active: boolean; uniqueize: boolean; uniq_profile_id: number | null; group_id: number | null } & AccountCredentials>) =>
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

  // hooks / overlays / профили уникализации
  hooks: () => fetch("/api/hooks").then((r) => j<Hook[]>(r)),
  uploadHook: (file: File, name: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    return fetch("/api/hooks", { method: "POST", body: fd }).then((r) => j<Hook>(r));
  },
  deleteHook: (id: number) => fetch(`/api/hooks/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  hookFileUrl: (id: number) => `/api/hooks/${id}/file`,

  overlayAssets: () => fetch("/api/overlays").then((r) => j<OverlayAsset[]>(r)),
  uploadOverlayAsset: (file: File, name: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    return fetch("/api/overlays", { method: "POST", body: fd }).then((r) => j<OverlayAsset>(r));
  },
  deleteOverlayAsset: (id: number) => fetch(`/api/overlays/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  overlayFileUrl: (id: number) => `/api/overlays/${id}/file`,

  ads: () => fetch("/api/ads").then((r) => j<AdClip[]>(r)),
  uploadAd: (file: File, name: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    return fetch("/api/ads", { method: "POST", body: fd }).then((r) => j<AdClip>(r));
  },
  deleteAd: (id: number) => fetch(`/api/ads/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  adFileUrl: (id: number) => `/api/ads/${id}/file`,

  backgrounds: () => fetch("/api/backgrounds").then((r) => j<Background[]>(r)),
  uploadBackground: (file: File, name: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    return fetch("/api/backgrounds", { method: "POST", body: fd }).then((r) => j<Background>(r));
  },
  deleteBackground: (id: number) => fetch(`/api/backgrounds/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  backgroundFileUrl: (id: number) => `/api/backgrounds/${id}/file`,

  /** Проверка канала: шлёт тело заданного размера и возвращает, сколько дошло.
   *  Ничего не сохраняет — нужен, чтобы найти лимит чужого прокси. */
  uploadProbe: (bytes: number) => {
    const fd = new FormData();
    fd.append("file", new Blob([new Uint8Array(bytes)]), "probe.bin");
    return upload<{ ok: boolean; received: number }>("/api/system/upload-probe", fd);
  },

  // папки библиотек
  assetFolders: (kind?: FolderKind) =>
    fetch("/api/asset-folders" + (kind ? `?kind=${kind}` : "")).then((r) => j<AssetFolder[]>(r)),
  createAssetFolder: (b: { kind: FolderKind; name: string; group_ids?: number[] }) =>
    fetch("/api/asset-folders", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b),
    }).then((r) => j<AssetFolder>(r)),
  updateAssetFolder: (id: number, b: Partial<{ name: string; group_ids: number[] }>) =>
    fetch(`/api/asset-folders/${id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b),
    }).then((r) => j<AssetFolder>(r)),
  deleteAssetFolder: (id: number) =>
    fetch(`/api/asset-folders/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  setAssetFolder: (kind: FolderKind, id: number, folderId: number | null) => {
    const base = { video: "videos", hook: "hooks", background: "backgrounds" }[kind];
    return fetch(`/api/${base}/${id}/folder`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_id: folderId }),
    }).then((r) => j<any>(r));
  },

  // группы аккаунтов
  accountGroups: () => fetch("/api/account-groups").then((r) => j<AccountGroup[]>(r)),
  createAccountGroup: (b: { name: string; color?: string | null }) =>
    fetch("/api/account-groups", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b),
    }).then((r) => j<AccountGroup>(r)),
  updateAccountGroup: (id: number, b: Partial<{ name: string; color: string | null }>) =>
    fetch(`/api/account-groups/${id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b),
    }).then((r) => j<AccountGroup>(r)),
  deleteAccountGroup: (id: number) =>
    fetch(`/api/account-groups/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),

  uniqProfiles: () => fetch("/api/uniq-profiles").then((r) => j<UniqProfile[]>(r)),
  uniqDefaults: () => fetch("/api/uniq-profiles/defaults").then((r) => j<Record<string, any>>(r)),
  createUniqProfile: (b: { name: string; params?: Record<string, any>; is_default?: boolean }) =>
    fetch("/api/uniq-profiles", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b),
    }).then((r) => j<UniqProfile>(r)),
  updateUniqProfile: (id: number, b: Partial<{ name: string; params: Record<string, any>; is_default: boolean }>) =>
    fetch(`/api/uniq-profiles/${id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b),
    }).then((r) => j<UniqProfile>(r)),
  deleteUniqProfile: (id: number) => fetch(`/api/uniq-profiles/${id}`, { method: "DELETE" }).then((r) => j<any>(r)),
  uniqPreviewUrl: (id: number, videoId: number) => `/api/uniq-profiles/${id}/preview?video_id=${videoId}`,

  // videos
  videos: () => fetch("/api/videos").then((r) => j<Video[]>(r)),
  uploadVideo: (file: File, onProgress?: (percent: number) => void) => {
    if (file.size <= CHUNK_THRESHOLD) {
      const fd = new FormData();
      fd.append("file", file);
      return upload<Video>("/api/videos", fd, onProgress);
    }
    return uploadInChunks(file, onProgress);
  },
  /** force=true удаляет ролик вместе с его задачами (панель сначала спрашивает). */
  deleteVideo: (id: number, force = false) =>
    fetch(`/api/videos/${id}${force ? "?force=true" : ""}`, { method: "DELETE" }).then((r) => j<any>(r)),
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

  /** Длинное видео → серия частей на каждый аккаунт */
  createJobsParts: (b: {
    account_ids: number[];
    video_id: number;
    parts: number;
    caption?: string;
    caption_template?: string;
    label_on?: boolean;
    banner_id?: number | null;
    scheduled_at?: string | null;
    uniq_profile_id?: number | null;
    part_gap_min_minutes?: number;
    part_gap_max_minutes?: number;
    spread_min_minutes?: number;
    spread_max_minutes?: number;
  }) =>
    fetch("/api/jobs/parts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then((r) => j<{ jobs: Job[]; skipped: string[] }>(r)),

  /** Одно видео на несколько аккаунтов: у каждого свой рендер и свой хеш */
  createJobsBulk: (b: {
    account_ids: number[];
    video_id: number;
    banner_id?: number | null;
    caption?: string;
    scheduled_at?: string | null;
    overlays?: Overlay[] | null;
    uniq_profile_id?: number | null;
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
