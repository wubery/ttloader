import { useEffect, useRef, useState } from "react";
import { api, Account, Banner, Motion, Overlay, Video } from "./api";

/**
 * Редактор слоёв: несколько баннеров + текстовые надписи поверх видео.
 * Позиции/размеры хранятся в долях кадра (0..1), поэтому одинаково ложатся на
 * видео любого разрешения. Всё, что видно в превью, вжигается в видео на бэкенде
 * (ffmpeg overlay + drawtext) — см. services/media.render_with_overlays.
 */
interface Props {
  videos: Video[];
  banners: Banner[];
  accounts?: Account[];
  onSaved?: (b: Banner) => void;
  onPosted?: () => void;
}

type Layer =
  | {
      uid: number;
      kind: "banner";
      bannerId: number;
      x: number;
      y: number;
      scale: number;
      opacity: number;
      motion: Motion;
      motionSpeed: number;
      start?: number;
      end?: number;
    }
  | {
      uid: number;
      kind: "text";
      text: string;
      x: number;
      y: number;
      fontSize: number; // доля высоты кадра
      color: string;
      opacity: number;
      start?: number;
      end?: number;
    };

export function BannerEditor({ videos, banners, accounts = [], onSaved, onPosted }: Props) {
  const [videoId, setVideoId] = useState<number | null>(videos[0]?.id ?? null);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [videoDuration, setVideoDuration] = useState(0);
  const [showPublish, setShowPublish] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  // высота превью в пикселях — чтобы размер текста в превью совпадал с результатом
  const [boxH, setBoxH] = useState(0);

  const boxRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const uidRef = useRef(1);
  const drag = useRef<{ uid: number; mode: "move" | "resize"; sx: number; sy: number; ox: number; oy: number; os: number } | null>(null);

  const video = videos.find((v) => v.id === videoId) || null;
  const sel = layers.find((l) => l.uid === selected) || null;

  useEffect(() => { if (videos.length && videoId === null) setVideoId(videos[0].id); }, [videos]);

  // Длительность видео — для таймлайна слоёв
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    const onLoaded = () => setVideoDuration(el.duration || 0);
    el.addEventListener("loadedmetadata", onLoaded);
    return () => el.removeEventListener("loadedmetadata", onLoaded);
  }, [videoId]);

  // Следим за высотой превью: размер текста задаём в пикселях от неё,
  // чтобы превью совпадало с тем, что вожжёт ffmpeg (доля высоты кадра).
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const update = () => setBoxH(el.getBoundingClientRect().height);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  function patch(uid: number, data: Partial<Layer>) {
    setLayers((prev) => prev.map((l) => (l.uid === uid ? ({ ...l, ...data } as Layer) : l)));
    setMsg(null);
  }

  function addBanner(bannerId: number) {
    const b = banners.find((x) => x.id === bannerId);
    if (!b) return;
    const uid = uidRef.current++;
    setLayers((prev) => [...prev, {
      uid, kind: "banner", bannerId,
      x: b.x, y: b.y, scale: b.scale, opacity: b.opacity,
      motion: b.motion ?? "none", motionSpeed: b.motion_speed ?? 1,
    }]);
    setSelected(uid);
  }

  function addText() {
    const uid = uidRef.current++;
    setLayers((prev) => [...prev, {
      uid, kind: "text", text: "Мой текст",
      x: 0.1, y: 0.8, fontSize: 0.06, color: "#ffffff", opacity: 1,
    }]);
    setSelected(uid);
  }

  function removeLayer(uid: number) {
    setLayers((prev) => prev.filter((l) => l.uid !== uid));
    if (selected === uid) setSelected(null);
  }

  function move(uid: number, dir: -1 | 1) {
    setLayers((prev) => {
      const i = prev.findIndex((l) => l.uid === uid);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  // --- перетаскивание слоёв в превью ---
  function onPointerDown(e: React.PointerEvent, uid: number, mode: "move" | "resize") {
    e.preventDefault();
    e.stopPropagation();
    const l = layers.find((x) => x.uid === uid);
    if (!l) return;
    setSelected(uid);
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = {
      uid, mode, sx: e.clientX, sy: e.clientY,
      ox: l.x, oy: l.y, os: l.kind === "banner" ? l.scale : l.fontSize,
    };
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d || !boxRef.current) return;
    const rect = boxRef.current.getBoundingClientRect();
    const dx = (e.clientX - d.sx) / rect.width;
    const dy = (e.clientY - d.sy) / rect.height;
    if (d.mode === "move") {
      patch(d.uid, { x: clamp(d.ox + dx, 0, 0.98), y: clamp(d.oy + dy, 0, 0.98) } as Partial<Layer>);
    } else {
      const l = layers.find((x) => x.uid === d.uid);
      if (l?.kind === "banner") patch(d.uid, { scale: clamp(d.os + dx, 0.05, 1) } as Partial<Layer>);
      else patch(d.uid, { fontSize: clamp(d.os + dy * 0.5, 0.02, 0.4) } as Partial<Layer>);
    }
  }

  function onPointerUp() { drag.current = null; }

  /** Сохранить позицию слоя-баннера как значение по умолчанию у самого баннера. */
  async function saveBannerDefaults() {
    if (sel?.kind !== "banner") return;
    const b = banners.find((x) => x.id === sel.bannerId);
    if (!b) return;
    const upd = await api.updateBanner(b.id, {
      x: sel.x, y: sel.y, scale: sel.scale, opacity: sel.opacity,
      motion: sel.motion, motion_speed: sel.motionSpeed,
    });
    setMsg("Позиция сохранена в баннере");
    onSaved?.(upd);
  }

  /** Преобразует слои редактора в формат бэкенда (доли кадра, banner_id). */
  function toOverlays(): Overlay[] {
    return layers.map((l) =>
      l.kind === "banner"
        ? {
            type: "banner" as const, banner_id: l.bannerId,
            x: l.x, y: l.y, scale: l.scale, opacity: l.opacity,
            motion: l.motion, motion_speed: l.motionSpeed,
            ...(l.start !== undefined ? { start: l.start } : {}),
            ...(l.end !== undefined ? { end: l.end } : {}),
          }
        : {
            type: "text" as const, text: l.text,
            x: l.x, y: l.y, font_size: l.fontSize, color: l.color, opacity: l.opacity,
            ...(l.start !== undefined ? { start: l.start } : {}),
            ...(l.end !== undefined ? { end: l.end } : {}),
          }
    ) as Overlay[];
  }

  return (
    <div>
      <div className="vp-card">
        <div className="editor-controls">
          <div>
            <label className="form-label vp">Видео</label>
            <select className="form-select vp" value={videoId ?? ""} onChange={(e) => setVideoId(Number(e.target.value))}>
              {videos.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
            </select>
          </div>
          <div>
            <label className="form-label vp">Добавить баннер</label>
            <select className="form-select vp" value="" onChange={(e) => e.target.value && addBanner(Number(e.target.value))}>
              <option value="">— выберите —</option>
              {banners.map((b) => <option key={b.id} value={b.id}>{b.name} ({b.type})</option>)}
            </select>
          </div>
          <div className="d-flex align-items-end">
            <button className="btn btn-vp-outline w-100" onClick={addText}>
              <i className="bi bi-type me-1" />Добавить текст
            </button>
          </div>
          <div className="d-flex align-items-end">
            <button className="btn btn-vp w-100" disabled={!video || layers.length === 0} onClick={() => setShowPublish(true)}>
              <i className="bi bi-send me-1" />Опубликовать
            </button>
          </div>
        </div>
        {msg && <div className="fs-sm text-success mt-2"><i className="bi bi-check-circle me-1" />{msg}</div>}
      </div>

      <div className="editor">
        {/* Панель слоёв + свойства */}
        <div className="vp-card">
          <div className="vp-card-header">
            <h3><i className="bi bi-layers me-2 text-accent" />Слои ({layers.length})</h3>
          </div>

          {layers.length === 0 ? (
            <p className="fs-sm text-muted mb-0">Добавьте баннер или текст — они вожгутся в видео при публикации.</p>
          ) : (
            <div className="d-flex flex-column gap-1 mb-3">
              {/* сверху — верхний слой (отрисовывается последним) */}
              {[...layers].reverse().map((l) => {
                const b = l.kind === "banner" ? banners.find((x) => x.id === l.bannerId) : null;
                return (
                  <div key={l.uid}
                    className={`d-flex align-items-center gap-2 p-2 rounded ${selected === l.uid ? "ring-selected" : ""}`}
                    style={{ background: "var(--vp-panel2)", cursor: "pointer" }}
                    onClick={() => setSelected(l.uid)}>
                    <i className={`bi ${l.kind === "banner" ? "bi-image" : "bi-type"} text-accent`} />
                    <span className="flex-grow-1 text-truncate fs-sm">
                      {l.kind === "banner" ? (b?.name ?? `баннер #${l.bannerId}`) : l.text}
                    </span>
                    <button className="btn btn-sm btn-vp-outline py-0 px-1" title="Выше" onClick={(e) => { e.stopPropagation(); move(l.uid, 1); }}>
                      <i className="bi bi-arrow-up" />
                    </button>
                    <button className="btn btn-sm btn-vp-outline py-0 px-1" title="Ниже" onClick={(e) => { e.stopPropagation(); move(l.uid, -1); }}>
                      <i className="bi bi-arrow-down" />
                    </button>
                    <button className="btn btn-sm py-0 px-1 border-0 bg-transparent text-danger" title="Удалить" onClick={(e) => { e.stopPropagation(); removeLayer(l.uid); }}>
                      <i className="bi bi-trash" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {/* Свойства выбранного слоя */}
          {sel && (
            <div className="border-top pt-3">
              <div className="fw-600 mb-2 fs-sm">Свойства слоя</div>

              {sel.kind === "text" && (
                <>
                  <label className="form-label vp">Текст</label>
                  <input className="form-control vp mb-2" value={sel.text} onChange={(e) => patch(sel.uid, { text: e.target.value } as Partial<Layer>)} />
                  <div className="d-flex gap-2 mb-2">
                    <div>
                      <label className="form-label vp">Цвет</label>
                      <input type="color" className="form-control form-control-color" value={sel.color}
                        onChange={(e) => patch(sel.uid, { color: e.target.value } as Partial<Layer>)} />
                    </div>
                    <div className="flex-grow-1">
                      <label className="form-label vp">Размер {(sel.fontSize * 100).toFixed(0)}% высоты</label>
                      <input type="range" className="form-range" min={0.02} max={0.3} step={0.005} value={sel.fontSize}
                        onChange={(e) => patch(sel.uid, { fontSize: Number(e.target.value) } as Partial<Layer>)} />
                    </div>
                  </div>
                </>
              )}

              {sel.kind === "banner" && (
                <>
                  <label className="form-label vp">Размер {Math.round(sel.scale * 100)}%</label>
                  <input type="range" className="form-range mb-2" min={0.05} max={1} step={0.01} value={sel.scale}
                    onChange={(e) => patch(sel.uid, { scale: Number(e.target.value) } as Partial<Layer>)} />
                  <label className="form-label vp">Движение</label>
                  <select className="form-select vp mb-2" value={sel.motion}
                    onChange={(e) => patch(sel.uid, { motion: e.target.value as Motion } as Partial<Layer>)}>
                    <option value="none">нет</option>
                    <option value="drift">дрейф</option>
                    <option value="bounce">отскок (DVD)</option>
                    <option value="slide">проезд</option>
                  </select>
                  {sel.motion !== "none" && (
                    <>
                      <label className="form-label vp">Скорость {sel.motionSpeed.toFixed(1)}x</label>
                      <input type="range" className="form-range mb-2" min={0.2} max={3} step={0.1} value={sel.motionSpeed}
                        onChange={(e) => patch(sel.uid, { motionSpeed: Number(e.target.value) } as Partial<Layer>)} />
                    </>
                  )}
                </>
              )}

              <label className="form-label vp">Прозрачность {Math.round(sel.opacity * 100)}%</label>
              <input type="range" className="form-range mb-2" min={0.1} max={1} step={0.05} value={sel.opacity}
                onChange={(e) => patch(sel.uid, { opacity: Number(e.target.value) } as Partial<Layer>)} />

              {/* Тайминг слоя */}
              {videoDuration > 0 && (
                <div className="d-flex gap-2 align-items-end mb-2">
                  <div>
                    <label className="form-label vp">Показ с, с</label>
                    <input className="form-control vp form-control-sm" type="number" min={0} max={Math.floor(videoDuration)} step={0.5}
                      value={sel.start ?? ""} placeholder="0"
                      onChange={(e) => patch(sel.uid, { start: e.target.value === "" ? undefined : Number(e.target.value) } as Partial<Layer>)} />
                  </div>
                  <div>
                    <label className="form-label vp">по, с</label>
                    <input className="form-control vp form-control-sm" type="number" min={0} max={Math.ceil(videoDuration)} step={0.5}
                      value={sel.end ?? ""} placeholder={videoDuration.toFixed(1)}
                      onChange={(e) => patch(sel.uid, { end: e.target.value === "" ? undefined : Number(e.target.value) } as Partial<Layer>)} />
                  </div>
                  <span className="fs-sm text-muted">длина {formatTime(videoDuration)}</span>
                </div>
              )}

              {sel.kind === "banner" && (
                <button className="btn btn-vp-outline btn-sm" onClick={saveBannerDefaults}>
                  <i className="bi bi-save me-1" />Сохранить как позицию баннера
                </button>
              )}
            </div>
          )}
        </div>

        {/* Превью */}
        <div className="preview-wrap">
          <div className="preview-box" ref={boxRef} onPointerMove={onPointerMove} onPointerUp={onPointerUp}>
            {video ? (
              <video key={video.id} ref={videoRef} src={api.videoFileUrl(video.id)}
                className="preview-video" controls muted loop playsInline />
            ) : (
              <div className="preview-empty">
                <div><i className="bi bi-film fs-1 d-block mb-2" />Загрузите видео на вкладке «Видео»</div>
              </div>
            )}

            {layers.map((l) => {
              const isSel = selected === l.uid;
              if (l.kind === "banner") {
                const b = banners.find((x) => x.id === l.bannerId);
                if (!b) return null;
                return (
                  <div key={l.uid}
                    className={`banner-layer ${l.motion !== "none" ? "motion-" + l.motion : ""} ${isSel ? "ring-selected" : ""}`}
                    style={{
                      left: `${l.x * 100}%`, top: `${l.y * 100}%`, width: `${l.scale * 100}%`,
                      opacity: l.opacity,
                      animationDuration: l.motion !== "none" ? `${(8 / l.motionSpeed).toFixed(1)}s` : undefined,
                    }}
                    onPointerDown={(e) => onPointerDown(e, l.uid, "move")}>
                    {b.type === "image"
                      ? <img src={api.bannerFileUrl(b.id)} alt={b.name} draggable={false} />
                      : <video src={api.bannerFileUrl(b.id)} autoPlay muted loop playsInline />}
                    {isSel && <span className="resize-handle" onPointerDown={(e) => onPointerDown(e, l.uid, "resize")} />}
                  </div>
                );
              }
              return (
                <div key={l.uid}
                  className={isSel ? "ring-selected" : ""}
                  style={{
                    position: "absolute", left: `${l.x * 100}%`, top: `${l.y * 100}%`,
                    color: l.color, fontSize: `${Math.max(8, l.fontSize * boxH)}px`, lineHeight: 1.1,
                    fontWeight: 700, opacity: l.opacity, cursor: "move", userSelect: "none",
                    textShadow: "0 2px 8px rgba(0,0,0,0.7)", whiteSpace: "nowrap",
                  }}
                  onPointerDown={(e) => onPointerDown(e, l.uid, "move")}>
                  {l.text}
                </div>
              );
            })}
          </div>
          <p className="fs-sm text-muted text-center" style={{ maxWidth: 400 }}>
            Тяните слои мышью; у выбранного баннера уголок меняет размер. Всё, что видно здесь,
            вжигается в видео при публикации.
          </p>
        </div>
      </div>

      {showPublish && video && (
        <PublishModal
          accounts={accounts}
          videoId={video.id}
          overlays={toOverlays()}
          onClose={() => setShowPublish(false)}
          onDone={() => { setShowPublish(false); setMsg("Задача создана"); onPosted?.(); }}
        />
      )}
    </div>
  );
}

function PublishModal({ accounts, videoId, overlays, onClose, onDone }: {
  accounts: Account[];
  videoId: number;
  overlays: Overlay[];
  onClose: () => void;
  onDone: () => void;
}) {
  const ready = accounts.filter((a) => a.has_cookies && a.active);
  const [accountId, setAccountId] = useState<number | null>(ready[0]?.id ?? null);
  const [caption, setCaption] = useState("");
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    if (!accountId) return;
    setBusy(true); setErr(null);
    try {
      await api.createJob({
        account_id: accountId,
        video_id: videoId,
        caption,
        scheduled_at: when ? new Date(when).toISOString() : null,
        overlays,
      });
      onDone();
    } catch (e: any) { setErr(e.message); setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal login-modal" onClick={(e) => e.stopPropagation()}>
        <div className="row between">
          <b><i className="bi bi-send me-2" />Публикация ({overlays.length} слоёв)</b>
          <button className="btn btn-sm btn-vp-outline" onClick={onClose}>Закрыть</button>
        </div>
        {err && <div className="alert alert-danger py-2 my-2 fs-sm">{err}</div>}
        <div className="d-flex flex-column gap-2 mt-2">
          <div>
            <label className="form-label vp">Аккаунт</label>
            <select className="form-select vp" value={accountId ?? ""} onChange={(e) => setAccountId(Number(e.target.value) || null)}>
              <option value="">— выберите —</option>
              {ready.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.platform})</option>)}
            </select>
            {ready.length === 0 && <div className="form-text text-danger fs-sm">Нет аккаунтов с куками — импортируйте их на вкладке «Аккаунты».</div>}
          </div>
          <div>
            <label className="form-label vp">Описание</label>
            <textarea className="form-control vp" rows={3} value={caption} onChange={(e) => setCaption(e.target.value)} />
          </div>
          <div>
            <label className="form-label vp">Время публикации (пусто — сразу)</label>
            <input className="form-control vp" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
          </div>
          <button className="btn btn-vp" disabled={busy || !accountId} onClick={submit}>
            {busy ? <><span className="spinner-border spinner-border-sm me-2" />Создаю…</> : <>Создать задачу</>}
          </button>
        </div>
      </div>
    </div>
  );
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

function formatTime(sec: number) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
