import { useEffect, useRef, useState, useCallback, createContext, useContext, useMemo } from "react";
import { api, Account, Banner, Job, LoginStage, Platform, SettingsData, SystemVersion, Video } from "./api";
import { BannerEditor } from "./BannerEditor";

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
type Tab = "jobs" | "post" | "editor" | "accounts" | "videos" | "banners" | "proxy" | "stats" | "settings";

const NAV_ITEMS: { tab: Tab; icon: string; label: string }[] = [
  { tab: "jobs", icon: "bi-clipboard2-data", label: "Очередь" },
  { tab: "post", icon: "bi-plus-circle", label: "Новый пост" },
  { tab: "editor", icon: "bi-film", label: "Редактор" },
  { tab: "accounts", icon: "bi-people", label: "Аккаунты" },
  { tab: "videos", icon: "bi-play-circle", label: "Видео" },
  { tab: "banners", icon: "bi-image", label: "Баннеры" },
  { tab: "proxy", icon: "bi-shield-check", label: "Прокси" },
  { tab: "stats", icon: "bi-bar-chart-line", label: "Статистика" },
  { tab: "settings", icon: "bi-gear", label: "Настройки" },
];

const TAB_LABELS: Record<Tab, string> = {
  jobs: "Очередь", post: "Новый пост", editor: "Редактор", accounts: "Аккаунты",
  videos: "Видео", banners: "Баннеры", proxy: "Прокси", stats: "Статистика", settings: "Настройки",
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
      const [a, v, b, j] = await Promise.all([api.accounts(), api.videos(), api.banners(), api.jobs()]);
      setAccounts(a); setVideos(v); setBanners(b); setJobs(j);
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
            {tab === "post" && <PostForm accounts={accounts} videos={videos} banners={banners} onCreated={() => { refreshAll(); setTab("jobs"); }} />}
            {tab === "editor" && <BannerEditor videos={videos} banners={banners} accounts={accounts}
              onSaved={refreshAll} onPosted={() => { refreshAll(); setTab("jobs"); }} />}
            {tab === "accounts" && <Accounts accounts={accounts} onChange={refreshAll} />}
            {tab === "videos" && <Videos videos={videos} onChange={refreshAll} />}
            {tab === "banners" && <Banners banners={banners} onChange={refreshAll} />}
            {tab === "proxy" && <ProxyManager accounts={accounts} onChange={refreshAll} />}
            {tab === "stats" && <Stats jobs={jobs} accounts={accounts} videos={videos} />}
            {tab === "settings" && <Settings />}
          </SearchCtx.Provider>
        </div>
      </div>
    </>
  );
}

/* ================================================================
   Accounts
   ================================================================ */
function Accounts({ accounts, onChange }: { accounts: Account[]; onChange: () => void }) {
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [proxy, setProxy] = useState("");
  const [login, setLogin] = useState<{ id: number; name: string } | null>(null);
  const [showCount, setShowCount] = useState(20);
  const toast = useToast();
  const { confirm } = useConfirm();
  const { query } = useContext(SearchCtx);

  const filtered = useMemo(() => {
    if (!query) return accounts;
    const q = query.toLowerCase();
    return accounts.filter((a) => a.name.toLowerCase().includes(q) || a.platform.includes(q) || (a.proxy_url || "").toLowerCase().includes(q));
  }, [accounts, query]);
  const visible = filtered.slice(0, showCount);

  async function create() {
    try {
      await api.createAccount({ name, platform, proxy_url: proxy || null });
      setName(""); setProxy(""); onChange(); toast.add("success", "Аккаунт создан");
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
          <div className="col-md-5">
            <label className="form-label vp">Прокси</label>
            <input className="form-control vp" placeholder="http://user:pass@host:port" value={proxy} onChange={(e) => setProxy(e.target.value)} />
          </div>
          <div className="col-md-2">
            <button className="btn btn-vp w-100" onClick={create} disabled={!name}>Создать</button>
          </div>
        </div>
        <p className="fs-sm text-muted mt-2 mb-0">Каждый аккаунт — свой прокси. Куки (storage_state) — авторизация без пароля.</p>
      </div>

      <div className="d-flex flex-column gap-2">
        {visible.map((a) => (
          <div className="vp-card" key={a.id}>
            <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
              <div className="d-flex align-items-center gap-2 flex-wrap">
                <i className={`bi ${a.platform === "tiktok" ? "bi-tiktok" : "bi-youtube"} fs-5`} />
                <b>{a.name}</b>
                <span className="badge-vp badge-vp-info">{a.platform}</span>
                {a.has_cookies ? <span className="badge-vp badge-vp-success"><i className="bi bi-check-circle" /> куки</span> : <span className="badge-vp badge-vp-danger"><i className="bi bi-x-circle" /> нет кук</span>}
                {a.proxy_url ? <span className="badge-vp badge-vp-muted"><i className="bi bi-shield" /> прокси</span> : <span className="badge-vp badge-vp-danger">без прокси</span>}
                {a.proxy_url && a.proxy_ok === true && <span className="badge-vp badge-vp-success">IP {a.proxy_ip}</span>}
                {a.proxy_url && a.proxy_ok === false && <span className="badge-vp badge-vp-danger"><i className="bi bi-x-circle" /> прокси down</span>}
              </div>
              <button className="btn btn-vp-danger btn-sm" onClick={async () => { if (await confirm("Удалить аккаунт?", `Вы уверены что хотите удалить «${a.name}»?`)) { api.deleteAccount(a.id).then(() => { onChange(); toast.add("info", "Аккаунт удалён"); }); } }}>
                <i className="bi bi-trash" />
              </button>
            </div>
            <div className="d-flex align-items-center gap-2 mt-2 flex-wrap">
              <button className="btn btn-vp btn-sm" onClick={() => setLogin({ id: a.id, name: a.name })}>
                <i className="bi bi-box-arrow-in-right me-1" />Войти
              </button>
              <label className="btn btn-vp-outline btn-sm mb-0">
                <i className="bi bi-upload me-1" />Куки (JSON)
                <input type="file" accept="application/json,.json" hidden onChange={(e) => onCookies(a.id, e.target.files?.[0] ?? null)} />
              </label>
              <label className="d-flex align-items-center gap-1 fs-sm text-muted" style={{ cursor: "pointer" }}>
                <input type="checkbox" className="form-check-input" checked={a.uniqueize}
                  onChange={(e) => api.updateAccount(a.id, { uniqueize: e.target.checked }).then(onChange).catch((x) => toast.add("error", x.message))} />
                уникализация
              </label>
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

      {login && <LoginModal login={login} onDone={() => { setLogin(null); onChange(); toast.add("success", "Вход выполнен"); }} onClose={() => setLogin(null)} />}
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
function Videos({ videos, onChange }: { videos: Video[]; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [showCount, setShowCount] = useState(20);
  const toast = useToast();
  const { confirm } = useConfirm();
  const { query } = useContext(SearchCtx);

  const filtered = useMemo(() => {
    if (!query) return videos;
    const q = query.toLowerCase();
    return videos.filter((v) => v.title.toLowerCase().includes(q));
  }, [videos, query]);
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
      <div className="vp-grid">
        {visible.map((v) => (
          <div className="vp-media-card" key={v.id}>
            <video src={api.videoFileUrl(v.id)} controls muted className="thumb" />
            <div className="info">
              <div className="title" title={v.title}>{v.title}</div>
              <div className="meta">{v.width && v.height ? `${v.width}×${v.height}` : "?"} {v.duration ? `· ${v.duration.toFixed(1)}с` : ""}</div>
            </div>
            <div className="actions">
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
function PostForm({ accounts, videos, banners, onCreated }: {
  accounts: Account[]; videos: Video[]; banners: Banner[]; onCreated: () => void;
}) {
  const [accountId, setAccountId] = useState<number | null>(null);
  const [videoId, setVideoId] = useState<number | null>(null);
  const [bannerId, setBannerId] = useState<number | null>(null);
  const [caption, setCaption] = useState("");
  const [when, setWhen] = useState("");
  const toast = useToast();

  async function submit() {
    if (!accountId || !videoId) { toast.add("warning", "Выберите аккаунт и видео"); return; }
    try {
      await api.createJob({
        account_id: accountId, video_id: videoId, banner_id: bannerId,
        caption, scheduled_at: when ? new Date(when).toISOString() : null,
      });
      toast.add("success", "Задача создана"); onCreated();
    } catch (e: any) { toast.add("error", e.message); }
  }

  return (
    <div className="vp-card">
      <div className="vp-card-header">
        <h3><i className="bi bi-plus-circle me-2 text-accent" />Новый пост</h3>
      </div>
      <div className="row g-3">
        <div className="col-md-6">
          <label className="form-label vp">Аккаунт</label>
          <select className="form-select vp" value={accountId ?? ""} onChange={(e) => setAccountId(Number(e.target.value) || null)}>
            <option value="">— выбрать —</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.platform}){a.has_cookies ? "" : " ⚠без кук"}</option>)}
          </select>
        </div>
        <div className="col-md-6">
          <label className="form-label vp">Видео</label>
          <select className="form-select vp" value={videoId ?? ""} onChange={(e) => setVideoId(Number(e.target.value) || null)}>
            <option value="">— выбрать —</option>
            {videos.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
          </select>
        </div>
        <div className="col-md-6">
          <label className="form-label vp">Баннер (необязательно)</label>
          <select className="form-select vp" value={bannerId ?? ""} onChange={(e) => setBannerId(Number(e.target.value) || null)}>
            <option value="">— без баннера —</option>
            {banners.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
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
          <button className="btn btn-vp" onClick={submit}>
            <i className="bi bi-send me-1" />Поставить в очередь
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
function Stats({ jobs, accounts, videos }: { jobs: Job[]; accounts: Account[]; videos: Video[] }) {
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
  const [ver, setVer] = useState<SystemVersion | null>(null);
  const [gitToken, setGitToken] = useState("");
  const [gitOpen, setGitOpen] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api.getSettings().then((d) => { setS(d); setChatId(d.tg_chat_id ?? ""); setEnabled(d.tg_login_enabled); }).catch((e) => toast.add("error", e.message));
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
      const body: any = { tg_chat_id: chatId, tg_login_enabled: enabled };
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
