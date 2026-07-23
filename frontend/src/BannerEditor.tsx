import { useEffect, useRef, useState } from "react";
import { api, Banner, Motion, Video } from "./api";

// Позиция/масштаб хранятся как доли кадра (0..1), поэтому корректны для любого
// разрешения. Редактор рисует баннер поверх <video> и даёт таскать/менять размер.
interface Props {
  videos: Video[];
  banners: Banner[];
  onSaved?: (b: Banner) => void;
}

export function BannerEditor({ videos, banners, onSaved }: Props) {
  const [videoId, setVideoId] = useState<number | null>(videos[0]?.id ?? null);
  const [bannerId, setBannerId] = useState<number | null>(banners[0]?.id ?? null);
  const [pos, setPos] = useState({ x: 0.05, y: 0.05, scale: 0.25, opacity: 1 });
  const [motion, setMotion] = useState<Motion>("none");
  const [motionSpeed, setMotionSpeed] = useState(1);
  const [saved, setSaved] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ mode: "move" | "resize"; sx: number; sy: number; ox: number; oy: number; os: number } | null>(null);

  const banner = banners.find((b) => b.id === bannerId) || null;

  useEffect(() => {
    if (banner) {
      setPos({ x: banner.x, y: banner.y, scale: banner.scale, opacity: banner.opacity });
      setMotion(banner.motion ?? "none");
      setMotionSpeed(banner.motion_speed ?? 1);
    }
  }, [bannerId]);

  useEffect(() => {
    if (videos.length && videoId === null) setVideoId(videos[0].id);
  }, [videos]);
  useEffect(() => {
    if (banners.length && bannerId === null) setBannerId(banners[0].id);
  }, [banners]);

  function onPointerDown(e: React.PointerEvent, mode: "move" | "resize") {
    e.preventDefault();
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { mode, sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y, os: pos.scale };
  }

  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current || !boxRef.current) return;
    const rect = boxRef.current.getBoundingClientRect();
    const dx = (e.clientX - drag.current.sx) / rect.width;
    const dy = (e.clientY - drag.current.sy) / rect.height;
    if (drag.current.mode === "move") {
      setPos((p) => ({
        ...p,
        x: clamp(drag.current!.ox + dx, 0, 1 - p.scale * 0.2),
        y: clamp(drag.current!.oy + dy, 0, 1),
      }));
    } else {
      setPos((p) => ({ ...p, scale: clamp(drag.current!.os + dx, 0.05, 1) }));
    }
    setSaved(false);
  }

  function onPointerUp(e: React.PointerEvent) {
    drag.current = null;
  }

  async function save() {
    if (!banner) return;
    const b = await api.updateBanner(banner.id, { ...pos, motion, motion_speed: motionSpeed });
    setSaved(true);
    onSaved?.(b);
  }

  const video = videos.find((v) => v.id === videoId) || null;

  return (
    <div className="editor">
      <div className="editor-controls">
        <label>
          Видео
          <select value={videoId ?? ""} onChange={(e) => setVideoId(Number(e.target.value))}>
            {videos.map((v) => (
              <option key={v.id} value={v.id}>
                {v.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Баннер
          <select value={bannerId ?? ""} onChange={(e) => setBannerId(Number(e.target.value))}>
            {banners.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} ({b.type})
              </option>
            ))}
          </select>
        </label>
        <label>
          Прозрачность {Math.round(pos.opacity * 100)}%
          <input
            type="range" min={0.1} max={1} step={0.05} value={pos.opacity}
            onChange={(e) => { setPos((p) => ({ ...p, opacity: Number(e.target.value) })); setSaved(false); }}
          />
        </label>
        <label>
          Размер {Math.round(pos.scale * 100)}%
          <input
            type="range" min={0.05} max={1} step={0.01} value={pos.scale}
            onChange={(e) => { setPos((p) => ({ ...p, scale: Number(e.target.value) })); setSaved(false); }}
          />
        </label>
        <label>
          Движение
          <select value={motion} onChange={(e) => { setMotion(e.target.value as Motion); setSaved(false); }}>
            <option value="none">нет</option>
            <option value="drift">дрейф</option>
            <option value="bounce">отскок (DVD)</option>
            <option value="slide">проезд</option>
          </select>
        </label>
        {motion !== "none" && (
          <label>
            Скорость {motionSpeed.toFixed(1)}×
            <input type="range" min={0.2} max={3} step={0.1} value={motionSpeed}
              onChange={(e) => { setMotionSpeed(Number(e.target.value)); setSaved(false); }} />
          </label>
        )}
        <button className="primary" onClick={save} disabled={!banner}>
          {saved ? "Сохранено ✓" : "Сохранить позицию"}
        </button>
      </div>

      <div className="preview-wrap">
        <div
          className="preview-box"
          ref={boxRef}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        >
          {video ? (
            <video
              key={video.id}
              src={api.videoFileUrl(video.id)}
              className="preview-video"
              controls
              muted
              loop
              playsInline
            />
          ) : (
            <div className="preview-empty">Загрузите видео на вкладке «Видео»</div>
          )}

          {banner && (
            <div
              className={`banner-layer ${motion !== "none" ? "motion-" + motion : ""}`}
              style={{
                left: `${pos.x * 100}%`,
                top: `${pos.y * 100}%`,
                width: `${pos.scale * 100}%`,
                opacity: pos.opacity,
                animationDuration: motion !== "none" ? `${(8 / motionSpeed).toFixed(1)}s` : undefined,
              }}
              onPointerDown={(e) => onPointerDown(e, "move")}
            >
              {banner.type === "image" ? (
                <img src={api.bannerFileUrl(banner.id)} alt={banner.name} draggable={false} />
              ) : (
                <video src={api.bannerFileUrl(banner.id)} autoPlay muted loop playsInline />
              )}
              <span className="resize-handle" onPointerDown={(e) => onPointerDown(e, "resize")} />
            </div>
          )}
        </div>
        <p className="hint">
          Перетаскивайте баннер мышью, тяните за уголок для изменения размера. Позиция
          хранится в долях кадра, поэтому одинаково ляжет на видео любого разрешения.
          При постинге баннер «вжигается» в видео через ffmpeg — украсть ролик без него нельзя.
        </p>
      </div>
    </div>
  );
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}
