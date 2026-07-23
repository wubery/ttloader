import { useEffect, useRef, useState } from "react";
import { api, Account, Banner, Job, LoginStage, Platform, SettingsData, Video } from "./api";
import { BannerEditor } from "./BannerEditor";

type Tab = "accounts" | "videos" | "banners" | "editor" | "post" | "jobs" | "settings";

export function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    api.authMe().then((m) => setAuthed(m.authenticated)).catch(() => setAuthed(false));
  }, []);

  if (authed === null) return <div className="app"><p style={{ padding: 24 }}>Загрузка…</p></div>;
  if (!authed) return <LoginPage onLogin={() => setAuthed(true)} />;
  return <Dashboard onLogout={() => setAuthed(false)} />;
}

function Dashboard({ onLogout }: { onLogout: () => void }) {
  const [tab, setTab] = useState<Tab>("jobs");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [videos, setVideos] = useState<Video[]>([]);
  const [banners, setBanners] = useState<Banner[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  async function refreshAll() {
    try {
      const [a, v, b, j] = await Promise.all([api.accounts(), api.videos(), api.banners(), api.jobs()]);
      setAccounts(a); setVideos(v); setBanners(b); setJobs(j);
    } catch (e: any) { setErr(e.message); }
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

  return (
    <div className="app">
      <header>
        <h1>🎬 Video Poster</h1>
        <nav>
          {(["jobs", "post", "editor", "accounts", "videos", "banners", "settings"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "tab active" : "tab"} onClick={() => setTab(t)}>
              {tabLabel(t)}
            </button>
          ))}
          <button className="tab" onClick={logout}>Выйти</button>
        </nav>
      </header>

      {health && (!health.ffmpeg || !health.playwright) && (
        <div className="warn">
          {!health.ffmpeg && <div>⚠ ffmpeg недоступен на бэкенде — наложение баннера не будет работать.</div>}
          {!health.playwright && <div>⚠ Playwright не установлен — постинг не будет работать.</div>}
        </div>
      )}
      {err && <div className="warn" onClick={() => setErr(null)}>Ошибка: {err} (клик чтобы скрыть)</div>}

      <main>
        {tab === "accounts" && <Accounts accounts={accounts} onChange={refreshAll} setErr={setErr} />}
        {tab === "videos" && <Videos videos={videos} onChange={refreshAll} setErr={setErr} />}
        {tab === "banners" && <Banners banners={banners} onChange={refreshAll} setErr={setErr} />}
        {tab === "editor" && <BannerEditor videos={videos} banners={banners} onSaved={refreshAll} />}
        {tab === "post" && <PostForm accounts={accounts} videos={videos} banners={banners} onCreated={() => { refreshAll(); setTab("jobs"); }} setErr={setErr} />}
        {tab === "jobs" && <Jobs jobs={jobs} accounts={accounts} videos={videos} onChange={refreshAll} setErr={setErr} />}
        {tab === "settings" && <Settings setErr={setErr} />}
      </main>
    </div>
  );
}

function tabLabel(t: Tab) {
  return { jobs: "Очередь", post: "＋ Новый пост", editor: "Баннер+превью", accounts: "Аккаунты", videos: "Видео", banners: "Баннеры", settings: "Настройки" }[t];
}

function LoginPage({ onLogin }: { onLogin: () => void }) {
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
    setBusy(true); setErr(null);
    try { await api.tgLoginVerify(code); onLogin(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="login-page">
      <div className="card login-card">
        <h1>🎬 Video Poster</h1>
        {err && <div className="warn">{err}</div>}
        <div className="col" style={{ gap: 8 }}>
          <input placeholder="Логин" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input type="password" placeholder="Пароль" value={password} onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doLogin()} />
          <button className="primary" disabled={busy || !username || !password} onClick={doLogin}>Войти</button>
        </div>
        <hr />
        {!tgStep ? (
          <button disabled={busy} onClick={tgRequest}>Войти через Telegram</button>
        ) : (
          <div className="col" style={{ gap: 8 }}>
            <p className="hint">Код отправлен в Telegram — введите его.</p>
            <input placeholder="Код из Telegram" value={code} onChange={(e) => setCode(e.target.value)} />
            <button className="primary" disabled={busy || !code} onClick={tgVerify}>Подтвердить</button>
          </div>
        )}
      </div>
    </div>
  );
}

function Settings({ setErr }: { setErr: (s: string) => void }) {
  const [s, setS] = useState<SettingsData | null>(null);
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [newPass, setNewPass] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [ver, setVer] = useState<{ version: string; update_status: string; update_requested: boolean } | null>(null);

  useEffect(() => {
    api.getSettings().then((d) => { setS(d); setChatId(d.tg_chat_id ?? ""); setEnabled(d.tg_login_enabled); })
      .catch((e) => setErr(e.message));
    const load = () => api.systemVersion().then(setVer).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  async function doUpdate() {
    try { await api.systemUpdate(); setMsg("Обновление запущено — панель перезапустится через минуту."); }
    catch (e: any) { setErr(e.message); }
  }

  async function save() {
    setMsg(null);
    try {
      const body: any = { tg_chat_id: chatId, tg_login_enabled: enabled };
      if (token) body.tg_bot_token = token;
      if (newPass) body.new_password = newPass;
      const d = await api.updateSettings(body);
      setS(d); setToken(""); setNewPass(""); setMsg("Сохранено ✓");
    } catch (e: any) { setErr(e.message); }
  }

  if (!s) return <p>Загрузка…</p>;
  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <h3>Настройки</h3>
      <div className="col" style={{ gap: 8 }}>
        <b>Telegram</b>
        <input placeholder={s.tg_bot_configured ? "Токен бота (задан, ввод заменит)" : "Токен бота @BotFather"} value={token} onChange={(e) => setToken(e.target.value)} />
        <input placeholder="Ваш chat_id" value={chatId} onChange={(e) => setChatId(e.target.value)} />
        <label className="row"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Разрешить вход в панель через Telegram</label>
        <hr />
        <b>Смена пароля администратора</b>
        <input type="password" placeholder="Новый пароль (пусто — не менять)" value={newPass} onChange={(e) => setNewPass(e.target.value)} />
        <div className="row">
          <button className="primary" onClick={save}>Сохранить</button>
          {msg && <span className="ok">{msg}</span>}
        </div>
        <p className="hint">Уведомления о постинге и упавших прокси приходят в этот chat_id. Бот команды: /queue, /accounts, присланное видео добавляется в библиотеку.</p>
        <hr />
        <b>Обновление</b>
        <div className="row">
          <span className="hint">Версия: {ver?.version ?? "…"}</span>
          <button onClick={doUpdate}>Обновить с GitHub</button>
        </div>
        {ver?.update_status && <span className="hint">Статус: {ver.update_status}</span>}
      </div>
    </div>
  );
}

// ---------------- Accounts ----------------
function Accounts({ accounts, onChange, setErr }: { accounts: Account[]; onChange: () => void; setErr: (s: string) => void }) {
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [proxy, setProxy] = useState("");
  const [login, setLogin] = useState<{ id: number; name: string } | null>(null);

  async function create() {
    try {
      await api.createAccount({ name, platform, proxy_url: proxy || null });
      setName(""); setProxy(""); onChange();
    } catch (e: any) { setErr(e.message); }
  }
  async function onCookies(id: number, f: File | null) {
    if (!f) return;
    try { await api.uploadCookies(id, f); onChange(); } catch (e: any) { setErr(e.message); }
  }

  return (
    <div>
      <div className="card">
        <h3>Новый аккаунт</h3>
        <div className="row">
          <input placeholder="Название (напр. Мой TikTok)" value={name} onChange={(e) => setName(e.target.value)} />
          <select value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
            <option value="tiktok">TikTok</option>
            <option value="youtube">YouTube Shorts</option>
          </select>
          <input placeholder="Прокси http://user:pass@host:port" value={proxy} onChange={(e) => setProxy(e.target.value)} style={{ flex: 2 }} />
          <button className="primary" onClick={create} disabled={!name}>Создать</button>
        </div>
        <p className="hint">У каждого аккаунта — свой прокси (один прокси нельзя назначить двум аккаунтам). Куки (storage_state) — авторизация без пароля.</p>
      </div>

      <div className="list">
        {accounts.map((a) => (
          <div className="card" key={a.id}>
            <div className="row between">
              <div>
                <b>{a.name}</b> <span className="badge">{a.platform}</span>{" "}
                {a.has_cookies ? <span className="ok">куки ✓</span> : <span className="bad">нет кук</span>}{" "}
                {a.proxy_url ? <span className="badge">прокси</span> : <span className="bad">без прокси</span>}{" "}
                {a.proxy_url && a.proxy_ok === true && <span className="ok">IP {a.proxy_ip} ✓</span>}
                {a.proxy_url && a.proxy_ok === false && <span className="bad">прокси ✗</span>}
              </div>
              <button className="danger" onClick={() => api.deleteAccount(a.id).then(onChange)}>Удалить</button>
            </div>
            <div className="row">
              <button className="primary" title="Войти по логину и паролю через прокси аккаунта" onClick={() => setLogin({ id: a.id, name: a.name })}>
                Войти (логин/пароль)
              </button>
              <label className="filebtn">
                Импорт кук (JSON)
                <input type="file" accept="application/json,.json" hidden onChange={(e) => onCookies(a.id, e.target.files?.[0] ?? null)} />
              </label>
              <label className="row" style={{ gap: 4 }} title="Подмена хеша видео перед постингом">
                <input type="checkbox" checked={a.uniqueize} onChange={(e) => api.updateAccount(a.id, { uniqueize: e.target.checked }).then(onChange).catch((x) => setErr(x.message))} />
                уникализация
              </label>
              <ProxyEditor a={a} onChange={onChange} setErr={setErr} />
            </div>
          </div>
        ))}
      </div>

      {login && (
        <LoginModal
          login={login}
          onDone={() => { setLogin(null); onChange(); }}
          onClose={() => setLogin(null)}
          setErr={setErr}
        />
      )}
    </div>
  );
}

function LoginModal({ login, onDone, onClose, setErr }: {
  login: { id: number; name: string };
  onDone: () => void;
  onClose: () => void;
  setErr: (s: string) => void;
}) {
  const [step, setStep] = useState<"creds" | "code" | "captcha">("creds");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const savedRef = useRef(false);

  // Освобождаем серверную сессию входа при закрытии/refresh.
  useEffect(() => {
    const onUnload = () => { if (!savedRef.current) navigator.sendBeacon?.("/api/accounts/login/cancel"); };
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.removeEventListener("beforeunload", onUnload);
      if (!savedRef.current) api.loginCancel().catch(() => {});
    };
  }, []);

  function handleStage(r: LoginStage) {
    if (r.stage === "done") { savedRef.current = true; onDone(); return; }
    if (r.stage === "email_code") { setStep("code"); setMsg("TikTok отправил код на почту — введите его."); return; }
    setStep("captcha"); setScreenshot(r.screenshot); setMsg(r.message || "Неожиданный шаг.");
  }

  async function submitCreds() {
    if (!username || !password) return;
    setBusy(true); setMsg(null);
    try {
      await api.loginCancel().catch(() => {});  // сброс возможной повисшей сессии
      handleStage(await api.loginCredentials(login.id, { username, password }));
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }
  async function submitCode() {
    if (!code) return;
    setBusy(true); setMsg(null);
    try {
      handleStage(await api.loginCode(login.id, code));
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }
  async function cancel() {
    try { await api.loginCancel(); } catch {}
    onClose();
  }

  return (
    <div className="modal-overlay" onClick={cancel}>
      <div className="modal login-modal" onClick={(e) => e.stopPropagation()}>
        <div className="row between">
          <b>Вход: {login.name}</b>
          <button className="danger" onClick={cancel}>Закрыть</button>
        </div>

        {step === "creds" && (
          <div className="col" style={{ gap: 8 }}>
            <p className="hint">Логин/пароль нужны один раз для авторизации; вход идёт через прокси аккаунта, затем — код с почты. Пароль не сохраняется.</p>
            <input placeholder="Логин / email / телефон" value={username} onChange={(e) => setUsername(e.target.value)} />
            <input type="password" placeholder="Пароль" value={password} onChange={(e) => setPassword(e.target.value)} />
            <button className="primary" disabled={busy || !username || !password} onClick={submitCreds}>
              {busy ? "Вхожу…" : "Войти"}
            </button>
          </div>
        )}

        {step === "code" && (
          <div className="col" style={{ gap: 8 }}>
            {msg && <p className="hint">{msg}</p>}
            <input placeholder="Код с почты" value={code} onChange={(e) => setCode(e.target.value)} />
            <button className="primary" disabled={busy || !code} onClick={submitCode}>
              {busy ? "Проверяю…" : "Подтвердить код"}
            </button>
          </div>
        )}

        {step === "captcha" && (
          <div className="col" style={{ gap: 8 }}>
            {msg && <p className="bad">{msg}</p>}
            {screenshot && <img className="login-shot" src={screenshot} alt="Скриншот шага TikTok" />}
            <p className="hint">Капчу в панели решить нельзя. Пройди вход в антидетект-браузере через этот же прокси и импортируй куки (кнопка «Импорт кук»).</p>
          </div>
        )}
      </div>
    </div>
  );
}

function ProxyEditor({ a, onChange, setErr }: { a: Account; onChange: () => void; setErr: (s: string) => void }) {
  const [val, setVal] = useState(a.proxy_url ?? "");
  const [checking, setChecking] = useState(false);
  const [ipInfo, setIpInfo] = useState<string | null>(null);

  async function check() {
    setChecking(true);
    setIpInfo(null);
    try {
      const r = await api.checkProxy(a.id);
      setIpInfo(r.ok ? `IP: ${r.ip}` : `✗ ${r.error}`);
    } catch (e: any) {
      setIpInfo(`✗ ${e.message}`);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="col" style={{ flex: 2, gap: 4 }}>
      <div className="row">
        <input placeholder="Прокси http://user:pass@host:port" value={val} onChange={(e) => setVal(e.target.value)} style={{ flex: 1 }} />
        <button onClick={() => api.updateAccount(a.id, { proxy_url: val || null }).then(onChange).catch((e) => setErr(e.message))}>Сохранить</button>
        <button onClick={check} disabled={checking || !a.proxy_url}>{checking ? "Проверка…" : "Проверить IP"}</button>
      </div>
      {ipInfo && <span className={ipInfo.startsWith("IP:") ? "ok" : "bad"}>{ipInfo}</span>}
    </div>
  );
}

// ---------------- Videos ----------------
function Videos({ videos, onChange, setErr }: { videos: Video[]; onChange: () => void; setErr: (s: string) => void }) {
  const [busy, setBusy] = useState(false);
  async function upload(f: File | null) {
    if (!f) return;
    setBusy(true);
    try { await api.uploadVideo(f); onChange(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <div>
      <div className="card">
        <label className="filebtn big">
          {busy ? "Загрузка…" : "＋ Загрузить видео"}
          <input type="file" accept="video/*" hidden disabled={busy} onChange={(e) => upload(e.target.files?.[0] ?? null)} />
        </label>
      </div>
      <div className="grid">
        {videos.map((v) => (
          <div className="card vcard" key={v.id}>
            <video src={api.videoFileUrl(v.id)} controls muted className="thumb" />
            <div className="row between">
              <span title={v.title}>{v.title}</span>
              <button className="danger" onClick={() => api.deleteVideo(v.id).then(onChange)}>✕</button>
            </div>
            <small>{v.width && v.height ? `${v.width}×${v.height}` : "?"} {v.duration ? `· ${v.duration.toFixed(1)}с` : ""}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------- Banners ----------------
function Banners({ banners, onChange, setErr }: { banners: Banner[]; onChange: () => void; setErr: (s: string) => void }) {
  const [name, setName] = useState("");
  async function upload(f: File | null) {
    if (!f) return;
    try { await api.uploadBanner(f, name || f.name); setName(""); onChange(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <div>
      <div className="card">
        <div className="row">
          <input placeholder="Имя баннера" value={name} onChange={(e) => setName(e.target.value)} />
          <label className="filebtn">
            ＋ Загрузить баннер (PNG/видео)
            <input type="file" accept="image/*,video/*" hidden onChange={(e) => upload(e.target.files?.[0] ?? null)} />
          </label>
        </div>
        <p className="hint">Статичная картинка (PNG с прозрачностью) или зацикленное видео — позицию настроите на вкладке «Баннер+превью».</p>
      </div>
      <div className="grid">
        {banners.map((b) => (
          <div className="card vcard" key={b.id}>
            {b.type === "image" ? (
              <img src={api.bannerFileUrl(b.id)} className="thumb" />
            ) : (
              <video src={api.bannerFileUrl(b.id)} autoPlay muted loop className="thumb" />
            )}
            <div className="row between">
              <span>{b.name} <span className="badge">{b.type}</span></span>
              <button className="danger" onClick={() => api.deleteBanner(b.id).then(onChange)}>✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------- Post form ----------------
function PostForm({ accounts, videos, banners, onCreated, setErr }: {
  accounts: Account[]; videos: Video[]; banners: Banner[]; onCreated: () => void; setErr: (s: string) => void;
}) {
  const [accountId, setAccountId] = useState<number | null>(null);
  const [videoId, setVideoId] = useState<number | null>(null);
  const [bannerId, setBannerId] = useState<number | null>(null);
  const [caption, setCaption] = useState("");
  const [when, setWhen] = useState("");

  async function submit() {
    if (!accountId || !videoId) { setErr("Выберите аккаунт и видео"); return; }
    try {
      await api.createJob({
        account_id: accountId, video_id: videoId, banner_id: bannerId,
        caption, scheduled_at: when ? new Date(when).toISOString() : null,
      });
      onCreated();
    } catch (e: any) { setErr(e.message); }
  }

  return (
    <div className="card">
      <h3>Новый пост</h3>
      <div className="formgrid">
        <label>Аккаунт
          <select value={accountId ?? ""} onChange={(e) => setAccountId(Number(e.target.value) || null)}>
            <option value="">— выбрать —</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.platform}){a.has_cookies ? "" : " ⚠без кук"}</option>)}
          </select>
        </label>
        <label>Видео
          <select value={videoId ?? ""} onChange={(e) => setVideoId(Number(e.target.value) || null)}>
            <option value="">— выбрать —</option>
            {videos.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
          </select>
        </label>
        <label>Баннер (необязательно)
          <select value={bannerId ?? ""} onChange={(e) => setBannerId(Number(e.target.value) || null)}>
            <option value="">— без баннера —</option>
            {banners.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>
        <label>Время публикации (пусто = сразу)
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </label>
      </div>
      <label>Описание / подпись
        <textarea rows={3} value={caption} onChange={(e) => setCaption(e.target.value)} placeholder="Текст поста, #хэштеги" />
      </label>
      <button className="primary big" onClick={submit}>Поставить в очередь</button>
    </div>
  );
}

// ---------------- Jobs ----------------
function Jobs({ jobs, accounts, videos, onChange, setErr }: {
  jobs: Job[]; accounts: Account[]; videos: Video[]; onChange: () => void; setErr: (s: string) => void;
}) {
  const accName = (id: number) => accounts.find((a) => a.id === id)?.name ?? `#${id}`;
  const vidName = (id: number) => videos.find((v) => v.id === id)?.title ?? `#${id}`;
  return (
    <div className="list">
      {jobs.length === 0 && <div className="card">Пока нет задач. Создайте пост на вкладке «Новый пост».</div>}
      {jobs.map((jb) => (
        <div className="card" key={jb.id}>
          <div className="row between">
            <div>
              <b>#{jb.id}</b> {accName(jb.account_id)} ← {vidName(jb.video_id)}{" "}
              <StatusBadge s={jb.status} />
              {jb.scheduled_at && <span className="badge">⏰ {new Date(jb.scheduled_at).toLocaleString()}</span>}
            </div>
            <div className="row">
              {jb.status === "failed" && <button onClick={() => api.retryJob(jb.id).then(onChange).catch((e) => setErr(e.message))}>Повторить</button>}
              <button className="danger" onClick={() => api.deleteJob(jb.id).then(onChange)}>✕</button>
            </div>
          </div>
          {jb.caption && <div className="caption">{jb.caption}</div>}
          {jb.error && <div className="joberr">{jb.error}</div>}
          {jb.log && <details><summary>Лог</summary><pre>{jb.log}</pre></details>}
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ s }: { s: Job["status"] }) {
  const map: Record<Job["status"], string> = {
    pending: "ожидает", rendering: "рендер баннера", uploading: "постинг", done: "готово", failed: "ошибка",
  };
  return <span className={`status ${s}`}>{map[s]}</span>;
}
