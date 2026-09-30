import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

type TrashItem = {
  id: string;
  original_filename: string;
  kind: string;
  capture_ts: string | null;
  deleted_at: string | null;
  size_bytes: number;
};

export default function Deleted() {
  const { user } = useAuth();
  const [needsPin, setNeedsPin] = useState<"set" | "verify" | "ok">(
    user?.has_deleted_pin ? "verify" : "set",
  );
  const [pin, setPin] = useState("");
  const [pinConfirm, setPinConfirm] = useState("");
  const [items, setItems] = useState<TrashItem[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (needsPin === "ok") refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsPin]);

  async function refresh() {
    try {
      const p = await api<{ items: TrashItem[] }>("/api/trash");
      setItems(p.items);
    } catch (e: any) {
      if (e?.status === 403) setNeedsPin("verify");
    }
  }

  async function submitSet() {
    if (pin !== pinConfirm) {
      setErr("PIN mismatch");
      return;
    }
    setErr(null);
    await api("/api/user/deleted-pin", { method: "POST", body: JSON.stringify({ pin }) });
    await api("/api/user/deleted-pin/verify", {
      method: "POST",
      body: JSON.stringify({ pin }),
    });
    setNeedsPin("ok");
  }

  async function submitVerify() {
    setErr(null);
    try {
      await api("/api/user/deleted-pin/verify", {
        method: "POST",
        body: JSON.stringify({ pin }),
      });
      setNeedsPin("ok");
    } catch (e: any) {
      setErr(e?.message ?? "wrong pin");
    }
  }

  async function restore(id: string) {
    await api(`/api/trash/${id}/restore`, { method: "POST", body: JSON.stringify({}) });
    refresh();
  }

  async function permanentDelete(id: string) {
    if (!window.confirm("Permanently delete this asset?")) return;
    await api(`/api/trash/${id}`, { method: "DELETE" });
    refresh();
  }

  if (needsPin === "set") {
    return (
      <div className="mx-auto max-w-sm py-16 space-y-3">
        <h2 className="text-lg font-semibold">Set your Deleted-view PIN</h2>
        <input
          className="w-full rounded border border-slate-300 px-3 py-2"
          type="password"
          placeholder="PIN"
          value={pin}
          onChange={(e) => setPin(e.target.value)}
        />
        <input
          className="w-full rounded border border-slate-300 px-3 py-2"
          type="password"
          placeholder="Confirm PIN"
          value={pinConfirm}
          onChange={(e) => setPinConfirm(e.target.value)}
        />
        {err ? <div className="text-red-500 text-sm">{err}</div> : null}
        <button
          className="w-full rounded bg-brand-500 py-2 text-white"
          onClick={submitSet}
        >
          Set PIN
        </button>
      </div>
    );
  }

  if (needsPin === "verify") {
    return (
      <div className="mx-auto max-w-sm py-16 space-y-3">
        <h2 className="text-lg font-semibold">Enter your Deleted-view PIN</h2>
        <input
          className="w-full rounded border border-slate-300 px-3 py-2"
          type="password"
          value={pin}
          onChange={(e) => setPin(e.target.value)}
        />
        {err ? <div className="text-red-500 text-sm">{err}</div> : null}
        <button className="w-full rounded bg-brand-500 py-2 text-white" onClick={submitVerify}>
          Unlock
        </button>
      </div>
    );
  }

  return (
    <div className="p-4">
      <h2 className="text-lg font-semibold mb-3">Deleted</h2>
      {items.length === 0 ? (
        <div className="text-slate-500">Trash is empty.</div>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li
              key={item.id}
              className="flex items-center gap-3 border border-slate-200 rounded-lg p-3"
            >
              <div className="flex-1">
                <div className="font-medium">{item.original_filename}</div>
                <div className="text-xs text-slate-500">
                  {item.kind} · {(item.size_bytes / 1024 / 1024).toFixed(2)} MB
                </div>
              </div>
              <button
                className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
                onClick={() => restore(item.id)}
              >
                Restore
              </button>
              <button
                className="rounded border border-red-300 px-3 py-1 text-sm text-red-600 hover:bg-red-50"
                onClick={() => permanentDelete(item.id)}
              >
                Delete forever
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
