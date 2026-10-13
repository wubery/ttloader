/** Вкладка «Эмулятор»: тестовая заливка через приложение TikTok по ADB. */
import { useState } from "react";
import { api, EmuDevice, EmuResult, Video } from "./api";

const STATE_LABELS: Record<EmuResult["state"], string> = {
  post: "Экран публикации — приложение приняло ролик",
  editor: "Редактор ролика — видео открыто в приложении",
  login: "Приложение просит войти",
  other_app: "Открылось не TikTok",
  unknown: "Экран не распознан",
};

export function Emulator({ videos }: { videos: Video[] }) {
  const [addr, setAddr] = useState(() => {
    try { return localStorage.getItem("vp_emu_addr") || "emulator-5554"; } catch { return "emulator-5554"; }
  });
  const [videoId, setVideoId] = useState<number | "">("");
  const [goToPost, setGoToPost] = useState(true);
  const [device, setDevice] = useState<EmuDevice | null>(null);
  const [result, setResult] = useState<EmuResult | null>(null);
  const [busy, setBusy] = useState<"" | "check" | "upload">("");
  const [err, setErr] = useState("");

  const remember = () => { try { localStorage.setItem("vp_emu_addr", addr); } catch {} };

  const check = async () => {
    setErr(""); setBusy("check"); remember();
    try { setDevice(await api.emuDevice(addr)); } catch (e: any) { setDevice(null); setErr(e.message); }
    setBusy("");
  };

  const run = async () => {
    if (videoId === "") return;
    setErr(""); setResult(null); setBusy("upload"); remember();
    try { setResult(await api.emuTestUpload(addr, videoId, goToPost)); } catch (e: any) { setErr(e.message); }
    setBusy("");
  };

  return (
    <div>
      <div className="alert alert-warning py-2 fs-sm">
        <b>Тестовый режим.</b> Ролик кладётся в галерею устройства и открывается в приложении
        TikTok через «Поделиться». Кнопка «Опубликовать» не нажимается никогда — проверяется
        только, доходит ли ролик до экрана публикации. TikTok распознаёт эмулятор, вход в
        приложении на нём обычно не проходит; надёжнее — реальный телефон с отладкой по Wi-Fi.
      </div>
      {err && <div className="alert alert-danger py-2 fs-sm">{err}</div>}

      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-phone me-2 text-accent" />Устройство</h3>
        </div>
        <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
          <input className="form-control vp form-control-sm" style={{ maxWidth: 260 }} value={addr}
                 placeholder="192.168.1.10:5555 или emulator-5554" onChange={(e) => setAddr(e.target.value)} />
          <button className="btn btn-vp btn-sm" disabled={!!busy} onClick={check}>
            {busy === "check" ? "Проверяю…" : "Проверить"}
          </button>
        </div>
        {device && (
          <div className="fs-sm">
            {device.model} · Android {device.android}{device.emulator ? " · эмулятор" : " · реальное устройство"} ·{" "}
            {device.tiktok_package
              ? <span className="text-success">TikTok: {device.tiktok_package}</span>
              : <span className="text-danger">TikTok не установлен</span>}
          </div>
        )}
        <div className="form-text fs-sm">
          Панель вызывает <code>adb</code> на своём сервере. Устройство должно быть доступно по сети:
          на телефоне — «Отладка по Wi-Fi» (<code>adb tcpip 5555</code>), для эмулятора на другом ПК —
          проброс порта ADB.
        </div>
      </div>

      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-cloud-upload me-2 text-accent" />Тестовая заливка</h3>
        </div>
        <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
          <select className="form-select vp form-select-sm" style={{ maxWidth: 360 }} value={videoId}
                  onChange={(e) => setVideoId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">— выберите видео —</option>
            {videos.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
          </select>
          <div className="form-check form-switch mb-0">
            <input id="emuNext" className="form-check-input" type="checkbox" checked={goToPost}
                   onChange={(e) => setGoToPost(e.target.checked)} />
            <label htmlFor="emuNext" className="form-check-label fs-sm">пройти «Далее» до экрана публикации</label>
          </div>
          <button className="btn btn-vp btn-sm" disabled={!!busy || videoId === ""} onClick={run}>
            {busy === "upload" ? "Идёт проверка… (до минуты)" : "Запустить тест"}
          </button>
        </div>

        {result && (
          <div className="row g-3 mt-1">
            <div className="col-md-6">
              <div className={`alert py-2 fs-sm ${result.ok ? "alert-success" : "alert-warning"}`}>
                {STATE_LABELS[result.state]}
              </div>
              <ol className="fs-sm ps-3">{result.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
              {result.texts.length > 0 && (
                <details className="fs-sm">
                  <summary>Надписи на экране</summary>
                  <div className="text-muted">{result.texts.join(" · ")}</div>
                </details>
              )}
            </div>
            <div className="col-md-6">
              <img src={api.emuShotUrl(result.screenshot)} alt="Снимок экрана устройства"
                   style={{ maxWidth: "100%", maxHeight: 520, borderRadius: 8 }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
