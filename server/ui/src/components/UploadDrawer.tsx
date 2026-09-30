import { useState } from "react";
import { api, sha256Hex } from "../lib/api";

type Props = { open: boolean; onClose: () => void };

type ProgressItem = {
  name: string;
  total: number;
  done: number;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
};

export default function UploadDrawer({ open, onClose }: Props) {
  const [items, setItems] = useState<ProgressItem[]>([]);

  async function handleFiles(fileList: FileList | null) {
    if (!fileList) return;
    const files = Array.from(fileList);
    const initial: ProgressItem[] = files.map((f) => ({
      name: f.name,
      total: f.size,
      done: 0,
      status: "pending",
    }));
    setItems((prev) => [...initial, ...prev]);

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      try {
        setItems((prev) => updateAt(prev, i, { status: "uploading" }));
        const bytes = await file.arrayBuffer();
        const sha = await sha256Hex(bytes);
        const pre = await api<{ exists: boolean; upload_url?: string }>(
          "/api/asset/precheck",
          { method: "POST", body: JSON.stringify({ sha256: sha, size: file.size }) },
        );
        if (!pre.exists) {
          const urlresp = await api<{ upload_url: string }>("/api/asset/upload-url", {
            method: "POST",
            body: JSON.stringify({
              sha256: sha,
              size: file.size,
              mime_type: file.type,
            }),
          });
          await uploadWithProgress(
            urlresp.upload_url,
            file,
            (loaded) =>
              setItems((prev) => updateAt(prev, i, { done: loaded })),
          );
        } else {
          setItems((prev) => updateAt(prev, i, { done: file.size }));
        }
        await api("/api/asset", {
          method: "POST",
          body: JSON.stringify({
            sha256: sha,
            size: file.size,
            original_filename: file.name,
            mime_type: file.type,
            kind: file.type.startsWith("video/") ? "video" : "photo",
          }),
        });
        setItems((prev) => updateAt(prev, i, { status: "done", done: file.size }));
      } catch (e: any) {
        setItems((prev) =>
          updateAt(prev, i, { status: "error", error: e?.message ?? "failed" }),
        );
      }
    }
  }

  if (!open) return null;
  return (
    <div className="fixed inset-y-0 right-0 z-50 w-96 border-l border-slate-200 bg-white shadow-xl flex flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="font-medium">Uploads</div>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-800">
          ✕
        </button>
      </div>
      <div className="p-4">
        <label className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-200 py-6 text-slate-500 hover:bg-slate-50 cursor-pointer">
          <span>Select files</span>
          <input
            type="file"
            multiple
            className="hidden"
            onChange={(e) => handleFiles(e.currentTarget.files)}
          />
        </label>
      </div>
      <ul className="flex-1 overflow-auto px-4 pb-4 space-y-2">
        {items.map((item, idx) => (
          <li key={`${item.name}-${idx}`} className="text-sm">
            <div className="flex justify-between">
              <span className="truncate max-w-[70%]">{item.name}</span>
              <span className="text-slate-500 text-xs">{item.status}</span>
            </div>
            <div className="mt-1 h-1 rounded bg-slate-200">
              <div
                className={`h-full rounded ${
                  item.status === "error" ? "bg-red-500" : "bg-brand-500"
                }`}
                style={{
                  width: item.total
                    ? `${(item.done / item.total) * 100}%`
                    : "0%",
                }}
              />
            </div>
            {item.error ? (
              <div className="text-xs text-red-500 mt-1">{item.error}</div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function updateAt<T>(list: T[], index: number, patch: Partial<T>): T[] {
  const next = list.slice();
  next[index] = { ...next[index], ...patch } as T;
  return next;
}

function uploadWithProgress(
  url: string,
  file: File,
  onProgress: (loaded: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    // The fake local SAS scheme is only meaningful during automated tests;
    // in production the URL is a real Azure Blob SAS.
    if (url.startsWith("memoryhub-local://")) {
      onProgress(file.size);
      resolve();
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("x-ms-blob-type", "BlockBlob");
    xhr.upload.onprogress = (ev) => onProgress(ev.loaded);
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload ${xhr.status}`)));
    xhr.onerror = () => reject(new Error("network error"));
    xhr.send(file);
  });
}
