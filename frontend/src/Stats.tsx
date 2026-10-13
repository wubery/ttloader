/** Вкладка «Статистика»: живые задачи плюс архивный счётчик удалённых. */
import { useEffect, useMemo, useState } from "react";
import { api, Account, AccountGroup, Job, JobStat, Video } from "./api";
import { GROUP_FALLBACK } from "./ui";

/* ================================================================
   Stats Dashboard
   ================================================================ */
export function Stats({ jobs, accounts, videos, groups }: {
  jobs: Job[]; accounts: Account[]; videos: Video[]; groups: AccountGroup[];
}) {
  // Выполненные задачи чистятся через несколько дней, а их исход остаётся в
  // счётчике на сервере — поэтому цифры считаются как «живые + архив».
  const [archive, setArchive] = useState<JobStat[]>([]);
  useEffect(() => { api.statsArchive().then(setArchive).catch(() => {}); }, [jobs.length]);
  const archDone = archive.reduce((n, r) => n + r.done, 0);
  const archFailed = archive.reduce((n, r) => n + r.failed, 0);

  const total = jobs.length + archDone + archFailed;
  const done = jobs.filter((j) => j.status === "done").length + archDone;
  const failed = jobs.filter((j) => j.status === "failed").length + archFailed;
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
    // день архива приходит как YYYY-MM-DD — сравниваем по календарной дате
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const arch = archive.filter((r) => r.day === key);
    const aDone = arch.reduce((n, r) => n + r.done, 0);
    const aFailed = arch.reduce((n, r) => n + r.failed, 0);
    return {
      label: d.toLocaleDateString("ru", { weekday: "short", day: "numeric" }),
      done: dayJobs.filter((j) => j.status === "done").length + aDone,
      failed: dayJobs.filter((j) => j.status === "failed").length + aFailed,
      total: dayJobs.length + aDone + aFailed,
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
      const ga = archive.filter((r) => (groupOf.get(r.account_id) ?? null) === row.id);
      const gd = gj.filter((j) => j.status === "done").length + ga.reduce((n, r) => n + r.done, 0);
      const gf = gj.filter((j) => j.status === "failed").length + ga.reduce((n, r) => n + r.failed, 0);
      const gt = gj.length + ga.reduce((n, r) => n + r.done + r.failed, 0);
      return {
        ...row, accounts: accs.length, jobs: gt, done: gd, failed: gf,
        rate: gt > 0 ? Math.round((gd / gt) * 100) : 0,
      };
    });
    // строку «Без группы» показываем только если там что-то есть
    return rows.filter((r) => r.id !== null || r.accounts > 0 || r.jobs > 0);
  }, [jobs, accounts, groups, archive]);

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
/** Резервные копии: база, куки и ключ шифрования. Делаются раз в сутки сами. */
