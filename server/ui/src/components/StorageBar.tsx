import { useEffect, useState } from "react";
import { api } from "../lib/api";

type Quota = {
  used_bytes: number;
  quota_bytes: number;
  asset_count: number;
  deleted_pending_purge_bytes: number;
};

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export default function StorageBar() {
  const [q, setQ] = useState<Quota | null>(null);

  useEffect(() => {
    api<Quota>("/api/storage/quota").then(setQ).catch(() => {});
  }, []);

  if (!q) return <div className="text-xs text-slate-500">Loading storage…</div>;
  const pct = Math.min(100, (q.used_bytes / q.quota_bytes) * 100);
  return (
    <div className="text-xs text-slate-600">
      <div className="mb-1 flex justify-between">
        <span>Storage</span>
        <span>
          {formatBytes(q.used_bytes)} / {formatBytes(q.quota_bytes)}
        </span>
      </div>
      <div className="h-1.5 rounded bg-slate-200 overflow-hidden">
        <div
          className="h-full bg-brand-500"
          style={{ width: `${pct.toFixed(2)}%` }}
        />
      </div>
    </div>
  );
}
