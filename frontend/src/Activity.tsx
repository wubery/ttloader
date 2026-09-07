/**
 * Вкладка «Активность»: аккаунты сами заходят в ленту и лайкают посты друг друга.
 *
 * Всё расписание задаётся диапазонами «от–до» — ровные интервалы у десятка
 * аккаунтов выглядят как ферма. Лайкать разрешено только аккаунты этой панели,
 * и опознаются они по публичному нику, поэтому ник виден в каждой строке.
 */
import { useEffect, useState } from "react";
import { Account, ActivityRun, ActivitySettings, api } from "./api";

/** Пара полей «от–до» — тот же вид, что у паузы между аккаунтами в форме поста. */
function Range({ label, from, to, unit, min, max, onChange }: {
  label: string; from: number; to: number; unit: string;
  min: number; max: number; onChange: (from: number, to: number) => void;
}) {
  const num = (v: string, fallback: number) => {
    const n = Number(v);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
  };
  return (
    <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
      <span className="fs-sm text-muted" style={{ minWidth: 190 }}>{label}</span>
      <span className="fs-sm text-muted">от</span>
      <input className="form-control vp form-control-sm" type="number" style={{ width: 84 }}
             min={min} max={max} value={from}
             onChange={(e) => onChange(num(e.target.value, from), to)} />
      <span className="fs-sm text-muted">до</span>
      <input className="form-control vp form-control-sm" type="number" style={{ width: 84 }}
             min={min} max={max} value={to}
             onChange={(e) => onChange(from, num(e.target.value, to))} />
      <span className="fs-sm text-muted">{unit}</span>
    </div>
  );
}

function Switch({ id, checked, label, onChange }: {
  id: string; checked: boolean; label: string; onChange: (v: boolean) => void;
}) {
  return (
    <div className="form-check form-switch mb-2">
      <input className="form-check-input" type="checkbox" id={id} checked={checked}
             onChange={(e) => onChange(e.target.checked)} />
      <label className="form-check-label fs-sm" htmlFor={id}>{label}</label>
    </div>
  );
}

const STATUS_BADGE: Record<string, string> = {
  ok: "badge-vp-success", error: "badge-vp-danger", skipped: "badge-vp-muted",
};

export function Activity({ accounts, onChange }: { accounts: Account[]; onChange: () => void }) {
  const [cfg, setCfg] = useState<ActivitySettings | null>(null);
  const [log, setLog] = useState<ActivityRun[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  async function reload() {
    try {
      const [c, l] = await Promise.all([api.activitySettings(), api.activityLog(50)]);
      setCfg(c); setLog(l);
    } catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { reload(); }, []);
  // Журнал пополняется фоновыми потоками — подтягиваем его, пока вкладка открыта
  useEffect(() => {
    const t = setInterval(() => api.activityLog(50).then(setLog).catch(() => {}), 10000);
    return () => clearInterval(t);
  }, []);

  const patch = (p: Partial<ActivitySettings>) => setCfg((c) => (c ? { ...c, ...p } : c));

  async function save() {
    if (!cfg) return;
    setErr(null); setMsg(null);
    try { setCfg(await api.saveActivitySettings(cfg)); setMsg("Настройки сохранены"); }
    catch (e: any) { setErr(e.message); }
  }

  async function runNow(a: Account) {
    setBusy(a.id); setErr(null); setMsg(null);
    try { await api.runActivity(a.id); setMsg(`«${a.name}»: просмотр запущен, следите за журналом`); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  }

  async function discover(a: Account) {
    setBusy(a.id); setErr(null); setMsg(null);
    try { const acc = await api.discoverHandle(a.id); setMsg(`Ник: @${acc.tiktok_handle}`); onChange(); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  }

  const withCookies = accounts.filter((a) => a.has_cookies);
  const named = withCookies.filter((a) => a.tiktok_handle).length;

  return (
    <div>
      {err && <div className="alert alert-danger py-2 fs-sm">{err}</div>}
      {msg && <div className="alert alert-success py-2 fs-sm">{msg}</div>}

      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-activity me-2 text-accent" />Расписание</h3>
          {cfg && <button className="btn btn-vp btn-sm" onClick={save}>Сохранить</button>}
        </div>
        {!cfg ? <div className="fs-sm text-muted">Загрузка…</div> : (
          <div className="row g-4">
            <div className="col-md-6">
              <Switch id="actOn" checked={cfg.activity_enabled} label="Просмотр ленты"
                      onChange={(v) => patch({ activity_enabled: v })} />
              <Range label="заходов в сутки" unit="раз" min={0} max={24}
                     from={cfg.activity_per_day_min} to={cfg.activity_per_day_max}
                     onChange={(f, t) => patch({ activity_per_day_min: f, activity_per_day_max: t })} />
              <Range label="длительность сессии" unit="секунд" min={10} max={1800}
                     from={cfg.activity_seconds_min} to={cfg.activity_seconds_max}
                     onChange={(f, t) => patch({ activity_seconds_min: f, activity_seconds_max: t })} />
              <Range label="в какие часы" unit="часов" min={0} max={24}
                     from={cfg.activity_hour_from} to={cfg.activity_hour_to}
                     onChange={(f, t) => patch({ activity_hour_from: f, activity_hour_to: t })} />
              <div className="form-text fs-sm">
                Время каждого захода разыгрывается случайно внутри этих рамок. Равные
                границы часов (например 0 и 0) означают «круглосуточно».
              </div>
            </div>
            <div className="col-md-6">
              <Switch id="likeOn" checked={cfg.likes_enabled} label="Взаимные лайки"
                      onChange={(v) => patch({ likes_enabled: v })} />
              <Range label="лайков за прогон" unit="шт." min={0} max={20}
                     from={cfg.likes_per_run_min} to={cfg.likes_per_run_max}
                     onChange={(f, t) => patch({ likes_per_run_min: f, likes_per_run_max: t })} />
              <Range label="пауза между прогонами" unit="минут" min={5} max={1440}
                     from={cfg.likes_interval_min} to={cfg.likes_interval_max}
                     onChange={(f, t) => patch({ likes_interval_min: f, likes_interval_max: t })} />
              <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
                <span className="fs-sm text-muted" style={{ minWidth: 190 }}>одного и того же — не чаще</span>
                <input className="form-control vp form-control-sm" type="number" style={{ width: 84 }}
                       min={1} max={720} value={cfg.like_cooldown_hours}
                       onChange={(e) => patch({ like_cooldown_hours: Number(e.target.value) || 1 })} />
                <span className="fs-sm text-muted">часов</span>
              </div>
              <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
                <span className="fs-sm text-muted" style={{ minWidth: 190 }}>одновременно аккаунтов</span>
                <input className="form-control vp form-control-sm" type="number" style={{ width: 84 }}
                       min={1} max={5} value={cfg.activity_max_concurrent}
                       onChange={(e) => patch({ activity_max_concurrent: Number(e.target.value) || 1 })} />
              </div>
              <div className="form-text fs-sm">
                Лайкать можно только аккаунты этой панели: адрес поста сверяется с их
                никами перед нажатием. В ленте лайков нет вовсе.
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="vp-card">
        <div className="vp-card-header">
          <h3><i className="bi bi-people me-2 text-accent" />Аккаунты</h3>
          <span className="fs-sm text-muted">с ником: {named} из {withCookies.length}</span>
        </div>
        {withCookies.length === 0 && (
          <div className="fs-sm text-muted">Нет аккаунтов с куками — проверять нечего.</div>
        )}
        <div className="d-flex flex-column gap-2">
          {withCookies.map((a) => (
            <div key={a.id} className="d-flex align-items-center gap-2 flex-wrap">
              <b style={{ minWidth: 140 }}>{a.name}</b>
              {a.tiktok_handle
                ? <span className="badge-vp badge-vp-info">@{a.tiktok_handle}</span>
                : <span className="badge-vp badge-vp-warning">ник не определён</span>}
              <label className="d-flex align-items-center gap-1 fs-sm text-muted" style={{ cursor: "pointer" }}>
                <input type="checkbox" className="form-check-input mt-0" checked={a.activity_on}
                       onChange={(e) => api.updateAccount(a.id, { activity_on: e.target.checked })
                         .then(onChange).catch((x) => setErr(x.message))} />
                лента
              </label>
              <label className="d-flex align-items-center gap-1 fs-sm text-muted" style={{ cursor: "pointer" }}>
                <input type="checkbox" className="form-check-input mt-0" checked={a.likes_on}
                       onChange={(e) => api.updateAccount(a.id, { likes_on: e.target.checked })
                         .then(onChange).catch((x) => setErr(x.message))} />
                лайки
              </label>
              <span className="fs-sm text-muted">
                {a.last_activity_at
                  ? `был(а): ${new Date(a.last_activity_at).toLocaleString("ru")}`
                  : "ещё не заходил"}
              </span>
              <button className="btn btn-vp-outline btn-sm ms-auto" disabled={busy === a.id}
                      onClick={() => discover(a)}>
                <i className="bi bi-person-badge me-1" />Определить ник
              </button>
              <button className="btn btn-vp btn-sm" disabled={busy === a.id} onClick={() => runNow(a)}>
                <i className="bi bi-play me-1" />Проверить сейчас
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="vp-card">
        <div className="vp-card-header"><h3><i className="bi bi-list-ul me-2 text-accent" />Журнал</h3></div>
        {log.length === 0 && <div className="fs-sm text-muted">Пока пусто.</div>}
        <div className="d-flex flex-column gap-1">
          {log.map((r) => (
            <div key={r.id} className="d-flex align-items-center gap-2 flex-wrap fs-sm">
              <span className="text-muted" style={{ minWidth: 130 }}>
                {new Date(r.created_at).toLocaleString("ru")}
              </span>
              <span className={`badge-vp ${STATUS_BADGE[r.status] || "badge-vp-muted"}`}>{r.status}</span>
              <b>{r.account_name || `#${r.account_id}`}</b>
              <span className="text-muted">
                {r.kind === "browse" ? "смотрел ленту" : `лайк → ${r.target_name || "?"}`}
              </span>
              {r.detail && <span className="text-muted">— {r.detail}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
