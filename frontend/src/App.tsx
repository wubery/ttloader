import { useEffect, useRef, useState, useCallback, createContext, useContext, useMemo } from "react";
import {
  api, Account, AccountGroup, AssetFolder, AutoLoginState, Banner, Job, LoginStage, MailConnect,
  MailConnectState,
  MailMessage, Platform, SettingsData, SystemVersion, UniqProfile, Video,
} from "./api";
import { BannerEditor } from "./BannerEditor";
import { FolderPicker, FolderTabs, FoldersCard, visibleToGroup } from "./Folders";
import { Uniqueizer } from "./Uniqueizer";

/* ================================================================
   Theme Context
   ================================================================ */
const ThemeCtx = createContext<{ dark: boolean; toggle: () => void }>({ dark: true, toggle: () => {} });

function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [dark, setDark] = useState(() => localStorage.getItem("vp-theme") !== "light");
  const toggle = useCallback(() => {
    setDark((d) => { const next = !d; localStorage.setItem("vp-theme", next ? "dark" : "light"); return next; });
  }, []);
  useEffect(() => {
    document.documentElement.setAttribute("data-bs-theme", dark ? "dark" : "light");
    document.documentElement.classList.toggle("theme-light", !dark);
  }, [dark]);
  return <ThemeCtx.Provider value={{ dark, toggle }}>{children}</ThemeCtx.Provider>;
}

/* ================================================================
   Search Context
   ================================================================ */
const SearchCtx = createContext<{ query: string; set: (q: string) => void }>({ query: "", set: () => {} });

/* ================================================================
   Toast Context
   ================================================================ */
type ToastType = "success" | "error" | "warning" | "info";
interface Toast { id: number; type: ToastType; text: string; }

const ToastCtx = createContext<{ add: (type: ToastType, text: string) => void }>({ add: () => {} });

function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const add = useCallback((type: ToastType, text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, type, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={{ add }}>
      {children}
      <div className="vp-toast">
        {toasts.map((t) => (
          <div key={t.id} className={`vp-toast-item ${t.type}`}>
            <i className={`bi ${t.type === "success" ? "bi-check-circle-fill text-success" : t.type === "error" ? "bi-x-circle-fill text-danger" : t.type === "warning" ? "bi-exclamation-triangle-fill text-warning" : "bi-info-circle-fill text-accent"}`} />
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

function useToast() { return useContext(ToastCtx); }

/* ================================================================
   Confirm Context (delete confirmation)
   ================================================================ */
interface ConfirmState { open: boolean; title: string; message: string; onConfirm: () => void; }
const ConfirmCtx = createContext<{ confirm: (title: string, message: string) => Promise<boolean> }>({ confirm: () => Promise.resolve(false) });

function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ConfirmState>({ open: false, title: "", message: "", onConfirm: () => {} });
  const resolverRef = useRef<(v: boolean) => void>(() => {});

  function confirm(title: string, message: string): Promise<boolean> {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setState({ open: true, title, message, onConfirm: () => {} });
    });
  }

  function handleConfirm() { setState((s) => ({ ...s, open: false })); resolverRef.current(true); }
  function handleCancel() { setState((s) => ({ ...s, open: false })); resolverRef.current(false); }

  return (
    <ConfirmCtx.Provider value={{ confirm }}>
      {children}
      {state.open && (
        <div className="modal d-block" tabIndex={-1} style={{ background: "rgba(0,0,0,0.6)" }}>
          <div className="modal-dialog modal-dialog-centered" style={{ maxWidth: 400 }}>
            <div className="modal-content vp">
              <div className="modal-header vp">
                <h6 className="modal-title"><i className="bi bi-exclamation-triangle text-warning me-2" />{state.title}</h6>
              </div>
              <div className="modal-body vp">
                <p className="mb-0">{state.message}</p>
              </div>
              <div className="modal-footer vp">
                <button className="btn btn-vp-outline btn-sm" onClick={handleCancel}>Отмена</button>
                <button className="btn btn-vp-danger btn-sm" onClick={handleConfirm}>Удалить</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </ConfirmCtx.Provider>
  );
}

function useConfirm() { return useContext(ConfirmCtx); }

/* ================================================================
   Tab type
   ================================================================ */
type Tab = "jobs" | "post" | "editor" | "accounts" | "videos" | "banners" | "uniq" | "proxy" | "stats" | "settings";

const NAV_ITEMS: { tab: Tab; icon: string; label: string }[] = [
  { tab: "jobs", icon: "bi-clipboard2-data", label: "Очередь" },
  { tab: "post", icon: "bi-plus-circle", label: "Новый пост" },
  { tab: "editor", icon: "bi-film", label: "Редактор" },
  { tab: "accounts", icon: "bi-people", label: "Аккаунты" },
  { tab: "videos", icon: "bi-play-circle", label: "Видео" },
  { tab: "banners", icon: "bi-image", label: "Баннеры" },
  { tab: "uniq", icon: "bi-shuffle", label: "Уникализация" },
  { tab: "proxy", icon: "bi-shield-check", label: "Прокси" },
  { tab: "stats", icon: "bi-bar-chart-line", label: "Статистика" },
  { tab: "settings", icon: "bi-gear", label: "Настройки" },
];

const TAB_LABELS: Record<Tab, string> = {
  jobs: "Очередь", post: "Новый пост", editor: "Редактор", accounts: "Аккаунты",
  videos: "Видео", banners: "Баннеры", uniq: "Уникализация",
  proxy: "Прокси", stats: "Статистика", settings: "Настройки",
};

/* ================================================================
   App root
   ================================================================ */
export function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => { api.authMe().then((m) => setAuthed(m.authenticated)).catch(() => setAuthed(false)); }, []);
  if (authed === null) return <div className="d-flex align-items-center justify-content-center vh-100"><div className="spinner-border text-primary" /></div>;
  if (!authed) return <ThemeProvider><LoginPage onLogin={() => setAuthed(true)} /></ThemeProvider>;
  return <ThemeProvider><ToastProvider><ConfirmProvider><Dashboard onLogout={() => setAuthed(false)} /></ConfirmProvider></ToastProvider></ThemeProvider>;
}

/* ================================================================
   Login Page
   ================================================================ */
function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [mode, setMode] = useState<"password" | "telegram">("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [tgStep, setTgStep] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function doLogin() {
    setBusy(true); setErr(null);
    try { await api.login(username, password); onLogin(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function tgRequest() {
    setBusy(true); setErr(null);
    try { await api.tgLoginRequest(); setTgStep(true); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function tgVerify() {
    if (code.length !== 6) return;
    setBusy(true); setErr(null);
    try { await api.tgLoginVerify(code); onLogin(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <h1><i className="bi bi-camera-reels me-2" />Video Poster</h1>
          <p>Панель управления публикациями</p>
        </div>

        {err && <div className="alert alert-danger py-2 mb-3" style={{ fontSize: 13 }}>{err}</div>}

        <div className="login-tabs">
          <button className={`login-tab ${mode === "password" ? "active" : ""}`} onClick={() => { setMode("password"); setErr(null); }}>
            <i className="bi bi-key me-1" /> Пароль
          </button>
          <button className={`login-tab ${mode === "telegram" ? "active" : ""}`} onClick={() => { setMode("telegram"); setErr(null); setTgStep(false); }}>
            <i className="bi bi-telegram me-1" /> Telegram
          </button>
        </div>

        {mode === "password" ? (
          <div className="d-flex flex-column gap-3">
            <div>
              <label className="form-label vp">Логин</label>
              <input className="form-control vp" placeholder="admin" value={username} onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div>
              <label className="form-label vp">Пароль</label>
              <input className="form-control vp" type="password" placeholder="Введите пароль" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doLogin()} />
            </div>
            <button className="btn btn-vp w-100" disabled={busy || !username || !password} onClick={doLogin}>
              {busy ? <><span className="spinner-border spinner-border-sm me-2" />Вхожу...</> : <><i className="bi bi-box-arrow-in-right me-1" />Войти</>}
            </button>
          </div>
        ) : (
          <div className="d-flex flex-column gap-3">
            {!tgStep ? (
              <>
                <p className="fs-sm text-muted mb-0">Код для входа будет отправлен в Telegram бот</p>
                <button className="btn btn-vp w-100" disabled={busy} onClick={tgRequest}>
                  {busy ? <><span className="spinner-border spinner-border-sm me-2" />Отправляю...</> : <><i className="bi bi-telegram me-1" />Получить код в Telegram</>}
                </button>
              </>
            ) : (
              <>
                <p className="fs-sm text-muted mb-0">Код отправлен в Telegram. Введите 6-значный код:</p>
                <input className="form-control vp text-center" style={{ fontSize: 24, letterSpacing: 8, fontWeight: 700 }}
                  placeholder="000000" maxLength={6} value={code} onChange={(e) => { setCode(e.target.value.replace(/\D/g, "").slice(0, 6)); }}
                  onKeyDown={(e) => e.key === "Enter" && tgVerify()} autoFocus />
                <button className="btn btn-vp w-100" disabled={busy || code.length !== 6} onClick={tgVerify}>
                  {busy ? <><span className="spinner-border spinner-border-sm me-2" />Проверяю...</> : <><i className="bi bi-check-circle me-1" />Подтвердить</>}
                </button>
                <button className="btn btn-vp-outline w-100" onClick={() => { setTgStep(false); setCode(""); }}>Назад</button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ================================================================
   Dashboard
   ================================================================ */
function Dashboard({ onLogout }: { onLogout: () => void }) {
  const [tab, setTab] = useState<Tab>("jobs");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [videos, setVideos] = useState<Video[]>([]);
  const [banners, setBanners] = useState<Banner[]>([]);
  const [profiles, setProfiles] = useState<UniqProfile[]>([]);
  const [groups, setGroups] = useState<AccountGroup[]>([]);
  const [videoFolders, setVideoFolders] = useState<AssetFolder[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Свёрнутое боковое меню (только иконки) — состояние помним между сессиями
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vp_sidebar_collapsed") === "1");
  const [search, setSearch] = useState("");
  const toast = useToast();
  const { dark, toggle: toggleTheme } = useContext(ThemeCtx);

  useEffect(() => {
    localStorage.setItem("vp_sidebar_collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  async function refreshAll() {
    try {
      const [a, v, b, j, pr, gr, vf] = await Promise.all([
        api.accounts(), api.videos(), api.banners(), api.jobs(), api.uniqProfiles(),
        api.accountGroups(), api.assetFolders("video"),
      ]);
      setAccounts(a); setVideos(v); setBanners(b); setJobs(j); setProfiles(pr); setGroups(gr);
      setVideoFolders(vf);
    } catch (e: any) { toast.add("error", e.message); }
  }

  useEffect(() => {
    refreshAll();
    api.health().then(setHealth).catch(() => {});
    const t = setInterval(() => api.jobs().then(setJobs).catch(() => {}), 4000);
    return () => clearInterval(t);
  }, []);

  async function logout() {
    try { await api.logout(); } catch {}
    onLogout();
  }

  const failedJobs = jobs.filter((j) => j.status === "failed").length;

  return (
    <>
      {/* Sidebar overlay for mobile */}
      <div className={`vp-sidebar-overlay ${sidebarOpen ? "open" : ""}`} onClick={() => setSidebarOpen(false)} />

      {/* Sidebar */}
      <aside className={`vp-sidebar ${sidebarOpen ? "open" : ""} ${collapsed ? "collapsed" : ""}`}>
        <div className="vp-sidebar-brand">
          <h2><i className="bi bi-camera-reels" /><span className="vp-brand-text">Video Poster</span></h2>
          <small className="vp-brand-text">Панель управления</small>
        </div>
        <nav className="vp-sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button key={item.tab} className={`vp-nav-item ${tab === item.tab ? "active" : ""}`}
              title={collapsed ? item.label : undefined}
              onClick={() => { setTab(item.tab); setSidebarOpen(false); }}>
              <i className={`bi ${item.icon}`} />
              <span className="vp-nav-label">{item.label}</span>
              {item.tab === "jobs" && failedJobs > 0 && <span className="vp-nav-badge">{failedJobs}</span>}
            </button>
          ))}
        </nav>
        <div className="vp-sidebar-footer">
          {/* Свернуть/развернуть меню (десктоп) */}
          <button className="vp-nav-item w-100 d-none d-lg-flex" onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? "Развернуть меню" : "Свернуть меню"}>
            <i className={`bi ${collapsed ? "bi-chevron-double-right" : "bi-chevron-double-left"}`} />
            <span className="vp-nav-label">Свернуть</span>
          </button>
          <button className="vp-nav-item w-100" onClick={logout} title={collapsed ? "Выйти" : undefined}>
            <i className="bi bi-box-arrow-left" />
            <span className="vp-nav-label">Выйти</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className={`vp-main ${collapsed ? "collapsed" : ""}`}>
        <header className="vp-topbar">
          <div className="d-flex align-items-center gap-3">
            <button className="vp-sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)}>
              <i className="bi bi-list" />
            </button>
            <span className="vp-topbar-title">{TAB_LABELS[tab]}</span>
          </div>
          <div className="d-flex align-items-center gap-3">
            {/* Search */}
            <div className="position-relative" style={{ width: 240 }}>
              <i className="bi bi-search position-absolute" style={{ left: 10, top: "50%", transform: "translateY(-50%)", fontSize: 13, color: "var(--vp-muted)" }} />
              <input className="form-control vp form-control-sm" style={{ paddingLeft: 32 }}
                placeholder="Поиск..." value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            {/* Theme toggle */}
            <button className="btn btn-vp-outline btn-sm" onClick={toggleTheme} title={dark ? "Светлая тема" : "Тёмная тема"}>
              <i className={`bi ${dark ? "bi-sun" : "bi-moon"}`} />
            </button>
            {/* Health */}
            {health && (
              <div className="d-flex align-items-center gap-2 fs-sm d-none d-md-flex">
                <span className={`status-dot ${health.ffmpeg && health.playwright ? "ok" : "fail"}`} />
                <span className="text-muted">{health.ffmpeg ? "ffmpeg" : ""}{health.ffmpeg && health.playwright ? " + " : ""}{health.playwright ? "Playwright" : ""}</span>
              </div>
            )}
          </div>
        </header>

        {/* Warnings */}
        {health && (!health.ffmpeg || !health.playwright) && (
          <div className="alert alert-warning py-2 mx-4 mt-3 mb-0" style={{ fontSize: 13 }}>
            {!health.ffmpeg && <div><i className="bi bi-exclamation-triangle me-1" />ffmpeg недоступен — наложение баннера не будет работать.</div>}
            {!health.playwright && <div><i className="bi bi-exclamation-triangle me-1" />Playwright не установлен — постинг не будет работать.</div>}
          </div>
        )}

        {/* key={tab} перезапускает анимацию появления при смене вкладки */}
        <div className="vp-content vp-tab-enter" key={tab}>
          <SearchCtx.Provider value={{ query: search, set: setSearch }}>
            {tab === "jobs" && <Jobs jobs={jobs} accounts={accounts} videos={videos} onChange={refreshAll} />}
            {tab === "post" && <PostForm accounts={accounts} videos={videos} banners={banners} profiles={profiles} groups={groups} videoFolders={videoFolders} onCreated={() => { refreshAll(); setTab("jobs"); }} />}
            {tab === "editor" && <BannerEditor videos={videos} banners={banners} accounts={accounts} groups={groups}
              onSaved={refreshAll} onPosted={() => { refreshAll(); setTab("jobs"); }} />}
            {tab === "accounts" && <Accounts accounts={accounts} profiles={profiles} groups={groups} onChange={refreshAll} />}
            {tab === "videos" && <Videos videos={videos} folders={videoFolders} groups={groups} onChange={refreshAll} />}
            {tab === "banners" && <Banners banners={banners} onChange={refreshAll} />}
            {tab === "uniq" && <Uniqueizer videos={videos} onChange={refreshAll} />}
            {tab === "proxy" && <ProxyManager accounts={accounts} onChange={refreshAll} />}
            {tab === "stats" && <Stats jobs={jobs} accounts={accounts} videos={videos} groups={groups} />}
            {tab === "settings" && <Settings />}
          </SearchCtx.Provider>
        </div>
      </div>
    </>
  );
}

/* ================================================================
   Группы аккаунтов — когорты для проверки гипотез постинга
   ================================================================ */
// Палитра фиксированная, а не свободный color-picker: бейджи должны оставаться
// читаемыми и в светлой, и в тёмной теме.
const GROUP_COLORS = ["#22c55e", "#3b82f6", "#f59e0b", "#ef4444", "#a855f7", "#14b8a6"];
const GROUP_FALLBACK = "#9b8cf5";   // как у badge-vp-info, если цвет не выбран

/** Бейдж группы: фон — цвет с прозрачностью, текст — он же насыщенный. */
function GroupBadge({ group, className = "" }: { group?: AccountGroup; className?: string }) {
  if (!group) return null;
  const c = group.color || GROUP_FALLBACK;
  return (
    <span className={`badge-vp ${className}`} style={{ background: `${c}26`, color: c }}
          title={`Группа: ${group.name}`}>
      <i className="bi bi-collection" /> {group.name}
    </span>
  );
}

/** Ряд свотчей палитры. */
function ColorSwatches({ value, onPick }: { value: string | null; onPick: (c: string) => void }) {
  return (
    <div className="d-flex align-items-center gap-1">
      {GROUP_COLORS.map((c) => (
        <button key={c} type="button" title={c} onClick={() => onPick(c)}
                style={{
                  width: 20, height: 20, borderRadius: 6, background: c, cursor: "pointer",
                  border: value === c ? "2px solid var(--vp-text)" : "1px solid var(--vp-border)",
                }} />
      ))}
    </div>
  );
}

/** Справочник групп: создание, переименование, цвет, удаление. */
function GroupsCard({ groups, onChange }: { groups: AccountGroup[]; onChange: () => void }) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(GROUP_COLORS[0]);
  const toast = useToast();
  const { confirm } = useConfirm();

  async function create() {
    try {
      await api.createAccountGroup({ name, color });
      setName("");
      onChange();
      toast.add("success", "Группа создана");
    } catch (e: any) { toast.add("error", e.message); }
  }
  async function patch(g: AccountGroup, body: Partial<{ name: string; color: string | null }>) {
    try { await api.updateAccountGroup(g.id, body); onChange(); }
    catch (e: any) { toast.add("error", e.message); onChange(); }   // откатываем поле к серверному
  }
  async function remove(g: AccountGroup) {
    const ok = await confirm("Удалить группу?",
      `«${g.name}» — аккаунты не удалятся, они просто потеряют группу.`);
    if (!ok) return;
    try { await api.deleteAccountGroup(g.id); onChange(); toast.add("info", "Группа удалена"); }
    catch (e: any) { toast.add("error", e.message); }
  }

  return (
    <div className="vp-card">
      <div className="vp-card-header">
        <h3><i className="bi bi-collection me-2 text-accent" />Группы аккаунтов</h3>
      </div>
      <div className="d-flex align-items-center gap-2 flex-wrap">
        <input className="form-control vp form-control-sm" style={{ maxWidth: 240 }}
               placeholder="Название группы" value={name}
               onChange={(e) => setName(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) create(); }} />
        <ColorSwatches value={color} onPick={setColor} />
        <button className="btn btn-vp btn-sm" disabled={!name.trim()} onClick={create}>
          <i className="bi bi-plus-lg me-1" />Создать
        </button>
      </div>

      {groups.length > 0 && (
        <div className="d-flex flex-column gap-2 mt-3">
          {groups.map((g) => (
            <div className="d-flex align-items-center gap-2 flex-wrap" key={g.id}>
              <input className="form-control vp form-control-sm" style={{ maxWidth: 240 }}
                     defaultValue={g.name} key={`${g.id}-${g.name}`}
                     onBlur={(e) => {
                       const v = e.target.value.trim();
                       if (v && v !== g.name) patch(g, { name: v });
                     }} />
              <ColorSwatches value={g.color} onPick={(c) => patch(g, { color: c })} />
              <span className="badge-vp badge-vp-muted">{g.accounts_count} акк.</span>
              <button className="btn btn-vp-danger btn-sm" onClick={() => remove(g)}>
                <i className="bi bi-trash" />
              </button>
            </div>
          ))}
        </div>
      )}
      <p className="fs-sm text-muted mt-2 mb-0">
        Группа — это когорта для проверки гипотез: в форме поста её аккаунты выбираются одним
        движением, а на вкладке «Статистика» видно результат по каждой группе. На рендер и
        уникализацию группа не влияет.
      </p>
    </div>
  );
}

/* ================================================================
   Accounts
   ================================================================ */
function Accounts({ accounts, profiles, groups, onChange }: {
  accounts: Account[]; profiles: UniqProfile[]; groups: AccountGroup[]; onChange: () => void;
}) {
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [proxy, setProxy] = useState("");
  const [ttLogin, setTtLogin] = useState("");
  const [ttPass, setTtPass] = useState("");
  const [mailAddr, setMailAddr] = useState("");
  const [mailPass, setMailPass] = useState("");
  const [newGroup, setNewGroup] = useState<number | null>(null);
  const [startLogin, setStartLogin] = useState(true);
  const [login, setLogin] = useState<{ id: number; name: string } | null>(null);
  const [mailFor, setMailFor] = useState<Account | null>(null);
  const [connectFor, setConnectFor] = useState<Account | null>(null);
  const [showCount, setShowCount] = useState(20);
  const toast = useToast();
  const { confirm } = useConfirm();
  const { query } = useContext(SearchCtx);

  const byId = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups]);
  const filtered = useMemo(() => {
    if (!query) return accounts;
    const q = query.toLowerCase();
    return accounts.filter((a) => a.name.toLowerCase().includes(q) || a.platform.includes(q)
      || (a.proxy_url || "").toLowerCase().includes(q)
      || (a.group_id ? byId.get(a.group_id)?.name.toLowerCase().includes(q) ?? false : false));
  }, [accounts, query, byId]);
  const visible = filtered.slice(0, showCount);

  async function create() {
    try {
      const acc = await api.createAccount({
        name, platform, proxy_url: proxy || null, group_id: newGroup,
        tt_login: ttLogin || null, tt_password: ttPass || null,
        mail_address: mailAddr || null, mail_password: mailPass || null,
        start_login: startLogin,
      });
      setName(""); setProxy(""); setTtLogin(""); setTtPass(""); setMailAddr(""); setMailPass("");
      onChange();
      if (startLogin && acc.has_tt_credentials) {
        setLogin({ id: acc.id, name: acc.name });   // сразу показываем ход входа
        toast.add("success", "Аккаунт создан — вхожу в него");
      } else {
        toast.add("success", "Аккаунт создан");
      }
    } catch (e: any) { toast.add("error", e.message); }
  }
  async function relogin(a: Account) {
    try {
      await api.loginAuto(a.id);
      setLogin({ id: a.id, name: a.name });
    } catch (e: any) { toast.add("error", e.message); }
  }
  async function onCookies(id: number, f: File | null) {
    if (!f) return;
    try { await api.uploadCookies(id, f); onChange(); toast.add("success", "Куки загружены"); } catch (e: any) { toast.add("error", e.message); }
  }

  return (
    <div>
      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-plus-circle me-2 text-accent" />Новый аккаунт</h3>
        </div>
        <div className="row g-2 align-items-end">
          <div className="col-md-3">
            <label className="form-label vp">Название</label>
            <input className="form-control vp" placeholder="Мой TikTok" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="col-md-2">
            <label className="form-label vp">Платформа</label>
            <select className="form-select vp" value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
              <option value="tiktok">TikTok</option>
              <option value="youtube">YouTube Shorts</option>
            </select>
          </div>
          <div className="col-md-3">
            <label className="form-label vp">Прокси</label>
            <input className="form-control vp" placeholder="http://user:pass@host:port" value={proxy} onChange={(e) => setProxy(e.target.value)} />
          </div>
          <div className="col-md-2">
            <label className="form-label vp">Группа</label>
            <select className="form-select vp" value={newGroup ?? ""}
                    onChange={(e) => setNewGroup(Number(e.target.value) || null)}>
              <option value="">— без группы —</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </div>
          <div className="col-md-2">
            <button className="btn btn-vp w-100" onClick={create} disabled={!name}>Создать</button>
          </div>
        </div>

        {/* Данные для автоматического входа: панель сама залогинится и достанет код из письма */}
        <div className="row g-2 align-items-end mt-1">
          <div className="col-md-3">
            <label className="form-label vp">Логин {platform === "tiktok" ? "TikTok" : "аккаунта"}</label>
            <input className="form-control vp" placeholder="почта или username" value={ttLogin} onChange={(e) => setTtLogin(e.target.value)} />
          </div>
          <div className="col-md-2">
            <label className="form-label vp">Пароль</label>
            <input className="form-control vp" type="password" value={ttPass} onChange={(e) => setTtPass(e.target.value)} />
          </div>
          <div className="col-md-3">
            <label className="form-label vp">Почта аккаунта</label>
            <input className="form-control vp" placeholder="name@outlook.com" value={mailAddr} onChange={(e) => setMailAddr(e.target.value)} />
          </div>
          <div className="col-md-2">
            <label className="form-label vp">Пароль почты</label>
            <input className="form-control vp" type="password" value={mailPass} onChange={(e) => setMailPass(e.target.value)} />
          </div>
          <div className="col-md-2">
            <label className="d-flex align-items-center gap-1 fs-sm text-muted mb-2" style={{ cursor: "pointer" }}>
              <input type="checkbox" className="form-check-input" checked={startLogin} onChange={(e) => setStartLogin(e.target.checked)} />
              войти сразу
            </label>
          </div>
        </div>
        <p className="fs-sm text-muted mt-2 mb-0">
          Каждый аккаунт — свой прокси. С логином и паролем панель входит сама; код из письма
          она достанет тоже сама, если подключить почту (кнопка у профиля). Пароли хранятся
          зашифрованными и наружу не отдаются.
        </p>
      </div>

      <GroupsCard groups={groups} onChange={onChange} />

      <div className="d-flex flex-column gap-2">
        {visible.map((a) => (
          <div className="vp-card" key={a.id}>
            <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
              <div className="d-flex align-items-center gap-2 flex-wrap">
                <i className={`bi ${a.platform === "tiktok" ? "bi-tiktok" : "bi-youtube"} fs-5`} />
                <b>{a.name}</b>
                <span className="badge-vp badge-vp-info">{a.platform}</span>
                {a.group_id != null && <GroupBadge group={byId.get(a.group_id)} />}
                {a.has_cookies ? <span className="badge-vp badge-vp-success"><i className="bi bi-check-circle" /> куки</span> : <span className="badge-vp badge-vp-danger"><i className="bi bi-x-circle" /> нет кук</span>}
                {a.proxy_url ? <span className="badge-vp badge-vp-muted"><i className="bi bi-shield" /> прокси</span> : <span className="badge-vp badge-vp-danger">без прокси</span>}
                {a.proxy_url && a.proxy_ok === true && <span className="badge-vp badge-vp-success">IP {a.proxy_ip}</span>}
                {a.proxy_url && a.proxy_ok === false && <span className="badge-vp badge-vp-danger"><i className="bi bi-x-circle" /> прокси down</span>}
                {a.has_tt_credentials && <span className="badge-vp badge-vp-muted"><i className="bi bi-key" /> автовход</span>}
                {a.mail_address && (a.mail_connected
                  ? <span className="badge-vp badge-vp-success"><i className="bi bi-envelope-check" /> почта</span>
                  : <span className="badge-vp badge-vp-warning"><i className="bi bi-envelope-exclamation" /> почта не подключена</span>)}
              </div>
              <button className="btn btn-vp-danger btn-sm" onClick={async () => { if (await confirm("Удалить аккаунт?", `Вы уверены что хотите удалить «${a.name}»?`)) { api.deleteAccount(a.id).then(() => { onChange(); toast.add("info", "Аккаунт удалён"); }); } }}>
                <i className="bi bi-trash" />
              </button>
            </div>
            {a.login_error && <div className="fs-sm text-danger mt-1"><i className="bi bi-exclamation-triangle me-1" />{a.login_error}</div>}
            <div className="d-flex align-items-center gap-2 mt-2 flex-wrap">
              {a.has_tt_credentials ? (
                <button className="btn btn-vp btn-sm" onClick={() => relogin(a)}>
                  <i className="bi bi-box-arrow-in-right me-1" />Войти заново
                </button>
              ) : (
                <button className="btn btn-vp btn-sm" onClick={() => setLogin({ id: a.id, name: a.name })}>
                  <i className="bi bi-box-arrow-in-right me-1" />Войти
                </button>
              )}
              {a.mail_address && (a.mail_connected ? (
                <button className="btn btn-vp-outline btn-sm" onClick={() => setMailFor(a)}>
                  <i className="bi bi-envelope me-1" />Почта
                </button>
              ) : (
                <button className="btn btn-vp-outline btn-sm" onClick={() => setConnectFor(a)}>
                  <i className="bi bi-envelope-plus me-1" />Подключить почту
                </button>
              ))}
              <label className="btn btn-vp-outline btn-sm mb-0">
                <i className="bi bi-upload me-1" />Куки (JSON)
                <input type="file" accept="application/json,.json" hidden onChange={(e) => onCookies(a.id, e.target.files?.[0] ?? null)} />
              </label>
              <label className="d-flex align-items-center gap-1 fs-sm text-muted" style={{ cursor: "pointer" }}>
                <input type="checkbox" className="form-check-input" checked={a.uniqueize}
                  onChange={(e) => api.updateAccount(a.id, { uniqueize: e.target.checked }).then(onChange).catch((x) => toast.add("error", x.message))} />
                уникализация
              </label>
              <select className="form-select vp form-select-sm" style={{ maxWidth: 210 }}
                      title="Профиль уникализации" value={a.uniq_profile_id ?? ""}
                      onChange={(e) => api.updateAccount(a.id, { uniq_profile_id: Number(e.target.value) || null })
                        .then(onChange).catch((x) => toast.add("error", x.message))}>
                <option value="">профиль: не задан</option>
                {profiles.map((p) => <option key={p.id} value={p.id}>профиль: {p.name}</option>)}
              </select>
              <select className="form-select vp form-select-sm" style={{ maxWidth: 190 }}
                      title="Группа аккаунта" value={a.group_id ?? ""}
                      onChange={(e) => api.updateAccount(a.id, { group_id: Number(e.target.value) || null })
                        .then(onChange).catch((x) => toast.add("error", x.message))}>
                <option value="">группа: не задана</option>
                {groups.map((g) => <option key={g.id} value={g.id}>группа: {g.name}</option>)}
              </select>
              <ProxyEditor a={a} onChange={onChange} />
            </div>
          </div>
        ))}
        {filtered.length > showCount && (
          <button className="btn btn-vp-outline w-100" onClick={() => setShowCount((c) => c + 20)}>
            Показать ещё ({filtered.length - showCount})
          </button>
        )}
        {filtered.length === 0 && query && <div className="vp-card text-center text-muted py-4">Ничего не найдено по запросу «{query}»</div>}
      </div>

      {login && (() => {
        const acc = accounts.find((x) => x.id === login.id);
        return acc?.has_tt_credentials
          ? <AutoLoginModal account={login} onDone={() => { setLogin(null); onChange(); toast.add("success", "Вход выполнен"); }} onClose={() => { setLogin(null); onChange(); }} />
          : <LoginModal login={login} onDone={() => { setLogin(null); onChange(); toast.add("success", "Вход выполнен"); }} onClose={() => setLogin(null)} />;
      })()}
      {mailFor && <MailModal account={mailFor} onClose={() => setMailFor(null)} />}
      {connectFor && <MailConnectModal account={connectFor} onClose={() => { setConnectFor(null); onChange(); }} />}
    </div>
  );
}

/* ================================================================
   Автоматический вход: панель сама вводит логин, пароль и код из письма.
   Человек нужен только при капче или если письмо не пришло.
   ================================================================ */
const AUTO_STAGES: Record<string, { label: string; icon: string }> = {
  idle: { label: "Ожидание", icon: "bi-hourglass" },
  starting: { label: "Готовлю браузер", icon: "bi-hourglass-split" },
  filling: { label: "Ввожу логин и пароль", icon: "bi-keyboard" },
  waiting_code: { label: "Жду письмо с кодом", icon: "bi-envelope" },
  submitting_code: { label: "Ввожу код", icon: "bi-123" },
  done: { label: "Готово", icon: "bi-check-circle" },
  captcha: { label: "Капча", icon: "bi-shield-exclamation" },
  error: { label: "Ошибка", icon: "bi-x-circle" },
};

function AutoLoginModal({ account, onDone, onClose }: { account: { id: number; name: string }; onDone: () => void; onClose: () => void }) {
  const [state, setState] = useState<AutoLoginState | null>(null);
  const [code, setCode] = useState("");
  const [manual, setManual] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const doneRef = useRef(false);

  useEffect(() => {
    const load = () =>
      api.loginState(account.id).then((s) => {
        setState(s);
        if (s.stage === "done" && !doneRef.current) { doneRef.current = true; onDone(); }
      }).catch(() => {});
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [account.id]);

  async function sendCode() {
    setBusy(true);
    try { await api.loginCode(account.id, code); setCode(""); toast.add("info", "Код передан"); }
    catch (e: any) { toast.add("error", e.message); }
    finally { setBusy(false); }
  }
  async function pullCode() {
    setBusy(true);
    try {
      const r = await api.mailCode(account.id);
      if (r.code) { setCode(r.code); toast.add("success", `Код из письма: ${r.code}`); }
      else toast.add("warning", r.message || "Код не найден");
    } catch (e: any) { toast.add("error", e.message); }
    finally { setBusy(false); }
  }

  const stage = state?.stage ?? "idle";
  const info = AUTO_STAGES[stage] ?? AUTO_STAGES.idle;
  const running = ["starting", "filling", "waiting_code", "submitting_code"].includes(stage);

  return (
    <div className="modal d-block" tabIndex={-1} style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="modal-dialog modal-dialog-centered" style={{ maxWidth: 520 }}>
        <div className="modal-content vp">
          <div className="modal-header vp">
            <h6 className="modal-title"><i className="bi bi-magic me-2" />Вход: {account.name}</h6>
            <button className="btn-close btn-close-white" onClick={onClose} />
          </div>
          <div className="modal-body vp">
            <div className="d-flex align-items-center gap-2 mb-2">
              {running ? <span className="spinner-border spinner-border-sm" /> : <i className={`bi ${info.icon} fs-5`} />}
              <b>{info.label}</b>
            </div>
            {state?.message && <p className="fs-sm text-muted">{state.message}</p>}

            {stage === "captcha" && state?.screenshot && (
              <img className="img-fluid rounded" src={state.screenshot} alt="captcha"
                   style={{ border: "1px solid var(--vp-border)" }} />
            )}

            {(stage === "waiting_code" || manual) && (
              <div className="mt-3">
                <label className="form-label vp">Код из письма</label>
                <div className="d-flex gap-2">
                  <input className="form-control vp" value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" />
                  <button className="btn btn-vp-outline btn-sm" onClick={pullCode} disabled={busy} title="Взять код из почты">
                    <i className="bi bi-envelope-arrow-down" />
                  </button>
                  <button className="btn btn-vp btn-sm" onClick={sendCode} disabled={busy || !code}>ОК</button>
                </div>
                <div className="form-text fs-sm">Панель ищет код сама; вводите вручную, только если письмо не подхватилось.</div>
              </div>
            )}

            {!manual && stage !== "waiting_code" && running && (
              <button className="btn btn-link btn-sm p-0 fs-sm" onClick={() => setManual(true)}>ввести код вручную</button>
            )}

            {stage === "error" && (
              <button className="btn btn-vp btn-sm mt-2" onClick={() => api.loginAuto(account.id).catch((e) => toast.add("error", e.message))}>
                <i className="bi bi-arrow-clockwise me-1" />Попробовать снова
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
   Почта аккаунта: список писем и подключение ящика Microsoft.
   ================================================================ */
function MailModal({ account, onClose }: { account: Account; onClose: () => void }) {
  const [items, setItems] = useState<MailMessage[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const load = useCallback(() => {
    setBusy(true);
    api.mailList(account.id).then(setItems)
      .catch((e) => toast.add("error", e.message))
      .finally(() => setBusy(false));
  }, [account.id]);
  useEffect(load, [load]);

  async function show(id: string) {
    if (open === id) { setOpen(null); return; }
    setOpen(id); setBody("загружаю…");
    try { setBody((await api.mailBody(account.id, id)).body || "(пусто)"); }
    catch (e: any) { setBody(`Ошибка: ${e.message}`); }
  }

  return (
    <div className="modal d-block" tabIndex={-1} style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="modal-dialog modal-dialog-centered modal-lg">
        <div className="modal-content vp">
          <div className="modal-header vp">
            <h6 className="modal-title"><i className="bi bi-envelope me-2" />{account.mail_address}</h6>
            <button className="btn-close btn-close-white" onClick={onClose} />
          </div>
          <div className="modal-body vp" style={{ maxHeight: "70vh", overflowY: "auto" }}>
            <div className="d-flex gap-2 mb-2">
              <button className="btn btn-vp-outline btn-sm" onClick={load} disabled={busy}>
                {busy ? <span className="spinner-border spinner-border-sm me-1" /> : <i className="bi bi-arrow-clockwise me-1" />}Обновить
              </button>
              <button className="btn btn-vp btn-sm" onClick={async () => {
                try {
                  const r = await api.mailCode(account.id);
                  toast.add(r.code ? "success" : "warning", r.code ? `Код: ${r.code}` : (r.message || "Код не найден"));
                } catch (e: any) { toast.add("error", e.message); }
              }}>
                <i className="bi bi-123 me-1" />Взять код TikTok
              </button>
            </div>
            {items === null && <div className="text-center py-4"><span className="spinner-border" /></div>}
            {items?.length === 0 && <div className="text-center text-muted py-4">Писем нет</div>}
            <div className="d-flex flex-column gap-1">
              {items?.map((m) => (
                <div key={m.id} className="vp-card mb-0" style={{ cursor: "pointer" }} onClick={() => show(m.id)}>
                  <div className="d-flex justify-content-between gap-2">
                    <b className="fs-sm">{m.subject}</b>
                    <span className="fs-sm text-muted">{m.received_at ? new Date(m.received_at).toLocaleString() : ""}</span>
                  </div>
                  <div className="fs-sm text-muted">{m.sender}</div>
                  {m.preview && open !== m.id && <div className="fs-sm text-muted mt-1">{m.preview}</div>}
                  {open === m.id && <pre className="fs-sm mt-2 mb-0" style={{ whiteSpace: "pre-wrap" }}>{body}</pre>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MailConnectModal({ account, onClose }: { account: Account; onClose: () => void }) {
  const [data, setData] = useState<MailConnect | null>(null);
  const [state, setState] = useState<MailConnectState | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.mailConnect(account.id).then(setData).catch((e) => setError(e.message));
  }, [account.id]);

  useEffect(() => {
    if (!data) return;
    const t = setInterval(() => {
      api.mailConnectState(account.id).then((s) => {
        setState(s);
        if (s.state === "done") { clearInterval(t); }
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [data, account.id]);

  return (
    <div className="modal d-block" tabIndex={-1} style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="modal-dialog modal-dialog-centered" style={{ maxWidth: 460 }}>
        <div className="modal-content vp">
          <div className="modal-header vp">
            <h6 className="modal-title"><i className="bi bi-envelope-plus me-2" />Подключение почты</h6>
            <button className="btn-close btn-close-white" onClick={onClose} />
          </div>
          <div className="modal-body vp">
            {error && <div className="alert alert-danger py-2 fs-sm">{error}</div>}
            {!data && !error && <div className="text-center py-3"><span className="spinner-border" /></div>}
            {data && (
              <>
                <p className="fs-sm text-muted mb-2">
                  Откройте страницу Microsoft и введите код — это нужно один раз на ящик.
                  Пароль вводится на сайте Microsoft, а не в панели.
                </p>
                <div className="text-center my-3">
                  <div style={{ fontSize: 30, letterSpacing: 3, fontWeight: 700 }}>{data.user_code}</div>
                  <a className="btn btn-vp btn-sm mt-2" href={data.verification_uri} target="_blank" rel="noreferrer">
                    <i className="bi bi-box-arrow-up-right me-1" />Открыть страницу входа
                  </a>
                </div>
                {state?.state === "pending" && <div className="fs-sm text-muted text-center"><span className="spinner-border spinner-border-sm me-2" />Жду подтверждения…</div>}
                {state?.state === "done" && <div className="alert alert-success py-2 fs-sm mb-0">Почта подключена — можно закрывать.</div>}
                {state?.state === "error" && <div className="alert alert-danger py-2 fs-sm mb-0">{state.message}</div>}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
   Login Modal (TikTok built-in login)
   ================================================================ */
function LoginModal({ login, onDone, onClose }: { login: { id: number; name: string }; onDone: () => void; onClose: () => void }) {
  const [step, setStep] = useState<"creds" | "code" | "captcha">("creds");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const savedRef = useRef(false);
  const toast = useToast();

  useEffect(() => {
    const onUnload = () => { if (!savedRef.current) navigator.sendBeacon?.("/api/accounts/login/cancel"); };
    window.addEventListener("beforeunload", onUnload);
    return () => { window.removeEventListener("beforeunload", onUnload); if (!savedRef.current) api.loginCancel().catch(() => {}); };
  }, []);

  function handleStage(r: LoginStage) {
    if (r.stage === "done") { savedRef.current = true; onDone(); return; }
    if (r.stage === "email_code") { setStep("code"); setMsg("TikTok отправил код на почту — введите его."); return; }
    setStep("captcha"); setScreenshot(r.screenshot); setMsg(r.message || "Неожиданный шаг.");
  }

  async function submitCreds() {
    if (!username || !password) return;
    setBusy(true); setMsg(null);
    try { await api.loginCancel().catch(() => {}); handleStage(await api.loginCredentials(login.id, { username, password })); }
    catch (e: any) { toast.add("error", e.message); } finally { setBusy(false); }
  }
  async function submitCode() {
    if (!code) return;
    setBusy(true); setMsg(null);
    try { handleStage(await api.loginCode(login.id, code)); }
    catch (e: any) { toast.add("error", e.message); } finally { setBusy(false); }
  }

  return (
    <div className="modal d-block" tabIndex={-1} style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="modal-dialog modal-dialog-centered" style={{ maxWidth: 440 }}>
        <div className="modal-content vp">
          <div className="modal-header vp">
            <h6 className="modal-title"><i className="bi bi-box-arrow-in-right me-2" />Вход: {login.name}</h6>
            <button className="btn-close btn-close-white" onClick={onClose} />
          </div>
          <div className="modal-body vp">
            {step === "creds" && (
              <div className="d-flex flex-column gap-3">
                <p className="fs-sm text-muted mb-0">Логин/пароль нужны один раз для авторизации через прокси аккаунта. Пароль не сохраняется.</p>
                <div>
                  <label className="form-label vp">Логин / email / телефон</label>
                  <input className="form-control vp" value={username} onChange={(e) => setUsername(e.target.value)} />
                </div>
                <div>
                  <label className="form-label vp">Пароль</label>
                  <input className="form-control vp" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
                </div>
                <button className="btn btn-vp" disabled={busy || !username || !password} onClick={submitCreds}>
                  {busy ? <><span className="spinner-border spinner-border-sm me-2" />Вхожу...</> : "Войти"}
                </button>
              </div>
            )}
            {step === "code" && (
              <div className="d-flex flex-column gap-3">
                {msg && <p className="fs-sm text-muted">{msg}</p>}
                <div>
                  <label className="form-label vp">Код с почты</label>
                  <input className="form-control vp" value={code} onChange={(e) => setCode(e.target.value)} />
                </div>
                <button className="btn btn-vp" disabled={busy || !code} onClick={submitCode}>
                  {busy ? <><span className="spinner-border spinner-border-sm me-2" />Проверяю...</> : "Подтвердить код"}
                </button>
              </div>
            )}
            {step === "captcha" && (
              <div className="d-flex flex-column gap-3">
                {msg && <div className="alert alert-danger py-2 mb-0" style={{ fontSize: 13 }}>{msg}</div>}
                {screenshot && <img className="img-fluid rounded" src={screenshot} alt="Скриншот" style={{ border: "1px solid var(--vp-border)" }} />}
                <p className="fs-sm text-muted mb-0">Капчу решить нельзя. Войдите в антидетект-браузере через этот же прокси и импортируй куки.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
   Proxy Editor (inline per-account)
   ================================================================ */
function ProxyEditor({ a, onChange }: { a: Account; onChange: () => void }) {
  const [val, setVal] = useState(a.proxy_url ?? "");
  const [checking, setChecking] = useState(false);
  const [ipInfo, setIpInfo] = useState<string | null>(null);
  const toast = useToast();

  async function check() {
    setChecking(true); setIpInfo(null);
    try { const r = await api.checkProxy(a.id); setIpInfo(r.ok ? `IP: ${r.ip}` : `✗ ${r.error}`); }
    catch (e: any) { setIpInfo(`✗ ${e.message}`); } finally { setChecking(false); }
  }

  return (
    <div className="d-flex align-items-center gap-2 flex-grow-1">
      <input className="form-control vp form-control-sm" placeholder="Прокси http://user:pass@host:port" value={val} onChange={(e) => setVal(e.target.value)} style={{ maxWidth: 260 }} />
      <button className="btn btn-vp-outline btn-sm" onClick={() => api.updateAccount(a.id, { proxy_url: val || null }).then(onChange).catch((e) => toast.add("error", e.message))}>
        <i className="bi bi-check-lg" />
      </button>
      <button className="btn btn-vp-outline btn-sm" onClick={check} disabled={checking || !a.proxy_url}>
        {checking ? <span className="spinner-border spinner-border-sm" /> : <i className="bi bi-globe2" />}
      </button>
      {ipInfo && <span className={`fs-sm ${ipInfo.startsWith("IP:") ? "text-success" : "text-danger"}`}>{ipInfo}</span>}
    </div>
  );
}

/* ================================================================
   Videos
   ================================================================ */
function Videos({ videos, folders, groups, onChange }: {
  videos: Video[]; folders: AssetFolder[]; groups: AccountGroup[]; onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [folder, setFolder] = useState<number | null | "none">(null);
  const [showCount, setShowCount] = useState(20);
  const toast = useToast();
  const { confirm } = useConfirm();
  const { query } = useContext(SearchCtx);

  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    return videos.filter((v) => {
      if (q && !v.title.toLowerCase().includes(q)) return false;
      if (folder === null) return true;
      return folder === "none" ? v.folder_id == null : v.folder_id === folder;
    });
  }, [videos, query, folder]);
  const visible = filtered.slice(0, showCount);

  async function upload(f: File | null) {
    if (!f) return;
    setBusy(true);
    try { await api.uploadVideo(f); onChange(); toast.add("success", "Видео загружено"); }
    catch (e: any) { toast.add("error", e.message); } finally { setBusy(false); }
  }

  return (
    <div>
      <div className="vp-card">
        <label className="vp-dropzone">
          <input type="file" accept="video/*" hidden disabled={busy} onChange={(e) => upload(e.target.files?.[0] ?? null)} />
          {busy ? <><span className="spinner-border spinner-border-sm me-2" />Загрузка...</> : <><i className="bi bi-cloud-arrow-up me-2" /><span>Загрузить видео</span><br /><small className="text-muted">MP4, MOV, WebM</small></>}
        </label>
      </div>
      <FoldersCard kind="video" title="Папки видео" folders={folders} groups={groups} onChange={onChange} />
      <FolderTabs folders={folders} value={folder} onPick={setFolder} />
      <div className="vp-grid">
        {visible.map((v) => (
          <div className="vp-media-card" key={v.id}>
            <video src={api.videoFileUrl(v.id)} controls muted className="thumb" />
            <div className="info">
              <div className="title" title={v.title}>{v.title}</div>
              <div className="meta">{v.width && v.height ? `${v.width}×${v.height}` : "?"} {v.duration ? `· ${v.duration.toFixed(1)}с` : ""}</div>
            </div>
            <div className="actions">
              <FolderPicker kind="video" id={v.id} folderId={v.folder_id} folders={folders}
                            onChange={onChange} className="me-auto" />
              <button className="btn btn-vp-danger btn-sm" onClick={async () => { if (await confirm("Удалить видео?", `Вы уверены что хотите удалить «${v.title}»?`)) { api.deleteVideo(v.id).then(() => { onChange(); toast.add("info", "Видео удалено"); }); } }}>
                <i className="bi bi-trash" />
              </button>
            </div>
          </div>
        ))}
        {filtered.length > showCount && (
          <button className="btn btn-vp-outline w-100 mt-2" onClick={() => setShowCount((c) => c + 20)}>
            Показать ещё ({filtered.length - showCount})
          </button>
        )}
        {filtered.length === 0 && query && <div className="vp-card text-center text-muted py-4">Ничего не найдено</div>}
      </div>
    </div>
  );
}

/* ================================================================
   Banners
   ================================================================ */
function Banners({ banners, onChange }: { banners: Banner[]; onChange: () => void }) {
  const [name, setName] = useState("");
  const [showCount, setShowCount] = useState(20);
  const toast = useToast();
  const { confirm } = useConfirm();
  const { query } = useContext(SearchCtx);

  const filtered = useMemo(() => {
    if (!query) return banners;
    const q = query.toLowerCase();
    return banners.filter((b) => b.name.toLowerCase().includes(q) || b.type.includes(q));
  }, [banners, query]);
  const visible = filtered.slice(0, showCount);

  async function upload(f: File | null) {
    if (!f) return;
    try { await api.uploadBanner(f, name || f.name); setName(""); onChange(); toast.add("success", "Баннер загружен"); }
    catch (e: any) { toast.add("error", e.message); }
  }

  return (
    <div>
      <div className="vp-card">
        <div className="d-flex align-items-end gap-3 flex-wrap">
          <div style={{ flex: "0 0 220px" }}>
            <label className="form-label vp">Имя баннера</label>
            <input className="form-control vp" placeholder="Мой баннер" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex-grow-1">
            <label className="form-label vp">Файл</label>
            <div>
              <label className="btn btn-vp mb-0" style={{ cursor: "pointer" }}>
                <i className="bi bi-upload me-1" /> Загрузить (PNG/GIF/видео)
                <input type="file" accept="image/*,video/*,.gif" hidden onChange={(e) => upload(e.target.files?.[0] ?? null)} />
              </label>
            </div>
          </div>
        </div>
        <p className="fs-sm text-muted mt-3 mb-0">Картинка (PNG с прозрачностью), GIF или зацикленное видео — позицию настроите в редакторе.</p>
      </div>
      <div className="vp-grid">
        {visible.map((b) => (
          <div className="vp-media-card vp-banner-card" key={b.id}>
            {b.type === "image" ? (
              <img src={api.bannerFileUrl(b.id)} className="thumb" alt={b.name} />
            ) : (
              <video src={api.bannerFileUrl(b.id)} autoPlay muted loop className="thumb" />
            )}
            <div className="info">
              <div className="title">{b.name} <span className="badge-vp badge-vp-muted ms-1">{b.type}</span></div>
            </div>
            <div className="actions">
              <button className="btn btn-vp-danger btn-sm" onClick={async () => { if (await confirm("Удалить баннер?", `Вы уверены что хотите удалить «${b.name}»?`)) { api.deleteBanner(b.id).then(() => { onChange(); toast.add("info", "Баннер удалён"); }); } }}>
                <i className="bi bi-trash" />
              </button>
            </div>
          </div>
        ))}
        {filtered.length > showCount && (
          <button className="btn btn-vp-outline w-100 mt-2" onClick={() => setShowCount((c) => c + 20)}>
            Показать ещё ({filtered.length - showCount})
          </button>
        )}
        {filtered.length === 0 && query && <div className="vp-card text-center text-muted py-4">Ничего не найдено</div>}
      </div>
    </div>
  );
}

/* ================================================================
   Post Form
   ================================================================ */
function PostForm({ accounts, videos, banners, profiles, groups, videoFolders, onCreated }: {
  accounts: Account[]; videos: Video[]; banners: Banner[]; profiles: UniqProfile[];
  groups: AccountGroup[]; videoFolders: AssetFolder[]; onCreated: () => void;
}) {
  const [picked, setPicked] = useState<number[]>([]);
  // Фильтр по группе: null — все аккаунты, -1 — только без группы, иначе id группы.
  const [groupFilter, setGroupFilter] = useState<number | null>(null);
  const [allVideos, setAllVideos] = useState(false);   // «показать все» в списке видео
  const [videoId, setVideoId] = useState<number | null>(null);
  const [bannerId, setBannerId] = useState<number | null>(null);
  const [caption, setCaption] = useState("");
  const [when, setWhen] = useState("");
  const [spreadMin, setSpreadMin] = useState(5);
  const [spreadMax, setSpreadMax] = useState(20);
  const [varyCaption, setVaryCaption] = useState(true);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [splitOn, setSplitOn] = useState(false);
  const [parts, setParts] = useState(3);
  const [gapMin, setGapMin] = useState(30);
  const [gapMax, setGapMax] = useState(120);
  const [labelOn, setLabelOn] = useState(true);
  const [labelTpl, setLabelTpl] = useState("Часть {n}/{total}");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const groupById = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups]);
  const inFilter = (a: Account) =>
    groupFilter === null ? true : groupFilter === -1 ? a.group_id == null : a.group_id === groupFilter;
  const shown = accounts.filter(inFilter);
  const ready = shown.filter((a) => a.has_cookies && a.active);
  const toggle = (id: number) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  // Видео, доступные выбранной группе: файл без папки или папка, открытая этой
  // группе. «Показать все» снимает сужение — иногда нужно выложить исключение.
  const groupForAssets = groupFilter !== null && groupFilter !== -1 ? groupFilter : null;
  const shownVideos = allVideos ? videos : visibleToGroup(videos, videoFolders, groupForAssets);
  const hiddenVideos = videos.length - shownVideos.length;

  // Выбранное видео могло выпасть из списка — при смене группы, снятии «показать
  // все» или правке папок. Иначе в задачу ушёл бы ролик, которого в списке не видно.
  useEffect(() => {
    if (videoId !== null && !shownVideos.some((v) => v.id === videoId)) setVideoId(null);
  }, [videoId, shownVideos]);

  /** Выбор группы — это и есть «постить на группу»: фильтруем список и сразу
   *  отмечаем её пригодные аккаунты. «Все аккаунты» только снимает фильтр,
   *  чтобы не терять уже собранный вручную набор. */
  function pickGroup(gid: number | null) {
    setGroupFilter(gid);
    if (gid === null) return;
    const fit = accounts.filter((a) => (gid === -1 ? a.group_id == null : a.group_id === gid));
    setPicked(fit.filter((a) => a.has_cookies && a.active).map((a) => a.id));
  }

  async function submit() {
    if (picked.length === 0 || !videoId) { toast.add("warning", "Выберите аккаунты и видео"); return; }
    setBusy(true);
    try {
      if (splitOn) {
        const r = await api.createJobsParts({
          account_ids: picked,
          video_id: videoId,
          parts,
          caption,
          caption_template: labelTpl,
          label_on: labelOn,
          banner_id: bannerId,
          scheduled_at: when ? new Date(when).toISOString() : null,
          uniq_profile_id: profileId,
          part_gap_min_minutes: gapMin,
          part_gap_max_minutes: gapMax,
          spread_min_minutes: picked.length > 1 ? spreadMin : 0,
          spread_max_minutes: picked.length > 1 ? spreadMax : 0,
        });
        toast.add("success", `Создано задач: ${r.jobs.length} (частей: ${parts})`);
        if (r.skipped.length) toast.add("warning", "Пропущены: " + r.skipped.join("; "));
        onCreated();
        return;
      }
      const r = await api.createJobsBulk({
        account_ids: picked,
        video_id: videoId,
        banner_id: bannerId,
        caption,
        scheduled_at: when ? new Date(when).toISOString() : null,
        spread_min_minutes: picked.length > 1 ? spreadMin : 0,
        spread_max_minutes: picked.length > 1 ? spreadMax : 0,
        vary_caption: picked.length > 1 && varyCaption,
        uniq_profile_id: profileId,
      });
      toast.add("success", `Создано задач: ${r.jobs.length}`);
      if (r.skipped.length) toast.add("warning", "Пропущены: " + r.skipped.join("; "));
      onCreated();
    } catch (e: any) { toast.add("error", e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="vp-card">
      <div className="vp-card-header">
        <h3><i className="bi bi-plus-circle me-2 text-accent" />Новый пост</h3>
      </div>
      <div className="row g-3">
        <div className="col-12">
          <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
            <label className="form-label vp mb-0">
              Аккаунты{picked.length > 0 && <span className="badge-vp badge-vp-info ms-2">выбрано {picked.length}</span>}
            </label>
            <div className="d-flex gap-2 align-items-center flex-wrap">
              {groups.length > 0 && (
                <select className="form-select vp form-select-sm" style={{ maxWidth: 220 }}
                        title="Постить на группу" value={groupFilter ?? ""}
                        onChange={(e) => pickGroup(e.target.value === "" ? null : Number(e.target.value))}>
                  <option value="">— все аккаунты —</option>
                  {groups.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.accounts_count})</option>)}
                  <option value="-1">— без группы —</option>
                </select>
              )}
              <button className="btn btn-vp-outline btn-sm" onClick={() => setPicked(ready.map((a) => a.id))}>Выбрать все</button>
              <button className="btn btn-vp-outline btn-sm" disabled={picked.length === 0} onClick={() => setPicked([])}>Снять</button>
            </div>
          </div>
          <div style={{ maxHeight: 200, overflowY: "auto", border: "1px solid var(--vp-border)", borderRadius: 8, padding: 8 }}>
            {accounts.length === 0 && <div className="fs-sm text-muted">Аккаунтов нет — добавьте их на вкладке «Аккаунты».</div>}
            {accounts.length > 0 && shown.length === 0 && (
              <div className="fs-sm text-muted">В этой группе нет аккаунтов.</div>
            )}
            {shown.map((a) => {
              const usable = a.has_cookies && a.active;
              return (
                <label key={a.id} className="d-flex align-items-center gap-2 py-1" style={{ cursor: usable ? "pointer" : "not-allowed", opacity: usable ? 1 : 0.55 }}>
                  <input type="checkbox" className="form-check-input mt-0" disabled={!usable}
                         checked={picked.includes(a.id)} onChange={() => toggle(a.id)} />
                  <span className="fs-sm">{a.name}</span>
                  <span className="badge-vp badge-vp-info">{a.platform}</span>
                  {a.group_id != null && <GroupBadge group={groupById.get(a.group_id)} />}
                  {!a.has_cookies && <span className="badge-vp badge-vp-danger">нет кук</span>}
                  {a.has_cookies && !a.active && <span className="badge-vp badge-vp-muted">выключен</span>}
                </label>
              );
            })}
          </div>
          <div className="form-text fs-sm">
            Каждый аккаунт получит свой рендер — отдельный файл с отдельным хешем.
            {groups.length > 0
              ? " Выбор группы отмечает все её пригодные аккаунты — лишние можно снять галочкой."
              : " Группы задаются на вкладке «Аккаунты» — ими удобно проверять гипотезы постинга."}
          </div>
        </div>
        <div className="col-md-6">
          <label className="form-label vp">Видео</label>
          <select className="form-select vp" value={videoId ?? ""} onChange={(e) => setVideoId(Number(e.target.value) || null)}>
            <option value="">— выбрать —</option>
            {shownVideos.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
          </select>
          {hiddenVideos > 0 && (
            <label className="form-text fs-sm d-flex align-items-center gap-1 mt-1" style={{ cursor: "pointer" }}>
              <input type="checkbox" className="form-check-input mt-0" checked={allVideos}
                     onChange={(e) => setAllVideos(e.target.checked)} />
              показать все ({hiddenVideos} скрыто: их папки закрыты для этой группы)
            </label>
          )}
          {!allVideos && shownVideos.length === 0 && videos.length > 0 && (
            <div className="form-text fs-sm text-warning">
              Для этой группы нет доступных видео — разложите их по папкам на вкладке «Видео».
            </div>
          )}
        </div>
        <div className="col-md-6">
          <label className="form-label vp">Баннер (необязательно)</label>
          <select className="form-select vp" value={bannerId ?? ""} onChange={(e) => setBannerId(Number(e.target.value) || null)}>
            <option value="">— без баннера —</option>
            {banners.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <div className="col-md-6">
          <label className="form-label vp">Профиль уникализации</label>
          <select className="form-select vp" value={profileId ?? ""}
                  onChange={(e) => setProfileId(Number(e.target.value) || null)}>
            <option value="">— как задано у аккаунта —</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}{p.is_default ? " (по умолчанию)" : ""}</option>)}
          </select>
        </div>
        <div className="col-md-6">
          <label className="form-label vp">Время публикации (пусто = сразу)</label>
          <input className="form-control vp" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </div>
        <div className="col-12">
          <label className="form-label vp">Описание / подпись</label>
          <textarea className="form-control vp" rows={3} value={caption} onChange={(e) => setCaption(e.target.value)} placeholder="Текст поста, #хэштеги" />
        </div>
        <div className="col-12">
          <div className="form-check form-switch">
            <input className="form-check-input" type="checkbox" id="splitOn"
                   checked={splitOn} onChange={(e) => setSplitOn(e.target.checked)} />
            <label className="form-check-label fs-sm" htmlFor="splitOn">
              Разрезать видео на части и выкладывать серией
            </label>
          </div>
          {splitOn && (
            <div className="mt-2">
              <div className="d-flex align-items-center gap-2 flex-wrap">
                <span className="fs-sm text-muted">частей</span>
                <input className="form-control vp form-control-sm" type="number" min={2} max={50} style={{ width: 84 }}
                       value={parts} onChange={(e) => setParts(Math.max(2, Number(e.target.value) || 2))} />
                <span className="fs-sm text-muted">пауза между частями: от</span>
                <input className="form-control vp form-control-sm" type="number" min={0} max={1440} style={{ width: 84 }}
                       value={gapMin} onChange={(e) => setGapMin(Math.max(0, Number(e.target.value) || 0))} />
                <span className="fs-sm text-muted">до</span>
                <input className="form-control vp form-control-sm" type="number" min={0} max={1440} style={{ width: 84 }}
                       value={gapMax} onChange={(e) => setGapMax(Math.max(0, Number(e.target.value) || 0))} />
                <span className="fs-sm text-muted">минут</span>
              </div>
              <div className="d-flex align-items-center gap-2 flex-wrap mt-2">
                <div className="form-check form-switch mb-0">
                  <input className="form-check-input" type="checkbox" id="labelOn"
                         checked={labelOn} onChange={(e) => setLabelOn(e.target.checked)} />
                  <label className="form-check-label fs-sm" htmlFor="labelOn">подпись на видео</label>
                </div>
                {labelOn && (
                  <input className="form-control vp form-control-sm" style={{ maxWidth: 220 }}
                         value={labelTpl} onChange={(e) => setLabelTpl(e.target.value)} />
                )}
              </div>
              <div className="form-text fs-sm">
                {(() => {
                  const v = videos.find((x) => x.id === videoId);
                  const per = v?.duration ? Math.round(v.duration / parts) : null;
                  return per
                    ? `≈ ${per} сек на часть. Каждая часть — отдельный пост со своей уникализацией; на аккаунте окажется вся серия.`
                    : "Каждая часть — отдельный пост со своей уникализацией; на аккаунте окажется вся серия.";
                })()}
                {" "}Реклама внутрь части включается в профиле уникализации.
              </div>
            </div>
          )}
        </div>
        {picked.length > 1 && (
          <div className="col-12">
            <label className="form-label vp">Пауза между аккаунтами</label>
            <div className="d-flex align-items-center gap-2 flex-wrap">
              <span className="fs-sm text-muted">от</span>
              <input className="form-control vp form-control-sm" type="number" min={0} max={720} style={{ width: 90 }}
                     value={spreadMin} onChange={(e) => setSpreadMin(Math.max(0, Number(e.target.value) || 0))} />
              <span className="fs-sm text-muted">до</span>
              <input className="form-control vp form-control-sm" type="number" min={0} max={720} style={{ width: 90 }}
                     value={spreadMax} onChange={(e) => setSpreadMax(Math.max(0, Number(e.target.value) || 0))} />
              <span className="fs-sm text-muted">минут</span>
              <div className="form-check form-switch ms-3 mb-0">
                <input className="form-check-input" type="checkbox" id="varyCaption"
                       checked={varyCaption} onChange={(e) => setVaryCaption(e.target.checked)} />
                <label className="form-check-label fs-sm" htmlFor="varyCaption">варьировать подпись</label>
              </div>
            </div>
            <div className="form-text fs-sm">
              Первый пост уходит сразу, каждый следующий — через случайный интервал из этого диапазона.
            </div>
          </div>
        )}
        <div className="col-12">
          <button className="btn btn-vp" disabled={busy || picked.length === 0 || !videoId} onClick={submit}>
            {busy
              ? <><span className="spinner-border spinner-border-sm me-2" />Создаю…</>
              : <><i className="bi bi-send me-1" />Поставить в очередь{picked.length > 1 ? ` (${picked.length})` : ""}</>}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
   Jobs
   ================================================================ */
function Jobs({ jobs, accounts, videos, onChange }: {
  jobs: Job[]; accounts: Account[]; videos: Video[]; onChange: () => void;
}) {
  const [showCount, setShowCount] = useState(20);
  const toast = useToast();
  const { confirm } = useConfirm();
  const { query } = useContext(SearchCtx);
  const accName = (id: number) => accounts.find((a) => a.id === id)?.name ?? `#${id}`;
  const vidName = (id: number) => videos.find((v) => v.id === id)?.title ?? `#${id}`;

  const filtered = useMemo(() => {
    if (!query) return jobs;
    const q = query.toLowerCase();
    return jobs.filter((j) =>
      `#${j.id}`.includes(q) ||
      j.status.includes(q) ||
      accName(j.account_id).toLowerCase().includes(q) ||
      vidName(j.video_id).toLowerCase().includes(q) ||
      (j.caption || "").toLowerCase().includes(q)
    );
  }, [jobs, query, accounts, videos]);
  const visible = filtered.slice(0, showCount);

  // Позиция задачи в пачке («группа · 2 из 5»), чтобы мультипост было видно в списке
  const groupInfo = useMemo(() => {
    const byGroup = new Map<string, number[]>();
    for (const j of jobs) {
      if (!j.group_id) continue;
      byGroup.set(j.group_id, [...(byGroup.get(j.group_id) ?? []), j.id]);
    }
    const info = new Map<number, string>();
    for (const ids of byGroup.values()) {
      const sorted = [...ids].sort((a, b) => a - b);
      sorted.forEach((id, i) => info.set(id, `${i + 1} из ${sorted.length}`));
    }
    return info;
  }, [jobs]);

  const statusConfig: Record<Job["status"], { label: string; dot: string; badge: string }> = {
    pending: { label: "ожидает", dot: "pending", badge: "badge-vp-muted" },
    rendering: { label: "рендер", dot: "rendering", badge: "badge-vp-warning" },
    uploading: { label: "постинг", dot: "uploading", badge: "badge-vp-info" },
    done: { label: "готово", dot: "ok", badge: "badge-vp-success" },
    failed: { label: "ошибка", dot: "fail", badge: "badge-vp-danger" },
  };

  return (
    <div>
      {jobs.length === 0 && <div className="vp-card text-center text-muted py-5"><i className="bi bi-inbox fs-1 d-block mb-2" />Пока нет задач. Создайте пост в «Новом посте».</div>}
      {filtered.length === 0 && query && <div className="vp-card text-center text-muted py-4">Ничего не найдено по запросу «{query}»</div>}
      {visible.map((jb) => {
        const sc = statusConfig[jb.status];
        return (
          <div className="vp-job" key={jb.id}>
            <div className="vp-job-header">
              <div className="vp-job-info">
                <span className="vp-job-id">#{jb.id}</span>
                <span className={`status-dot ${sc.dot}`} />
                <span className={`badge-vp ${sc.badge}`}>{sc.label}</span>
                <span className="fs-sm">{accName(jb.account_id)} &larr; {vidName(jb.video_id)}</span>
                {jb.part_index && <span className="badge-vp badge-vp-info"><i className="bi bi-scissors me-1" />часть {jb.part_index}/{jb.part_total}</span>}
                {jb.group_id && !jb.part_index && <span className="badge-vp badge-vp-muted"><i className="bi bi-collection me-1" />группа · {groupInfo.get(jb.id) ?? ""}</span>}
                {jb.scheduled_at && <span className="badge-vp badge-vp-muted"><i className="bi bi-clock me-1" />{new Date(jb.scheduled_at).toLocaleString()}</span>}
              </div>
              <div className="d-flex gap-1">
                {jb.status === "failed" && (
                  <button className="btn btn-vp-outline btn-sm" onClick={() => api.retryJob(jb.id).then(() => { onChange(); toast.add("info", "Повтор запущен"); }).catch((e) => toast.add("error", e.message))}>
                    <i className="bi bi-arrow-clockwise" />
                  </button>
                )}
                <button className="btn btn-vp-danger btn-sm" onClick={async () => { if (await confirm("Удалить задачу?", `Вы уверены что хотите удалить задачу #${jb.id}?`)) { api.deleteJob(jb.id).then(() => { onChange(); toast.add("info", "Задача удалена"); }); } }}>
                  <i className="bi bi-trash" />
                </button>
              </div>
            </div>
            {jb.caption && <div className="vp-job-caption">{jb.caption}</div>}
            {jb.error && <div className="vp-job-error"><i className="bi bi-exclamation-triangle me-1" />{jb.error}</div>}
            {/* Скриншот страницы TikTok в момент разбора — иначе неудачу не посмотреть */}
            {/tiktok_[a-z_]+_\d+\.png/.test(`${jb.log ?? ""}${jb.error ?? ""}`) && (
              <a className="btn btn-vp-outline btn-sm mt-2" href={`/api/jobs/${jb.id}/screenshot`} target="_blank" rel="noreferrer">
                <i className="bi bi-image me-1" />Скриншот страницы TikTok
              </a>
            )}
            {jb.log && (
              <details className="vp-job-log">
                <summary className="fs-sm text-muted" style={{ cursor: "pointer" }}>Показать лог</summary>
                <pre>{jb.log}</pre>
              </details>
            )}
          </div>
        );
      })}
      {filtered.length > showCount && (
        <button className="btn btn-vp-outline w-100 mt-2" onClick={() => setShowCount((c) => c + 20)}>
          Показать ещё ({filtered.length - showCount})
        </button>
      )}
    </div>
  );
}

/* ================================================================
   Bulk Proxy Import
   ================================================================ */
function BulkProxyImport({ accounts, onChange }: { accounts: Account[]; onChange: () => void }) {
  const [text, setText] = useState("");
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const toast = useToast();

  async function importProxies() {
    const lines = text.split("\n").map((l) => l.trim()).filter((l) => l && l.startsWith("http"));
    if (lines.length === 0) { toast.add("warning", "Не найдено валидных прокси (начинаются с http://)"); return; }

    setImporting(true);
    let imported = 0;
    const accountsWithoutProxy = accounts.filter((a) => !a.proxy_url);

    for (let i = 0; i < Math.min(lines.length, accountsWithoutProxy.length); i++) {
      try {
        await api.updateAccount(accountsWithoutProxy[i].id, { proxy_url: lines[i] });
        imported++;
      } catch {}
    }

    setImporting(false);
    setText("");
    setResult(`Импортировано ${imported} из ${lines.length} прокси`);
    onChange();
    toast.add("success", `Импортировано ${imported} прокси`);
  }

  return (
    <div className="vp-card mb-3">
      <div className="vp-card-header">
        <h6 className="mb-0"><i className="bi bi-list-ul me-2" />Массовый импорт прокси</h6>
      </div>
      <p className="fs-sm text-muted mb-2">Вставьте прокси по одному на строку (http://user:pass@host:port). Будут назначены аккаунтам без прокси.</p>
      <textarea className="form-control vp" rows={4} placeholder="http://user1:pass1@host1:port1&#10;http://user2:pass2@host2:port2&#10;http://user3:pass3@host3:port3" value={text} onChange={(e) => setText(e.target.value)} />
      <div className="d-flex align-items-center gap-2 mt-2">
        <button className="btn btn-vp btn-sm" onClick={importProxies} disabled={importing || !text.trim()}>
          {importing ? <><span className="spinner-border spinner-border-sm me-1" />Импорт...</> : <><i className="bi bi-upload me-1" />Импортировать</>}
        </button>
        {result && <span className="fs-sm text-success">{result}</span>}
      </div>
    </div>
  );
}

/* ================================================================
   Proxy Manager (NEW tab)
   ================================================================ */
function ProxyManager({ accounts, onChange }: { accounts: Account[]; onChange: () => void }) {
  const [checkingAll, setCheckingAll] = useState(false);
  const [monitoring, setMonitoring] = useState(false);
  const monitoringRef = useRef(false);
  const [interval, setInterval_] = useState(30);
  const [alerts, setAlerts] = useState<{ account: string; error: string; time: string }[]>([]);
  const toast = useToast();

  const proxied = accounts.filter((a) => a.proxy_url);
  const okCount = proxied.filter((a) => a.proxy_ok === true).length;
  const failCount = proxied.filter((a) => a.proxy_ok === false).length;
  const uncheckedCount = proxied.filter((a) => a.proxy_ok === null).length;

  async function checkOne(a: Account) {
    try {
      const r = await api.checkProxy(a.id);
      if (!r.ok) {
        setAlerts((prev) => [{ account: a.name, error: r.error || "неизвестная ошибка", time: new Date().toLocaleTimeString() }, ...prev].slice(0, 20));
      }
      onChange();
      return r;
    } catch (e: any) {
      setAlerts((prev) => [{ account: a.name, error: e.message, time: new Date().toLocaleTimeString() }, ...prev].slice(0, 20));
      return { ok: false };
    }
  }

  async function checkAll() {
    setCheckingAll(true);
    for (const a of proxied) { await checkOne(a); }
    setCheckingAll(false);
    toast.add("success", `Проверено ${proxied.length} прокси`);
  }

  function toggleMonitoring() {
    if (monitoring) {
      setMonitoring(false);
      monitoringRef.current = false;
      if ((window as any).__proxyInterval) { clearInterval((window as any).__proxyInterval); (window as any).__proxyInterval = null; }
      toast.add("info", "Мониторинг остановлен");
    } else {
      setMonitoring(true);
      monitoringRef.current = true;
      toast.add("success", `Мониторинг запущен (каждые ${interval} мин)`);
      checkAll();
      const t = setInterval(() => { if (monitoringRef.current) checkAll(); }, interval * 60 * 1000);
      (window as any).__proxyInterval = t;
    }
  }

  useEffect(() => {
    return () => {
      monitoringRef.current = false;
      if ((window as any).__proxyInterval) clearInterval((window as any).__proxyInterval);
    };
  }, []);

  return (
    <div>
      {/* Stats */}
      <div className="row g-3 mb-4">
        <div className="col-6 col-md-3">
          <div className="vp-stat">
            <div className="vp-stat-value text-accent">{proxied.length}</div>
            <div className="vp-stat-label">Всего прокси</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="vp-stat">
            <div className="vp-stat-value" style={{ color: "var(--vp-success)" }}>{okCount}</div>
            <div className="vp-stat-label">Активных</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="vp-stat">
            <div className="vp-stat-value" style={{ color: "var(--vp-danger)" }}>{failCount}</div>
            <div className="vp-stat-label">Упавших</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="vp-stat">
            <div className="vp-stat-value" style={{ color: "var(--vp-muted)" }}>{uncheckedCount}</div>
            <div className="vp-stat-label">Не проверено</div>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="vp-card">
        <div className="d-flex align-items-center justify-content-between flex-wrap gap-3">
          <div className="d-flex align-items-center gap-2">
            <button className="btn btn-vp" onClick={checkAll} disabled={checkingAll || proxied.length === 0}>
              {checkingAll ? <><span className="spinner-border spinner-border-sm me-2" />Проверяю...</> : <><i className="bi bi-arrow-clockwise me-1" />Проверить все</>}
            </button>
          </div>
          <div className="d-flex align-items-center gap-2">
            <label className="form-label vp mb-0 me-2">Интервал (мин):</label>
            <input className="form-control vp form-control-sm" type="number" min={1} max={1440} style={{ width: 80 }} value={interval} onChange={(e) => setInterval_(Number(e.target.value) || 30)} />
            <button className={`btn ${monitoring ? "btn-vp-danger" : "btn-vp-success"} btn-sm`} onClick={toggleMonitoring}>
              <i className={`bi ${monitoring ? "bi-stop-circle" : "bi-play-circle"} me-1`} />
              {monitoring ? "Остановить" : "Мониторинг"}
            </button>
          </div>
        </div>
      </div>

      {/* Bulk import */}
      <BulkProxyImport accounts={accounts} onChange={onChange} />

      {/* Grouped view */}
      <div className="row g-3 mb-4">
        <div className="col-md-6">
          <div className="vp-card">
            <h6 className="mb-3"><i className="bi bi-tiktok me-2" />TikTok ({accounts.filter((a) => a.platform === "tiktok" && a.proxy_url).length})</h6>
            <div className="d-flex flex-column gap-1">
              {accounts.filter((a) => a.platform === "tiktok" && a.proxy_url).map((a) => (
                <div key={a.id} className="d-flex align-items-center gap-2 fs-sm">
                  <span className={`status-dot ${a.proxy_ok === true ? "ok" : a.proxy_ok === false ? "fail" : "pending"}`} />
                  <span className="flex-grow-1">{a.name}</span>
                  <span className="text-muted">{a.proxy_ip || "—"}</span>
                </div>
              ))}
              {accounts.filter((a) => a.platform === "tiktok" && a.proxy_url).length === 0 && <span className="text-muted fs-sm">Нет прокси</span>}
            </div>
          </div>
        </div>
        <div className="col-md-6">
          <div className="vp-card">
            <h6 className="mb-3"><i className="bi bi-youtube me-2" />YouTube ({accounts.filter((a) => a.platform === "youtube" && a.proxy_url).length})</h6>
            <div className="d-flex flex-column gap-1">
              {accounts.filter((a) => a.platform === "youtube" && a.proxy_url).map((a) => (
                <div key={a.id} className="d-flex align-items-center gap-2 fs-sm">
                  <span className={`status-dot ${a.proxy_ok === true ? "ok" : a.proxy_ok === false ? "fail" : "pending"}`} />
                  <span className="flex-grow-1">{a.name}</span>
                  <span className="text-muted">{a.proxy_ip || "—"}</span>
                </div>
              ))}
              {accounts.filter((a) => a.platform === "youtube" && a.proxy_url).length === 0 && <span className="text-muted fs-sm">Нет прокси</span>}
            </div>
          </div>
        </div>
      </div>

      {/* Proxy table */}
      {proxied.length === 0 ? (
        <div className="vp-card text-center text-muted py-5">
          <i className="bi bi-shield-x fs-1 d-block mb-2" />
          Нет аккаунтов с прокси. Добавьте прокси в настройках аккаунта.
        </div>
      ) : (
        <div className="vp-card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="table vp mb-0">
            <thead>
              <tr>
                <th>Аккаунт</th>
                <th>Прокси</th>
                <th>Статус</th>
                <th>IP</th>
                <th>Проверка</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {proxied.map((a) => (
                <tr key={a.id}>
                  <td>
                    <div className="d-flex align-items-center gap-2">
                      <i className={`bi ${a.platform === "tiktok" ? "bi-tiktok" : "bi-youtube"}`} />
                      <span className="fw-600">{a.name}</span>
                    </div>
                  </td>
                  <td><code className="fs-sm">{a.proxy_url}</code></td>
                  <td>
                    {a.proxy_ok === true && <span className="badge-vp badge-vp-success"><span className="status-dot ok me-1" />Работает</span>}
                    {a.proxy_ok === false && <span className="badge-vp badge-vp-danger"><span className="status-dot fail me-1" />Упал</span>}
                    {a.proxy_ok === null && <span className="badge-vp badge-vp-muted"><span className="status-dot pending me-1" />Не проверен</span>}
                  </td>
                  <td className="fs-sm">{a.proxy_ip || "—"}</td>
                  <td className="fs-sm text-muted">{a.proxy_checked_at ? new Date(a.proxy_checked_at).toLocaleString() : "—"}</td>
                  <td>
                    <button className="btn btn-vp-outline btn-sm" onClick={() => checkOne(a)}>
                      <i className="bi bi-arrow-clockwise" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Dead proxy alerts */}
      {alerts.length > 0 && (
        <div className="vp-card mt-3">
          <div className="vp-card-header">
            <h3><i className="bi bi-exclamation-triangle text-danger me-2" />Алерты (прокси упали)</h3>
            <button className="btn btn-vp-outline btn-sm" onClick={() => setAlerts([])}>Очистить</button>
          </div>
          <div style={{ maxHeight: 300, overflowY: "auto" }}>
            {alerts.map((al, i) => (
              <div className="vp-proxy-alert" key={i}>
                <i className="bi bi-x-circle-fill text-danger" />
                <span><b>{al.account}</b>: {al.error}</span>
                <span className="time">{al.time}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ================================================================
   Stats Dashboard
   ================================================================ */
function Stats({ jobs, accounts, videos, groups }: {
  jobs: Job[]; accounts: Account[]; videos: Video[]; groups: AccountGroup[];
}) {
  const total = jobs.length;
  const done = jobs.filter((j) => j.status === "done").length;
  const failed = jobs.filter((j) => j.status === "failed").length;
  const pending = jobs.filter((j) => j.status === "pending").length;
  const rendering = jobs.filter((j) => j.status === "rendering").length;
  const uploading = jobs.filter((j) => j.status === "uploading").length;
  const successRate = total > 0 ? Math.round((done / total) * 100) : 0;

  // Jobs per day (last 7 days)
  const last7 = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (6 - i));
    d.setHours(0, 0, 0, 0);
    const next = new Date(d);
    next.setDate(next.getDate() + 1);
    const dayJobs = jobs.filter((j) => {
      const created = new Date(j.created_at);
      return created >= d && created < next;
    });
    return {
      label: d.toLocaleDateString("ru", { weekday: "short", day: "numeric" }),
      done: dayJobs.filter((j) => j.status === "done").length,
      failed: dayJobs.filter((j) => j.status === "failed").length,
      total: dayJobs.length,
    };
  });
  const maxDay = Math.max(1, ...last7.map((d) => d.total));

  // Разбивка по группам-когортам. Считается на клиенте из уже загруженных данных:
  // задача знает аккаунт, аккаунт — свою текущую группу.
  const byGroup = useMemo(() => {
    const groupOf = new Map(accounts.map((a) => [a.id, a.group_id ?? null]));
    const rows = [
      ...groups.map((g) => ({ id: g.id as number | null, name: g.name, color: g.color })),
      { id: null as number | null, name: "Без группы", color: null as string | null },
    ].map((row) => {
      const accs = accounts.filter((a) => (a.group_id ?? null) === row.id);
      const gj = jobs.filter((j) => (groupOf.get(j.account_id) ?? null) === row.id);
      const gd = gj.filter((j) => j.status === "done").length;
      const gf = gj.filter((j) => j.status === "failed").length;
      return {
        ...row, accounts: accs.length, jobs: gj.length, done: gd, failed: gf,
        rate: gj.length > 0 ? Math.round((gd / gj.length) * 100) : 0,
      };
    });
    // строку «Без группы» показываем только если там что-то есть
    return rows.filter((r) => r.id !== null || r.accounts > 0 || r.jobs > 0);
  }, [jobs, accounts, groups]);

  // Accounts by platform
  const tiktok = accounts.filter((a) => a.platform === "tiktok").length;
  const youtube = accounts.filter((a) => a.platform === "youtube").length;

  return (
    <div>
      {/* Summary cards */}
      <div className="row g-3 mb-4">
        <div className="col-6 col-md-3">
          <div className="vp-stat">
            <div className="vp-stat-value text-accent">{total}</div>
            <div className="vp-stat-label">Всего задач</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="vp-stat">
            <div className="vp-stat-value" style={{ color: "var(--vp-success)" }}>{done}</div>
            <div className="vp-stat-label">Выполнено</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="vp-stat">
            <div className="vp-stat-value" style={{ color: "var(--vp-danger)" }}>{failed}</div>
            <div className="vp-stat-label">Ошибки</div>
          </div>
        </div>
        <div className="col-6 col-md-3">
          <div className="vp-stat">
            <div className="vp-stat-value" style={{ color: "var(--vp-warning)" }}>{pending + rendering + uploading}</div>
            <div className="vp-stat-label">В работе</div>
          </div>
        </div>
      </div>

      <div className="row g-3 mb-4">
        <div className="col-md-4">
          <div className="vp-card">
            <h6 className="mb-3"><i className="bi bi-pie-chart me-2" />Успешность</h6>
            <div className="d-flex align-items-center gap-3">
              <div style={{ width: 80, height: 80, borderRadius: "50%", background: `conic-gradient(var(--vp-success) ${successRate * 3.6}deg, var(--vp-border) 0)`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <div style={{ width: 60, height: 60, borderRadius: "50%", background: "var(--vp-panel)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, fontWeight: 700 }}>
                  {successRate}%
                </div>
              </div>
              <div className="fs-sm text-muted">
                <div>✅ {done} выполнено</div>
                <div>❌ {failed} ошибок</div>
                <div>⏳ {pending} в очереди</div>
              </div>
            </div>
          </div>
        </div>
        <div className="col-md-4">
          <div className="vp-card">
            <h6 className="mb-3"><i className="bi bi-people me-2" />Аккаунты</h6>
            <div className="d-flex gap-4">
              <div className="text-center">
                <div className="fs-4 fw-bold" style={{ color: "var(--vp-accent)" }}>{accounts.length}</div>
                <div className="fs-sm text-muted">Всего</div>
              </div>
              <div className="text-center">
                <div className="fs-4 fw-bold">🎵 {tiktok}</div>
                <div className="fs-sm text-muted">TikTok</div>
              </div>
              <div className="text-center">
                <div className="fs-4 fw-bold">▶️ {youtube}</div>
                <div className="fs-sm text-muted">YouTube</div>
              </div>
            </div>
          </div>
        </div>
        <div className="col-md-4">
          <div className="vp-card">
            <h6 className="mb-3"><i className="bi bi-play-circle me-2" />Контент</h6>
            <div className="d-flex gap-4">
              <div className="text-center">
                <div className="fs-4 fw-bold" style={{ color: "var(--vp-accent)" }}>{videos.length}</div>
                <div className="fs-sm text-muted">Видео</div>
              </div>
              <div className="text-center">
                <div className="fs-4 fw-bold" style={{ color: "var(--vp-accent)" }}>{total}</div>
                <div className="fs-sm text-muted">Постов</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Разбивка по группам — ради неё группы и заводятся */}
      {groups.length > 0 && (
        <div className="vp-card mb-4">
          <h6 className="mb-3"><i className="bi bi-collection me-2" />По группам</h6>
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-0">
              <thead>
                <tr className="fs-sm text-muted">
                  <th>Группа</th><th className="text-end">Аккаунтов</th><th className="text-end">Задач</th>
                  <th className="text-end">Выполнено</th><th className="text-end">Ошибок</th>
                  <th style={{ minWidth: 140 }}>Успех</th>
                </tr>
              </thead>
              <tbody>
                {byGroup.map((r) => {
                  const c = r.color || GROUP_FALLBACK;
                  return (
                    <tr key={r.id ?? "none"}>
                      <td>
                        {r.id === null
                          ? <span className="badge-vp badge-vp-muted">{r.name}</span>
                          : <span className="badge-vp" style={{ background: `${c}26`, color: c }}>
                              <i className="bi bi-collection" /> {r.name}
                            </span>}
                      </td>
                      <td className="text-end">{r.accounts}</td>
                      <td className="text-end">{r.jobs}</td>
                      <td className="text-end" style={{ color: "var(--vp-success)" }}>{r.done}</td>
                      <td className="text-end" style={{ color: "var(--vp-danger)" }}>{r.failed}</td>
                      <td>
                        <div className="d-flex align-items-center gap-2">
                          <div style={{ flex: 1, height: 6, borderRadius: 3, background: "var(--vp-border)" }}>
                            <div style={{ width: `${r.rate}%`, height: "100%", borderRadius: 3, background: "var(--vp-success)" }} />
                          </div>
                          <span className="fs-sm text-muted" style={{ minWidth: 34 }}>{r.jobs > 0 ? `${r.rate}%` : "—"}</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="form-text fs-sm mt-2">
            Считается по текущей принадлежности аккаунтов: если перенести аккаунт в другую
            группу, его прошлые посты уедут вместе с ним.
          </div>
        </div>
      )}

      {/* Activity chart */}
      <div className="vp-card">
        <h6 className="mb-3"><i className="bi bi-bar-chart-line me-2" />Активность за 7 дней</h6>
        <div className="d-flex align-items-end gap-2" style={{ height: 140 }}>
          {last7.map((day, i) => (
            <div key={i} className="flex-grow-1 d-flex flex-column align-items-center gap-1">
              <div className="w-100 d-flex flex-column align-items-center" style={{ height: 100 }}>
                {day.done > 0 && (
                  <div className="w-100 rounded-top" style={{ height: `${(day.done / maxDay) * 100}%`, background: "var(--vp-success)", minHeight: 2 }} />
                )}
                {day.failed > 0 && (
                  <div className="w-100" style={{ height: `${(day.failed / maxDay) * 100}%`, background: "var(--vp-danger)", minHeight: 2 }} />
                )}
              </div>
              <div className="fs-sm text-muted" style={{ fontSize: 10 }}>{day.label}</div>
            </div>
          ))}
        </div>
        <div className="d-flex gap-3 mt-2 fs-sm">
          <span><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: "var(--vp-success)", marginRight: 4 }} />Выполнено</span>
          <span><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: "var(--vp-danger)", marginRight: 4 }} />Ошибки</span>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
   Settings
   ================================================================ */
function Settings() {
  const [s, setS] = useState<SettingsData | null>(null);
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [newPass, setNewPass] = useState("");
  const [msClientId, setMsClientId] = useState("");
  const [ver, setVer] = useState<SystemVersion | null>(null);
  const [gitToken, setGitToken] = useState("");
  const [gitOpen, setGitOpen] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api.getSettings().then((d) => { setS(d); setChatId(d.tg_chat_id ?? ""); setEnabled(d.tg_login_enabled); setMsClientId(d.ms_client_id ?? ""); }).catch((e) => toast.add("error", e.message));
    const load = () => api.systemVersion().then(setVer).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  // приватный репозиторий без токена — сразу открываем поле для токена
  useEffect(() => { if (ver?.git_status === "auth_required") setGitOpen(true); }, [ver?.git_status]);

  async function doUpdate() {
    try { await api.systemUpdate(); toast.add("success", "Обновление запущено — панель перезапустится через минуту."); }
    catch (e: any) { toast.add("error", e.message); }
  }

  async function saveGitToken() {
    try {
      const r = await api.systemGitToken(gitToken);
      if (!r.ok) { toast.add("error", r.error ?? "Не удалось сохранить токен"); return; }
      setGitToken("");
      toast.add("success", "Токен передан — апдейтер проверит доступ через несколько секунд.");
    } catch (e: any) { toast.add("error", e.message); }
  }

  async function save() {
    try {
      const body: any = { tg_chat_id: chatId, tg_login_enabled: enabled, ms_client_id: msClientId };
      if (token) body.tg_bot_token = token;
      if (newPass) body.new_password = newPass;
      const d = await api.updateSettings(body);
      setS(d); setToken(""); setNewPass(""); toast.add("success", "Настройки сохранены");
    } catch (e: any) { toast.add("error", e.message); }
  }

  if (!s) return <div className="d-flex justify-content-center py-5"><div className="spinner-border text-primary" /></div>;

  return (
    <div style={{ maxWidth: 600 }}>
      {/* Telegram */}
      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-telegram me-2 text-accent" />Telegram</h3>
        </div>
        <div className="d-flex flex-column gap-3">
          <div>
            <label className="form-label vp">{s.tg_bot_configured ? "Токен бота (задан, ввод заменит)" : "Токен бота @BotFather"}</label>
            <input className="form-control vp" type="password" placeholder={s.tg_bot_configured ? "••••••••" : "123456:ABC-..."} value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
          <div>
            <label className="form-label vp">Chat ID — можно несколько через запятую</label>
            <input className="form-control vp" placeholder="123456789, 987654321" value={chatId} onChange={(e) => setChatId(e.target.value)} />
            <div className="form-text fs-sm">Все указанные аккаунты получают уведомления, код входа и могут командовать ботом.</div>
          </div>
          <div className="form-check form-switch">
            <input className="form-check-input" type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} id="tgLoginEnabled" />
            <label className="form-check-label fs-sm" htmlFor="tgLoginEnabled">Разрешить вход в панель через Telegram (2FA)</label>
          </div>
          <p className="fs-sm text-muted mb-0">Уведомления о постинге и упавших прокси приходят во все указанные чаты. Бот: /queue, /accounts, /stats; присланное видео добавляется в библиотеку.</p>
        </div>
      </div>

      {/* Почта аккаунтов */}
      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-envelope-at me-2 text-accent" />Почта аккаунтов</h3>
        </div>
        <div>
          <label className="form-label vp">Client ID приложения Microsoft</label>
          <input className="form-control vp" placeholder="00000000-0000-0000-0000-000000000000"
                 value={msClientId} onChange={(e) => setMsClientId(e.target.value)} />
          <div className="form-text fs-sm">
            Нужен, чтобы панель читала письма outlook/hotmail: Microsoft больше не пускает
            к почте по обычному паролю. Регистрация приложения — разовая и бесплатная,
            пошагово описана в INSTALL.md. Дальше у каждого профиля жмите «Подключить почту».
          </div>
        </div>
      </div>

      {/* Password */}
      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-key me-2 text-accent" />Смена пароля</h3>
        </div>
        <div className="d-flex flex-column gap-3">
          <div>
            <label className="form-label vp">Новый пароль (пусто — не менять)</label>
            <input className="form-control vp" type="password" value={newPass} onChange={(e) => setNewPass(e.target.value)} />
          </div>
          <div>
            <button className="btn btn-vp" onClick={save}><i className="bi bi-check-lg me-1" />Сохранить</button>
          </div>
        </div>
      </div>

      {/* Update */}
      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-cloud-arrow-up me-2 text-accent" />Обновление</h3>
        </div>
        <div className="d-flex align-items-center gap-3 flex-wrap">
          <span className="fs-sm text-muted">Версия: {ver?.version ?? "..."}</span>
          <button className="btn btn-vp-outline btn-sm" onClick={doUpdate}><i className="bi bi-download me-1" />Обновить с GitHub</button>
          {ver?.git_status === "ok" && <span className="badge-vp badge-vp-success"><i className="bi bi-check-circle me-1" />доступ к репозиторию есть</span>}
          {ver?.git_status === "auth_required" && <span className="badge-vp badge-vp-warning"><i className="bi bi-lock me-1" />нужен токен GitHub</span>}
          {ver?.git_status === "no_git" && <span className="badge-vp badge-vp-muted">установлено не из git — обновление недоступно</span>}
        </div>
        {ver?.update_status && <p className="fs-sm text-muted mt-2 mb-0">Статус: {ver.update_status}</p>}

        {ver?.git_status !== "no_git" && (
          <div className="mt-3 pt-3 border-top border-vp">
            {!gitOpen ? (
              <button className="btn btn-link btn-sm p-0 fs-sm" onClick={() => setGitOpen(true)}>
                <i className="bi bi-key me-1" />Токен для приватного репозитория
              </button>
            ) : (
              <div className="d-flex flex-column gap-2">
                <label className="form-label vp mb-0">Токен GitHub (для приватного репозитория)</label>
                <input className="form-control vp" type="password" placeholder="github_pat_… или ghp_…"
                       value={gitToken} onChange={(e) => setGitToken(e.target.value)} />
                <div className="form-text fs-sm">
                  GitHub → Settings → Developer settings → <b>Fine-grained tokens</b>: доступ только к этому
                  репозиторию, право <b>Contents: Read-only</b>. Токен не сохраняется в базе — он передаётся
                  апдейтеру на хосте и хранится только в git credential store (chmod 600).
                </div>
                <div className="d-flex gap-2">
                  <button className="btn btn-vp btn-sm" disabled={!gitToken.trim()} onClick={saveGitToken}>
                    <i className="bi bi-check-lg me-1" />Сохранить токен
                  </button>
                  <button className="btn btn-vp-outline btn-sm" onClick={() => { setGitToken(""); setGitOpen(false); }}>Скрыть</button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
