/** Вкладка «Очередь»: задачи, фильтры по статусу, автоповтор и массовый перезапуск. */
import { useContext, useEffect, useMemo, useState } from "react";
import { api, Account, Job, Video } from "./api";
import { SearchCtx, useConfirm, useToast } from "./ui";

/* ================================================================
   Jobs
   ================================================================ */
export function Jobs({ jobs, accounts, videos, onChange }: {
  jobs: Job[]; accounts: Account[]; videos: Video[]; onChange: () => void;
}) {
  const [showCount, setShowCount] = useState(20);
  // Фильтр по статусу помним между заходами — как свёрнутое меню
  const [statusFilter, setStatusFilter] = useState<Job["status"] | "all">(
    () => (localStorage.getItem("vp_jobs_filter") as Job["status"] | "all") || "all");
  useEffect(() => { localStorage.setItem("vp_jobs_filter", statusFilter); }, [statusFilter]);
  const toast = useToast();
  const { confirm } = useConfirm();
  const { query } = useContext(SearchCtx);
  const accName = (id: number) => accounts.find((a) => a.id === id)?.name ?? `#${id}`;
  const vidName = (id: number) => videos.find((v) => v.id === id)?.title ?? `#${id}`;

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: jobs.length };
    for (const j of jobs) c[j.status] = (c[j.status] ?? 0) + 1;
    return c;
  }, [jobs]);

  const filtered = useMemo(() => {
    const byStatus = statusFilter === "all" ? jobs : jobs.filter((j) => j.status === statusFilter);
    if (!query) return byStatus;
    const q = query.toLowerCase();
    return byStatus.filter((j) =>
      `#${j.id}`.includes(q) ||
      j.status.includes(q) ||
      accName(j.account_id).toLowerCase().includes(q) ||
      vidName(j.video_id).toLowerCase().includes(q) ||
      (j.caption || "").toLowerCase().includes(q)
    );
  }, [jobs, query, accounts, videos, statusFilter]);

  async function retryAllFailed() {
    const n = counts.failed ?? 0;
    if (!(await confirm("Перезапустить все ошибки?",
      `${n} задач(и) вернутся в очередь и пойдут заново с первой попытки.`))) return;
    try {
      const r = await api.retryFailed();
      toast.add("success", `Перезапущено: ${r.restarted}`);
      if (r.skipped_maybe_posted)
        toast.add("info", `Не перезапущено ${r.skipped_maybe_posted}: публикация могла пройти — `
          + "проверьте профиль и перезапустите по одной.");
      onChange();
    } catch (e: any) { toast.add("error", e.message); }
  }
  /** Если попытка дошла до «Опубликовать», сервер отвечает 409: ролик мог уже
   *  выйти, и повтор даст дубль — переспрашиваем. */
  async function retryOne(id: number) {
    try {
      await api.retryJob(id);
    } catch (e: any) {
      if (e.status !== 409) { toast.add("error", e.message); return; }
      if (!(await confirm("Повторить публикацию?", `${e.message} Повторить всё равно?`))) return;
      try { await api.retryJob(id, true); } catch (x: any) { toast.add("error", x.message); return; }
    }
    onChange(); toast.add("info", "Повтор запущен");
  }
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

  const FILTERS: { key: Job["status"] | "all"; label: string }[] = [
    { key: "all", label: "Все" }, { key: "pending", label: "ожидает" },
    { key: "rendering", label: "рендер" }, { key: "uploading", label: "постинг" },
    { key: "done", label: "готово" }, { key: "failed", label: "ошибка" },
  ];

  return (
    <div>
      {jobs.length > 0 && (
        <div className="d-flex align-items-center gap-2 flex-wrap mb-3">
          {FILTERS.map((f) => (
            <button key={f.key}
              className={`btn btn-sm ${statusFilter === f.key ? "btn-vp" : "btn-vp-outline"}`}
              onClick={() => { setStatusFilter(f.key); setShowCount(20); }}>
              {f.label}<span className="ms-1 opacity-75">{counts[f.key] ?? 0}</span>
            </button>
          ))}
          {(counts.failed ?? 0) > 0 && (
            <button className="btn btn-vp-danger btn-sm ms-auto" onClick={retryAllFailed}>
              <i className="bi bi-arrow-clockwise me-1" />Перезапустить все ошибки ({counts.failed})
            </button>
          )}
        </div>
      )}
      {jobs.length === 0 && <div className="vp-card text-center text-muted py-5"><i className="bi bi-inbox fs-1 d-block mb-2" />Пока нет задач. Создайте пост в «Новом посте».</div>}
      {jobs.length > 0 && filtered.length === 0 && !query && (
        <div className="vp-card text-center text-muted py-4">В этом статусе задач нет.</div>
      )}
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
                {jb.status === "failed" && jb.retry_at && (
                  <span className="badge-vp badge-vp-warning" title="автоповтор">
                    <i className="bi bi-arrow-repeat me-1" />попытка {jb.attempts + 1} из 5 · повтор в{" "}
                    {new Date(jb.retry_at).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" })}
                  </span>
                )}
                {jb.status === "failed" && !jb.retry_at && jb.attempts >= 5 && (
                  <span className="badge-vp badge-vp-danger" title="автоповтор больше не запланирован">
                    <i className="bi bi-x-octagon me-1" />попытки исчерпаны
                  </span>
                )}
                {jb.status !== "failed" && jb.attempts > 0 && (
                  <span className="badge-vp badge-vp-muted" title="это автоповтор">
                    <i className="bi bi-arrow-repeat me-1" />повтор {jb.attempts}
                  </span>
                )}
              </div>
              <div className="d-flex gap-1">
                {jb.status === "failed" && (
                  <button className="btn btn-vp-outline btn-sm" onClick={() => retryOne(jb.id)}>
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
            {/* Ссылка на опубликованный ролик: она уже с ником автора, иначе TikTok отдаёт 404 */}
            {jb.posted_url && (
              <a className="btn btn-vp-outline btn-sm mt-2 me-2" href={jb.posted_url} target="_blank" rel="noreferrer">
                <i className="bi bi-box-arrow-up-right me-1" />Открыть ролик
              </a>
            )}
            {/* Скриншот страницы TikTok в момент разбора — иначе неудачу не посмотреть */}
            {jb.has_screenshot && (
              <a className="btn btn-vp-outline btn-sm mt-2" href={`/api/jobs/${jb.id}/screenshot`} target="_blank" rel="noreferrer">
                <i className="bi bi-image me-1" />Скриншот страницы TikTok
              </a>
            )}
            {jb.log && (
              <details className="vp-job-log">
                <summary className="fs-sm text-muted" style={{ cursor: "pointer" }}>Показать лог</summary>
                {jb.log_truncated && (
                  <a className="fs-sm d-block mb-1" href={`/api/jobs/${jb.id}/log`} target="_blank" rel="noreferrer">
                    показаны последние строки — открыть весь лог
                  </a>
                )}
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

