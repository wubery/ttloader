import { useEffect, useRef, useState } from "react";
import { api, Account, Banner, Job, Platform, Video } from "./api";
import { BannerEditor } from "./BannerEditor";

type Tab = "accounts" | "videos" | "banners" | "editor" | "post" | "jobs";

export function App() {
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

  return (
    <div className="app">
      <header>
        <h1>🎬 Video Poster</h1>
        <nav>
          {(["jobs", "post", "editor", "accounts", "videos", "banners"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "tab active" : "tab"} onClick={() => setTab(t)}>
              {tabLabel(t)}
            </button>
          ))}
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
      </main>
    </div>
  );
}

function tabLabel(t: Tab) {
  return { jobs: "Очередь", post: "＋ Новый пост", editor: "Баннер+превью", accounts: "Аккаунты", videos: "Видео", banners: "Баннеры" }[t];
}

// ---------------- Accounts ----------------
function Accounts({ accounts, onChange, setErr }: { accounts: Account[]; onChange: () => void; setErr: (s: string) => void }) {
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [proxy, setProxy] = useState("");
  const [login, setLogin] = useState<{ id: number; name: string; url: string } | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);

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
  async function startLogin(a: Account) {
    setLoginBusy(true);
    try {
      let r;
      try {
        r = await api.loginStart(a.id);
      } catch (e) {
        // Возможно, повисла прошлая сессия (окно закрыли/панель обновили без отмены).
        // Сбрасываем её и пробуем ещё раз.
        await api.loginCancel().catch(() => {});
        r = await api.loginStart(a.id);
      }
      setLogin({ id: a.id, name: a.name, url: r.novnc_url });
    } catch (e: any) { setErr(e.message); }
    finally { setLoginBusy(false); }
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
                {a.proxy_url ? <span className="badge">прокси</span> : <span className="bad">без прокси</span>}
              </div>
              <button className="danger" onClick={() => api.deleteAccount(a.id).then(onChange)}>Удалить</button>
            </div>
            <div className="row">
              <button className="primary" disabled={loginBusy} title={a.proxy_url ? "Войти через прокси аккаунта" : "Войти без прокси — через собственный IP сервера (твой домашний IP)"} onClick={() => startLogin(a)}>
                {loginBusy ? "Открываю…" : a.proxy_url ? "Войти в браузере" : "Войти (через IP сервера)"}
              </button>
              <label className="filebtn">
                Импорт кук (JSON)
                <input type="file" accept="application/json,.json" hidden onChange={(e) => onCookies(a.id, e.target.files?.[0] ?? null)} />
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
  login: { id: number; name: string; url: string };
  onDone: () => void;
  onClose: () => void;
  setErr: (s: string) => void;
}) {
  const [saving, setSaving] = useState(false);
  const savedRef = useRef(false);

  // Если окно входа закрыли/размонтировали не через «Готово» — освобождаем сессию,
  // чтобы она не «повисла» на сервере. beforeunload ловит закрытие вкладки/refresh.
  useEffect(() => {
    const onUnload = () => { if (!savedRef.current) navigator.sendBeacon?.("/api/accounts/login/cancel"); };
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.removeEventListener("beforeunload", onUnload);
      if (!savedRef.current) api.loginCancel().catch(() => {});
    };
  }, []);

  async function save() {
    setSaving(true);
    try {
      await api.loginFinish(login.id);
      savedRef.current = true;
      onDone();
    } catch (e: any) { setErr(e.message); setSaving(false); }
  }
  async function cancel() {
    try { await api.loginCancel(); } catch {}
    onClose();
  }

  return (
    <div className="modal-overlay" onClick={cancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="row between">
          <b>Вход: {login.name}</b>
          <div className="row">
            <button className="primary" onClick={save} disabled={saving}>{saving ? "Сохраняю…" : "Готово — сохранить куки"}</button>
            <button className="danger" onClick={cancel}>Отмена</button>
          </div>
        </div>
        <p className="hint">Залогинься в открывшемся браузере (пароль/SMS/капча — как обычно). Трафик идёт через прокси аккаунта. Когда увидишь, что вошёл — нажми «Готово».</p>
        <iframe className="novnc" src={login.url} title="Вход в аккаунт" />
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
