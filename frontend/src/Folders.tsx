/**
 * Папки библиотек и их привязка к группам аккаунтов.
 *
 * Папки у каждой библиотеки свои (kind: video / hook / background). Смысл в
 * группах: пока на папку не повешена ни одна группа, она ничего не ограничивает —
 * просто полка. Как только группы указаны, содержимое папки достаётся только им,
 * и при постинге на группу рендер берёт хуки и фоны уже с этим фильтром.
 *
 * Здесь только UI; правило доступности продублировано на бэкенде в
 * services/folders.py — оно же применяется при случайном выборе ассетов.
 */
import { useState } from "react";
import { AccountGroup, AssetFolder, FolderKind, api } from "./api";

/** Доступна ли папка группе (null-группа = аккаунт без группы, ограничений нет). */
export function folderAllowsGroup(folder: AssetFolder | undefined, groupId: number | null): boolean {
  if (groupId === null) return true;
  if (!folder) return true;                    // файл без папки доступен всем
  if (folder.group_ids.length === 0) return true;
  return folder.group_ids.includes(groupId);
}

/** Фильтр «этот файл доступен группе» для списков библиотек. */
export function visibleToGroup<T extends { folder_id: number | null }>(
  items: T[], folders: AssetFolder[], groupId: number | null,
): T[] {
  if (groupId === null) return items;
  const byId = new Map(folders.map((f) => [f.id, f]));
  return items.filter((it) =>
    it.folder_id == null || folderAllowsGroup(byId.get(it.folder_id), groupId));
}

/** Селектор папки у карточки файла. */
export function FolderPicker({ kind, id, folderId, folders, onChange, className = "" }: {
  kind: FolderKind; id: number; folderId: number | null;
  folders: AssetFolder[]; onChange: () => void; className?: string;
}) {
  const [busy, setBusy] = useState(false);
  if (folders.length === 0) return null;       // папок нет — нечего показывать
  return (
    <select className={`form-select vp form-select-sm ${className}`} disabled={busy}
            title="Папка" value={folderId ?? ""}
            onChange={async (e) => {
              setBusy(true);
              try { await api.setAssetFolder(kind, id, Number(e.target.value) || null); await onChange(); }
              finally { setBusy(false); }
            }}>
      <option value="">без папки</option>
      {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
    </select>
  );
}

/** Полоска фильтра по папкам над списком файлов. */
export function FolderTabs({ folders, value, onPick }: {
  folders: AssetFolder[]; value: number | null | "none"; onPick: (v: number | null | "none") => void;
}) {
  if (folders.length === 0) return null;
  const chip = (active: boolean) => `btn btn-sm ${active ? "btn-vp" : "btn-vp-outline"}`;
  return (
    <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
      <button className={chip(value === null)} onClick={() => onPick(null)}>Все</button>
      {folders.map((f) => (
        <button key={f.id} className={chip(value === f.id)} onClick={() => onPick(f.id)}>
          <i className="bi bi-folder me-1" />{f.name}
          <span className="ms-1 opacity-75">{f.items_count}</span>
        </button>
      ))}
      <button className={chip(value === "none")} onClick={() => onPick("none")}>Без папки</button>
    </div>
  );
}

/** Управление папками одной библиотеки: создать, переименовать, задать группы, удалить. */
export function FoldersCard({ kind, title, folders, groups, onChange }: {
  kind: FolderKind; title: string; folders: AssetFolder[];
  groups: AccountGroup[]; onChange: () => void;
}) {
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(fn: () => Promise<any>) {
    setErr(null);
    try { await fn(); await onChange(); } catch (e: any) { setErr(e.message); }
  }
  function toggleGroup(f: AssetFolder, gid: number) {
    const next = f.group_ids.includes(gid)
      ? f.group_ids.filter((x) => x !== gid)
      : [...f.group_ids, gid];
    run(() => api.updateAssetFolder(f.id, { group_ids: next }));
  }

  return (
    <div className="mb-2">
      <button className="btn btn-vp-outline btn-sm" onClick={() => setOpen(!open)}>
        <i className={`bi ${open ? "bi-chevron-up" : "bi-folder2-open"} me-1`} />
        {title} ({folders.length})
      </button>
      {open && (
        <div className="mt-2 p-2" style={{ border: "1px solid var(--vp-border)", borderRadius: 8 }}>
          {err && <div className="alert alert-danger py-2 fs-sm">{err}</div>}
          <div className="d-flex align-items-center gap-2 flex-wrap">
            <input className="form-control vp form-control-sm" style={{ maxWidth: 220 }}
                   placeholder="Новая папка" value={name} onChange={(e) => setName(e.target.value)}
                   onKeyDown={(e) => {
                     if (e.key === "Enter" && name.trim()) {
                       run(() => api.createAssetFolder({ kind, name })); setName("");
                     }
                   }} />
            <button className="btn btn-vp btn-sm" disabled={!name.trim()}
                    onClick={() => { run(() => api.createAssetFolder({ kind, name })); setName(""); }}>
              <i className="bi bi-plus-lg me-1" />Создать
            </button>
          </div>

          {folders.map((f) => (
            <div className="d-flex align-items-center gap-2 flex-wrap mt-2" key={f.id}>
              <input className="form-control vp form-control-sm" style={{ maxWidth: 200 }}
                     defaultValue={f.name} key={`${f.id}-${f.name}`}
                     onBlur={(e) => {
                       const v = e.target.value.trim();
                       if (v && v !== f.name) run(() => api.updateAssetFolder(f.id, { name: v }));
                     }} />
              <span className="fs-sm text-muted">группы:</span>
              {groups.length === 0
                ? <span className="fs-sm text-muted">их пока нет</span>
                : groups.map((g) => {
                    const on = f.group_ids.includes(g.id);
                    const c = g.color || "#9b8cf5";
                    return (
                      <button key={g.id} className="badge-vp" onClick={() => toggleGroup(f, g.id)}
                              title={on ? "Убрать группу" : "Дать доступ группе"}
                              style={{
                                cursor: "pointer", border: "1px solid transparent",
                                background: on ? `${c}26` : "var(--vp-bg2)",
                                color: on ? c : "var(--vp-muted)",
                                borderColor: on ? c : "var(--vp-border)",
                              }}>
                        {on && <i className="bi bi-check2 me-1" />}{g.name}
                      </button>
                    );
                  })}
              <span className="badge-vp badge-vp-muted">{f.items_count} шт.</span>
              <button className="btn btn-vp-danger btn-sm"
                      onClick={() => run(() => api.deleteAssetFolder(f.id))}>
                <i className="bi bi-trash" />
              </button>
            </div>
          ))}

          <p className="fs-sm text-muted mt-2 mb-0">
            Пока у папки не отмечено ни одной группы, она ничего не ограничивает — как и файл без
            папки. С отмеченными группами содержимое достаётся только им: и в списках панели, и
            при автоматическом выборе во время рендера.
          </p>
        </div>
      )}
    </div>
  );
}
