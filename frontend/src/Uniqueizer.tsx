import { useEffect, useMemo, useState } from "react";
import { api, AdClip, Background, Hook, OverlayAsset, UniqProfile, Video } from "./api";

/* ================================================================
   Вкладка «Уникализация»: профили + библиотеки хуков и оверлеев.

   Каждый числовой параметр — диапазон [от, до]. Авто = панель берёт
   случайное значение из диапазона на каждый рендер; вручную = ставишь
   одинаковые границы, и значение фиксируется.
   ================================================================ */

type Params = Record<string, any>;

const PRESET_NAMES: Record<string, string> = {
  warm: "тёплый",
  cool: "холодный",
  contrast: "контраст",
  fade: "выцветший",
  vivid: "сочный",
};

/** Готовые наборы: заполняют диапазоны, дальше их можно править руками. */
const STRENGTH: Record<string, Params> = {
  Мягкий: {
    trim: { on: true, percent: [0, 4], from: "both" },
    speed: { on: true, factor: [0.98, 1.02] },
    crop: { on: true, px: [1, 4] },
    rotate: { on: true, deg: [0.5, 1.5], flip180: false },
    color: { on: true, presets: ["warm", "cool"] },
    noise: { on: false, strength: [1, 2] },
    canvas: { on: true, w: 1080, h: 1920, border_px: [8, 12], bg: "blur", color: "#000000" },
  },
  Средний: {
    trim: { on: true, percent: [3, 8], from: "both" },
    speed: { on: true, factor: [0.95, 1.05] },
    crop: { on: true, px: [2, 8] },
    rotate: { on: true, deg: [1, 3], flip180: false },
    color: { on: true, presets: ["warm", "cool", "contrast", "fade", "vivid"] },
    noise: { on: true, strength: [1, 2] },
    canvas: { on: true, w: 1080, h: 1920, border_px: [10, 20], bg: "blur", color: "#000000" },
  },
  Агрессивный: {
    trim: { on: true, percent: [6, 10], from: "both" },
    speed: { on: true, factor: [0.9, 1.1] },
    crop: { on: true, px: [5, 10] },
    rotate: { on: true, deg: [2, 3], flip180: false },
    color: { on: true, presets: ["warm", "cool", "contrast", "fade", "vivid"] },
    noise: { on: true, strength: [2, 3] },
    canvas: { on: true, w: 1080, h: 1920, border_px: [14, 20], bg: "blur", color: "#000000" },
  },
};

function Range({ label, unit, block, field, min, max, step = 1, onChange }: {
  label: string; unit?: string; block: Params; field: string;
  min: number; max: number; step?: number; onChange: (v: [number, number]) => void;
}) {
  const [lo, hi] = (block?.[field] ?? [min, max]) as [number, number];
  const fixed = lo === hi;
  return (
    <div>
      <label className="form-label vp mb-1">
        {label} {fixed ? <span className="badge-vp badge-vp-muted">точно {lo}{unit}</span>
                       : <span className="badge-vp badge-vp-info">{lo}–{hi}{unit}</span>}
      </label>
      <div className="d-flex align-items-center gap-2">
        <input className="form-control vp form-control-sm" type="number" style={{ width: 82 }}
               min={min} max={max} step={step} value={lo}
               onChange={(e) => onChange([Number(e.target.value), hi])} />
        <span className="fs-sm text-muted">…</span>
        <input className="form-control vp form-control-sm" type="number" style={{ width: 82 }}
               min={min} max={max} step={step} value={hi}
               onChange={(e) => onChange([lo, Number(e.target.value)])} />
        <button className="btn btn-vp-outline btn-sm" title="Зафиксировать значение (ручной режим)"
                onClick={() => onChange([lo, lo])}>=</button>
      </div>
    </div>
  );
}

function Block({ title, hint, on, onToggle, children }: {
  title: string; hint?: string; on: boolean; onToggle: (v: boolean) => void; children?: React.ReactNode;
}) {
  return (
    <div className="vp-card" style={{ marginBottom: 12 }}>
      <div className="d-flex align-items-center justify-content-between">
        <div>
          <b className="fs-sm">{title}</b>
          {hint && <div className="fs-sm text-muted">{hint}</div>}
        </div>
        <div className="form-check form-switch mb-0">
          <input className="form-check-input" type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} />
        </div>
      </div>
      {on && <div className="editor-controls mt-3">{children}</div>}
    </div>
  );
}

export function Uniqueizer({ videos, onChange }: { videos: Video[]; onChange?: () => void }) {
  const [profiles, setProfiles] = useState<UniqProfile[]>([]);
  const [hooks, setHooks] = useState<Hook[]>([]);
  const [assets, setAssets] = useState<OverlayAsset[]>([]);
  const [backgrounds, setBackgrounds] = useState<Background[]>([]);
  const [ads, setAds] = useState<AdClip[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [draft, setDraft] = useState<Params>({});
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const current = useMemo(() => profiles.find((p) => p.id === sel) ?? null, [profiles, sel]);

  async function reload() {
    const [p, h, a, bg, ad] = await Promise.all([
      api.uniqProfiles(), api.hooks(), api.overlayAssets(), api.backgrounds(), api.ads(),
    ]);
    setProfiles(p); setHooks(h); setAssets(a); setBackgrounds(bg); setAds(ad);
    onChange?.();   // селекты профиля в других вкладках берут список из Dashboard
    if (sel === null && p.length) select(p[0]);
  }
  useEffect(() => { reload().catch((e) => setMsg(e.message)); }, []);

  function select(p: UniqProfile) {
    setSel(p.id); setDraft(JSON.parse(JSON.stringify(p.params))); setName(p.name); setPreviewUrl(null);
  }

  function patch(block: string, changes: Params) {
    setDraft((d) => ({ ...d, [block]: { ...(d[block] ?? {}), ...changes } }));
  }

  async function createProfile() {
    const defaults = await api.uniqDefaults();
    const p = await api.createUniqProfile({ name: `Профиль ${profiles.length + 1}`, params: defaults });
    setProfiles((x) => [p, ...x]); select(p); onChange?.();
  }

  async function save() {
    if (!current) return;
    setBusy(true); setMsg(null);
    try {
      const p = await api.updateUniqProfile(current.id, { name, params: draft });
      setProfiles((x) => x.map((i) => (i.id === p.id ? p : i)));
      onChange?.();
      setMsg("Профиль сохранён");
    } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  }

  async function makeDefault() {
    if (!current) return;
    await api.updateUniqProfile(current.id, { is_default: true });
    await reload();
    setMsg("Профиль назначен профилем по умолчанию");
  }

  async function remove() {
    if (!current) return;
    await api.deleteUniqProfile(current.id);
    setSel(null); setDraft({}); await reload();
  }

  function preview() {
    if (!current || !videos.length) return;
    setBusy(true); setMsg("Собираю предпросмотр — это несколько секунд…");
    // сохраняем черновик, иначе предпросмотр покажет старые настройки
    api.updateUniqProfile(current.id, { name, params: draft })
      .then(() => { setPreviewUrl(api.uniqPreviewUrl(current.id, videos[0].id) + `&t=${Date.now()}`); setMsg(null); })
      .catch((e) => setMsg(e.message))
      .finally(() => setBusy(false));
  }

  return (
    <div>
      {msg && <div className="vp-card fs-sm">{msg}</div>}

      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-shuffle me-2 text-accent" />Профили уникализации</h3>
          <button className="btn btn-vp btn-sm" onClick={() => createProfile().catch((e) => setMsg(e.message))}>
            <i className="bi bi-plus-lg me-1" />Новый профиль
          </button>
        </div>
        <div className="d-flex gap-2 flex-wrap">
          {profiles.map((p) => (
            <button key={p.id} className={`btn btn-sm ${p.id === sel ? "btn-vp" : "btn-vp-outline"}`}
                    onClick={() => select(p)}>
              {p.name}{p.is_default && <span className="badge-vp badge-vp-success ms-2">по умолчанию</span>}
            </button>
          ))}
          {profiles.length === 0 && <span className="fs-sm text-muted">Профилей нет — создайте первый.</span>}
        </div>
      </div>

      {current && (
        <>
          <div className="vp-card">
            <div className="d-flex align-items-end gap-2 flex-wrap">
              <div style={{ flex: "0 0 260px" }}>
                <label className="form-label vp">Название профиля</label>
                <input className="form-control vp" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="d-flex gap-2 flex-wrap">
                {Object.keys(STRENGTH).map((k) => (
                  <button key={k} className="btn btn-vp-outline btn-sm"
                          onClick={() => setDraft((d) => ({ ...d, ...JSON.parse(JSON.stringify(STRENGTH[k])) }))}>
                    {k}
                  </button>
                ))}
              </div>
              <div className="flex-grow-1" />
              <button className="btn btn-vp btn-sm" disabled={busy} onClick={save}>
                <i className="bi bi-check-lg me-1" />Сохранить
              </button>
              <button className="btn btn-vp-outline btn-sm" disabled={busy || !videos.length} onClick={preview}>
                <i className="bi bi-eye me-1" />Предпросмотр
              </button>
              <button className="btn btn-vp-outline btn-sm" onClick={makeDefault}>По умолчанию</button>
              <button className="btn btn-vp-danger btn-sm" onClick={() => remove().catch((e) => setMsg(e.message))}>
                <i className="bi bi-trash" />
              </button>
            </div>
            <div className="form-text fs-sm">
              Значения берутся случайно из диапазона на каждый рендер — поэтому у каждого аккаунта
              получается своя копия. Кнопка «=» фиксирует значение (ручной режим).
            </div>
          </div>

          {previewUrl && (
            <div className="vp-card">
              <div className="vp-card-header"><h3><i className="bi bi-play-btn me-2 text-accent" />Предпросмотр</h3></div>
              <video src={previewUrl} controls style={{ maxHeight: 420, borderRadius: 8 }} />
            </div>
          )}

          <Block title="Обрезка по длине" hint="срезает часть ролика — меняет длительность и границы сцен"
                 on={!!draft.trim?.on} onToggle={(v) => patch("trim", { on: v })}>
            <Range label="Сколько срезать" unit="%" block={draft.trim} field="percent" min={0} max={30}
                   onChange={(v) => patch("trim", { percent: v })} />
            <div>
              <label className="form-label vp mb-1">Откуда</label>
              <select className="form-select vp form-select-sm" value={draft.trim?.from ?? "both"}
                      onChange={(e) => patch("trim", { from: e.target.value })}>
                <option value="both">с обоих концов</option>
                <option value="start">с начала</option>
                <option value="end">с конца</option>
              </select>
            </div>
          </Block>

          <Block title="Скорость" hint="видео и звук меняются синхронно; голос слегка сдвигается по тону"
                 on={!!draft.speed?.on} onToggle={(v) => patch("speed", { on: v })}>
            <Range label="Множитель" block={draft.speed} field="factor" min={0.5} max={2} step={0.01}
                   onChange={(v) => patch("speed", { factor: v })} />
          </Block>

          <Block title="Кроп по краям" on={!!draft.crop?.on} onToggle={(v) => patch("crop", { on: v })}>
            <Range label="Срез с каждой стороны" unit="px" block={draft.crop} field="px" min={0} max={40}
                   onChange={(v) => patch("crop", { px: v })} />
          </Block>

          <Block title="Поворот" hint="наклон компенсируется масштабом, чёрных углов не будет"
                 on={!!draft.rotate?.on} onToggle={(v) => patch("rotate", { on: v })}>
            <Range label="Угол наклона" unit="°" block={draft.rotate} field="deg" min={0} max={10} step={0.5}
                   onChange={(v) => patch("rotate", { deg: v })} />
            <div>
              <label className="form-label vp mb-1">Переворот на 180°</label>
              <div className="form-check form-switch">
                <input className="form-check-input" type="checkbox" checked={!!draft.rotate?.flip180}
                       onChange={(e) => patch("rotate", { flip180: e.target.checked })} />
                <label className="form-check-label fs-sm">включить (зритель заметит)</label>
              </div>
            </div>
          </Block>

          <Block title="Цветокоррекция" on={!!draft.color?.on} onToggle={(v) => patch("color", { on: v })}>
            <div style={{ gridColumn: "1 / -1" }}>
              <label className="form-label vp mb-1">Пресеты (панель берёт случайный из выбранных)</label>
              <div className="d-flex gap-3 flex-wrap">
                {Object.entries(PRESET_NAMES).map(([key, label]) => {
                  const list: string[] = draft.color?.presets ?? [];
                  return (
                    <label key={key} className="d-flex align-items-center gap-1 fs-sm" style={{ cursor: "pointer" }}>
                      <input type="checkbox" className="form-check-input mt-0" checked={list.includes(key)}
                             onChange={(e) => patch("color", {
                               presets: e.target.checked ? [...list, key] : list.filter((x) => x !== key),
                             })} />
                      {label}
                    </label>
                  );
                })}
              </div>
            </div>
          </Block>

          <Block title="Микро-шум" hint="меняет каждый пиксель; сильные значения заметны на однотонном фоне"
                 on={!!draft.noise?.on} onToggle={(v) => patch("noise", { on: v })}>
            <Range label="Сила" block={draft.noise} field="strength" min={1} max={10}
                   onChange={(v) => patch("noise", { strength: v })} />
          </Block>

          <Block title="Холст 1080×1920 и рамка" on={!!draft.canvas?.on} onToggle={(v) => patch("canvas", { on: v })}>
            <Range label="Ширина рамки" unit="px" block={draft.canvas} field="border_px" min={0} max={80}
                   onChange={(v) => patch("canvas", { border_px: v })} />
            <div>
              <label className="form-label vp mb-1">Фон рамки</label>
              <select className="form-select vp form-select-sm" value={draft.canvas?.bg ?? "blur"}
                      onChange={(e) => patch("canvas", { bg: e.target.value })}>
                <option value="blur">размытая копия кадра</option>
                <option value="color">сплошной цвет</option>
                <option value="image">своя картинка или видео</option>
              </select>
            </div>
            {draft.canvas?.bg === "image" && (
              <div>
                <label className="form-label vp mb-1">Файл фона</label>
                <select className="form-select vp form-select-sm" value={draft.canvas?.bg_asset_id ?? ""}
                        onChange={(e) => patch("canvas", { bg_asset_id: Number(e.target.value) || null })}>
                  <option value="">случайный из библиотеки</option>
                  {backgrounds.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </div>
            )}
            {draft.canvas?.bg === "color" && (
              <div>
                <label className="form-label vp mb-1">Цвет</label>
                <input type="color" className="form-control form-control-color" value={draft.canvas?.color ?? "#000000"}
                       onChange={(e) => patch("canvas", { color: e.target.value })} />
              </div>
            )}
          </Block>

          <Block title="PNG-оверлей на весь кадр" on={!!draft.overlay?.on} onToggle={(v) => patch("overlay", { on: v })}>
            <div>
              <label className="form-label vp mb-1">Файл</label>
              <select className="form-select vp form-select-sm" value={draft.overlay?.asset_id ?? ""}
                      onChange={(e) => patch("overlay", { asset_id: Number(e.target.value) || null })}>
                <option value="">случайный из библиотеки</option>
                {assets.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            <Range label="Прозрачность" block={draft.overlay} field="opacity" min={0} max={1} step={0.01}
                   onChange={(v) => patch("overlay", { opacity: v })} />
          </Block>

          <Block title="Хук в начале" hint="заставка проходит те же операции со своими случайными значениями"
                 on={!!draft.hook?.on} onToggle={(v) => patch("hook", { on: v })}>
            <div>
              <label className="form-label vp mb-1">Ролик</label>
              <select className="form-select vp form-select-sm" value={draft.hook?.asset_id ?? ""}
                      onChange={(e) => patch("hook", { asset_id: Number(e.target.value) || null })}>
                <option value="">случайный из библиотеки</option>
                {hooks.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
              </select>
            </div>
          </Block>

          <Block title="Реклама внутри ролика"
                 hint="видео прерывается в случайной точке средней трети, играет ролик, затем продолжение"
                 on={!!draft.ad?.on} onToggle={(v) => patch("ad", { on: v })}>
            <div>
              <label className="form-label vp mb-1">Ролик</label>
              <select className="form-select vp form-select-sm" value={draft.ad?.asset_id ?? ""}
                      onChange={(e) => patch("ad", { asset_id: Number(e.target.value) || null })}>
                <option value="">случайный из библиотеки</option>
                {ads.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
          </Block>

          <Block title="Стереть метаданные" hint="убирает исходные теги и пишет случайные"
                 on={draft.metadata?.on !== false} onToggle={(v) => patch("metadata", { on: v })} />
        </>
      )}

      <MediaLibrary title="Хуки" icon="bi-lightning-charge"
                    hint="Короткие заставки, которые клеятся в начало ролика."
                    accept="video/*" items={hooks}
                    upload={(f, n) => api.uploadHook(f, n)} remove={(id) => api.deleteHook(id)}
                    fileUrl={(id) => api.hookFileUrl(id)} isVideo onChange={reload} />

      <MediaLibrary title="Реклама" icon="bi-megaphone"
                    hint="Короткие ролики, которые вставляются внутрь части видео."
                    accept="video/*" items={ads}
                    upload={(f, n) => api.uploadAd(f, n)} remove={(id) => api.deleteAd(id)}
                    fileUrl={(id) => api.adFileUrl(id)} isVideo onChange={reload} />

      <MediaLibrary title="Фоны" icon="bi-easel"
                    hint="Картинка или видео под рамку: видно по краям вокруг вписанного ролика."
                    accept="image/*,video/*" items={backgrounds}
                    upload={(f, n) => api.uploadBackground(f, n)} remove={(id) => api.deleteBackground(id)}
                    fileUrl={(id) => api.backgroundFileUrl(id)} onChange={reload} />

      <MediaLibrary title="Оверлеи" icon="bi-layers"
                    hint="PNG с прозрачностью на весь кадр: текстуры, рамки, лёгкие засветки."
                    accept="image/png,image/webp" items={assets}
                    upload={(f, n) => api.uploadOverlayAsset(f, n)} remove={(id) => api.deleteOverlayAsset(id)}
                    fileUrl={(id) => api.overlayFileUrl(id)} onChange={reload} />
    </div>
  );
}

function MediaLibrary({ title, icon, hint, accept, items, upload, remove, fileUrl, isVideo, onChange }: {
  title: string; icon: string; hint: string; accept: string;
  items: { id: number; name: string; is_video?: boolean }[];
  upload: (f: File, name: string) => Promise<any>;
  remove: (id: number) => Promise<any>;
  fileUrl: (id: number) => string;
  /** Библиотека целиком из видео (хуки, реклама). У фонов тип свой у каждого файла. */
  isVideo?: boolean;
  onChange: () => Promise<void> | void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  return (
    <div className="vp-card">
      <div className="vp-card-header"><h3><i className={`bi ${icon} me-2 text-accent`} />{title}</h3></div>
      {err && <div className="alert alert-danger py-2 fs-sm">{err}</div>}
      <div className="d-flex align-items-end gap-3 flex-wrap">
        <div style={{ flex: "0 0 220px" }}>
          <label className="form-label vp">Название</label>
          <input className="form-control vp" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <label className="btn btn-vp mb-0" style={{ cursor: "pointer" }}>
          {busy ? <><span className="spinner-border spinner-border-sm me-2" />Загрузка…</> : <><i className="bi bi-upload me-1" />Загрузить</>}
          <input type="file" accept={accept} hidden disabled={busy} onChange={async (e) => {
            const f = e.target.files?.[0]; if (!f) return;
            setBusy(true); setErr(null);
            try { await upload(f, name || f.name); setName(""); await onChange(); }
            catch (x: any) { setErr(x.message); } finally { setBusy(false); }
          }} />
        </label>
        <span className="fs-sm text-muted">{hint}</span>
      </div>
      <div className="vp-grid mt-3">
        {items.map((it) => (
          <div className="vp-media-card" key={it.id}>
            {/* preload+controls обязательны: без них браузер не декодирует первый кадр
                и вместо превью виден чёрный прямоугольник */}
            {(isVideo || it.is_video)
              ? <video src={fileUrl(it.id)} className="thumb" preload="metadata" muted playsInline controls />
              : <img src={fileUrl(it.id)} className="thumb" alt={it.name} />}
            <div className="info"><div className="title" title={it.name}>{it.name}</div></div>
            <div className="actions">
              <button className="btn btn-vp-danger btn-sm"
                      onClick={async () => { await remove(it.id); await onChange(); }}>
                <i className="bi bi-trash" />
              </button>
            </div>
          </div>
        ))}
        {items.length === 0 && <div className="fs-sm text-muted">Пока пусто.</div>}
      </div>
    </div>
  );
}
