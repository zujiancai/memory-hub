import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { api } from "../lib/api";

type Asset = {
  id: string;
  kind: string;
  original_filename: string;
  capture_ts: string | null;
  width: number | null;
  height: number | null;
  thumbnail_url: string | null;
};

type Page = { items: Asset[]; next_cursor: string | null };

const PAGE_SIZE = 60;
const COLUMNS = 4;
const ROW_HEIGHT = 220;

function monthBucket(iso: string | null): string {
  if (!iso) return "Undated";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "long" });
}

export default function Library() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (assets.length === 0 && !done) loadMore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadMore() {
    if (loading || done) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (cursor) params.set("cursor", cursor);
      const p = await api<Page>(`/api/asset?${params.toString()}`);
      setAssets((prev) => [...prev, ...p.items]);
      setCursor(p.next_cursor);
      if (!p.next_cursor) setDone(true);
    } finally {
      setLoading(false);
    }
  }

  // Group items into rows with sticky month headers.
  type Row =
    | { kind: "header"; label: string }
    | { kind: "grid"; assets: Asset[] };
  const rows: Row[] = [];
  let currentBucket: string | null = null;
  let queue: Asset[] = [];
  for (const asset of assets) {
    const bucket = monthBucket(asset.capture_ts);
    if (bucket !== currentBucket) {
      if (queue.length) {
        for (let i = 0; i < queue.length; i += COLUMNS) {
          rows.push({ kind: "grid", assets: queue.slice(i, i + COLUMNS) });
        }
        queue = [];
      }
      rows.push({ kind: "header", label: bucket });
      currentBucket = bucket;
    }
    queue.push(asset);
  }
  if (queue.length) {
    for (let i = 0; i < queue.length; i += COLUMNS) {
      rows.push({ kind: "grid", assets: queue.slice(i, i + COLUMNS) });
    }
  }

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => (rows[index].kind === "header" ? 40 : ROW_HEIGHT),
    overscan: 6,
  });

  useEffect(() => {
    const el = parentRef.current;
    if (!el) return;
    const onScroll = () => {
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 200) loadMore();
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor, loading, done]);

  return (
    <div ref={parentRef} className="h-full overflow-auto p-4">
      {assets.length === 0 && !loading ? (
        <div className="text-center text-slate-400 pt-24">
          No photos yet. Use the Upload button to add some.
        </div>
      ) : null}
      <div
        style={{
          height: virtualizer.getTotalSize(),
          position: "relative",
          width: "100%",
        }}
      >
        {virtualizer.getVirtualItems().map((v) => {
          const row = rows[v.index];
          return (
            <div
              key={v.key}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                transform: `translateY(${v.start}px)`,
                height: v.size,
              }}
            >
              {row.kind === "header" ? (
                <div className="sticky top-0 bg-slate-50/95 backdrop-blur px-2 py-2 text-sm font-semibold text-slate-700">
                  {row.label}
                </div>
              ) : (
                <div className="grid grid-cols-4 gap-2 px-2">
                  {row.assets.map((asset) => (
                    <div
                      key={asset.id}
                      className="aspect-square rounded-lg bg-slate-200 overflow-hidden"
                    >
                      {asset.thumbnail_url ? (
                        <img
                          src={asset.thumbnail_url}
                          alt={asset.original_filename}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="h-full w-full flex items-center justify-center text-xs text-slate-500">
                          {asset.kind}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {loading ? (
        <div className="text-center text-slate-500 py-4">Loading…</div>
      ) : null}
    </div>
  );
}
