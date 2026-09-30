import { Dialog } from "@headlessui/react";
import { useEffect, useMemo, useState } from "react";
import { createAvatar } from "@dicebear/core";
import { avataaars, notionists } from "@dicebear/collection";
import { api, getAccessToken } from "../lib/api";
import { API_BASE_URL } from "../lib/config";
import { useAuth } from "../lib/auth";

type Props = { open: boolean; onClose: () => void };

const STYLES: Record<string, any> = { avataaars, notionists };

export default function UserModal({ open, onClose }: Props) {
  const { user, reload, logout } = useAuth();
  const [friendly, setFriendly] = useState(user?.friendly_name ?? "");
  const [password, setPassword] = useState("");
  const [style, setStyle] = useState<"avataaars" | "notionists">(
    (user?.avatar_generator_json?.style as any) ?? "avataaars",
  );
  const [seed, setSeed] = useState<string>(
    user?.avatar_generator_json?.seed ?? user?.email ?? "seed",
  );
  const [backgroundColor, setBackgroundColor] = useState(
    user?.avatar_generator_json?.backgroundColor ?? "b6e3f4",
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setFriendly(user.friendly_name);
      setStyle((user.avatar_generator_json?.style as any) ?? "avataaars");
      setSeed(user.avatar_generator_json?.seed ?? user.email);
      setBackgroundColor(user.avatar_generator_json?.backgroundColor ?? "b6e3f4");
    }
  }, [user]);

  const avatarSvg = useMemo(() => {
    const collection = STYLES[style];
    return createAvatar(collection, { seed, backgroundColor: [backgroundColor] }).toString();
  }, [style, seed, backgroundColor]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const patch: Record<string, unknown> = { friendly_name: friendly };
      if (password) patch.password = password;
      patch.avatar_generator_json = { style, seed, backgroundColor };
      await api("/api/user/me", { method: "PATCH", body: JSON.stringify(patch) });

      // Rasterize the SVG to PNG and upload as the avatar blob.
      const png = await svgToPng(avatarSvg, 256);
      const buf = await png.arrayBuffer();
      await fetch(`${API_BASE_URL}/api/user/me/avatar`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "image/png",
          Authorization: `Bearer ${getAccessToken() ?? ""}`,
        },
        body: buf,
      });
      await reload();
      onClose();
    } catch (e: any) {
      setErr(e?.message ?? "save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-slate-900/40" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
          <Dialog.Title className="text-lg font-semibold text-slate-800">
            Your account
          </Dialog.Title>
          <div className="mt-4 flex gap-4">
            <div className="w-24 h-24 rounded-full bg-slate-100 overflow-hidden shrink-0">
              <div
                className="w-full h-full"
                dangerouslySetInnerHTML={{ __html: avatarSvg }}
              />
            </div>
            <div className="flex-1 space-y-2">
              <label className="block text-sm font-medium">Friendly name</label>
              <input
                className="w-full rounded border border-slate-200 px-2 py-1"
                value={friendly}
                onChange={(e) => setFriendly(e.target.value)}
              />
              <label className="block text-sm font-medium mt-3">Change password</label>
              <input
                type="password"
                placeholder="Leave blank to keep current"
                className="w-full rounded border border-slate-200 px-2 py-1"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <label className="text-sm">
              Avatar style
              <select
                className="mt-1 w-full rounded border border-slate-200 px-2 py-1"
                value={style}
                onChange={(e) => setStyle(e.target.value as any)}
              >
                <option value="avataaars">Avataaars</option>
                <option value="notionists">Notionists</option>
              </select>
            </label>
            <label className="text-sm">
              Seed
              <input
                className="mt-1 w-full rounded border border-slate-200 px-2 py-1"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
              />
            </label>
            <label className="text-sm col-span-2">
              Background color (hex, no #)
              <input
                className="mt-1 w-full rounded border border-slate-200 px-2 py-1"
                value={backgroundColor}
                onChange={(e) => setBackgroundColor(e.target.value.replace(/^#/, ""))}
              />
            </label>
          </div>
          {err ? <div className="mt-2 text-sm text-red-500">{err}</div> : null}
          <div className="mt-6 flex justify-between">
            <button
              className="text-sm text-slate-500 hover:text-slate-800"
              onClick={logout}
            >
              Sign out
            </button>
            <div className="flex gap-2">
              <button
                className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
                onClick={onClose}
                disabled={saving}
              >
                Cancel
              </button>
              <button
                className="rounded-lg bg-brand-500 px-3 py-2 text-sm text-white hover:bg-brand-600 disabled:opacity-50"
                onClick={save}
                disabled={saving}
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}

async function svgToPng(svg: string, size: number): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const img = new Image();
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error("image load failed"));
    img.src = url;
  });
  ctx.drawImage(img, 0, 0, size, size);
  URL.revokeObjectURL(url);
  return await new Promise((res) =>
    canvas.toBlob((b) => res(b as Blob), "image/png"),
  );
}
