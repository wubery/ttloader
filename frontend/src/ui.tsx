/** Общие для вкладок контексты: тема, поиск, всплывающие уведомления, подтверждение. */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

/* ================================================================
   Theme Context
   ================================================================ */
export const ThemeCtx = createContext<{ dark: boolean; toggle: () => void }>({ dark: true, toggle: () => {} });

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [dark, setDark] = useState(() => localStorage.getItem("vp-theme") !== "light");
  const toggle = useCallback(() => {
    setDark((d) => { const next = !d; localStorage.setItem("vp-theme", next ? "dark" : "light"); return next; });
  }, []);
  useEffect(() => {
    document.documentElement.setAttribute("data-bs-theme", dark ? "dark" : "light");
    document.documentElement.classList.toggle("theme-light", !dark);
  }, [dark]);
  return <ThemeCtx.Provider value={{ dark, toggle }}>{children}</ThemeCtx.Provider>;
}

/* ================================================================
   Search Context
   ================================================================ */
export const SearchCtx = createContext<{ query: string; set: (q: string) => void }>({ query: "", set: () => {} });

/* ================================================================
   Toast Context
   ================================================================ */
export type ToastType = "success" | "error" | "warning" | "info";
interface Toast { id: number; type: ToastType; text: string; }

export const ToastCtx = createContext<{ add: (type: ToastType, text: string) => void }>({ add: () => {} });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const add = useCallback((type: ToastType, text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, type, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={{ add }}>
      {children}
      <div className="vp-toast">
        {toasts.map((t) => (
          <div key={t.id} className={`vp-toast-item ${t.type}`}>
            <i className={`bi ${t.type === "success" ? "bi-check-circle-fill text-success" : t.type === "error" ? "bi-x-circle-fill text-danger" : t.type === "warning" ? "bi-exclamation-triangle-fill text-warning" : "bi-info-circle-fill text-accent"}`} />
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() { return useContext(ToastCtx); }

/* ================================================================
   Confirm Context (delete confirmation)
   ================================================================ */
interface ConfirmState { open: boolean; title: string; message: string; onConfirm: () => void; }
export const ConfirmCtx = createContext<{ confirm: (title: string, message: string) => Promise<boolean> }>({ confirm: () => Promise.resolve(false) });

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ConfirmState>({ open: false, title: "", message: "", onConfirm: () => {} });
  const resolverRef = useRef<(v: boolean) => void>(() => {});

  function confirm(title: string, message: string): Promise<boolean> {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setState({ open: true, title, message, onConfirm: () => {} });
    });
  }

  function handleConfirm() { setState((s) => ({ ...s, open: false })); resolverRef.current(true); }
  function handleCancel() { setState((s) => ({ ...s, open: false })); resolverRef.current(false); }

  return (
    <ConfirmCtx.Provider value={{ confirm }}>
      {children}
      {state.open && (
        <div className="modal d-block" tabIndex={-1} style={{ background: "rgba(0,0,0,0.6)" }}>
          <div className="modal-dialog modal-dialog-centered" style={{ maxWidth: 400 }}>
            <div className="modal-content vp">
              <div className="modal-header vp">
                <h6 className="modal-title"><i className="bi bi-exclamation-triangle text-warning me-2" />{state.title}</h6>
              </div>
              <div className="modal-body vp">
                <p className="mb-0">{state.message}</p>
              </div>
              <div className="modal-footer vp">
                <button className="btn btn-vp-outline btn-sm" onClick={handleCancel}>Отмена</button>
                <button className="btn btn-vp-danger btn-sm" onClick={handleConfirm}>Удалить</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </ConfirmCtx.Provider>
  );
}

export function useConfirm() { return useContext(ConfirmCtx); }


/** Цвет бейджа группы, если свой не выбран (как у badge-vp-info). */
export const GROUP_FALLBACK = "#9b8cf5";
