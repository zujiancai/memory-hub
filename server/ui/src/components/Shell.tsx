import { ReactNode, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  PhotoIcon,
  ClockIcon,
  LockClosedIcon,
  CloudArrowUpIcon,
} from "@heroicons/react/24/outline";
import { useAuth } from "../lib/auth";
import UploadDrawer from "./UploadDrawer";
import UserModal from "./UserModal";
import StorageBar from "./StorageBar";

type Props = { children: ReactNode };

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
    isActive ? "bg-brand-500 text-white" : "text-slate-700 hover:bg-slate-100"
  }`;

export default function Shell({ children }: Props) {
  const { user } = useAuth();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [userModalOpen, setUserModalOpen] = useState(false);
  const navigate = useNavigate();

  if (!user) return null;

  return (
    <div className="flex h-screen">
      <aside className="flex w-64 flex-col border-r border-slate-200 bg-white">
        <div className="px-4 py-4 text-lg font-semibold text-brand-700">
          Memory Hub
        </div>
        <nav className="flex-1 space-y-1 px-3">
          <NavLink to="/" end className={linkClass}>
            <PhotoIcon className="h-5 w-5" /> Library
          </NavLink>
          <NavLink to="/recently-saved" className={linkClass}>
            <ClockIcon className="h-5 w-5" /> Recently Saved
          </NavLink>
          <NavLink to="/deleted" className={linkClass}>
            <LockClosedIcon className="h-5 w-5" /> Deleted
          </NavLink>
        </nav>
        <div className="border-t border-slate-200 p-3 space-y-3">
          <StorageBar />
          <button
            type="button"
            onClick={() => setUserModalOpen(true)}
            className="flex w-full items-center gap-3 rounded-lg px-2 py-1 text-left hover:bg-slate-100"
          >
            <div className="h-8 w-8 rounded-full bg-brand-500 text-white flex items-center justify-center text-sm font-semibold">
              {user.friendly_name.slice(0, 1).toUpperCase()}
            </div>
            <div className="flex-1 truncate">
              <div className="text-sm font-medium">{user.friendly_name}</div>
              <div className="truncate text-xs text-slate-500">{user.email}</div>
            </div>
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-hidden flex flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-6 py-3">
          <div className="flex-1 text-lg font-semibold text-slate-800">Library</div>
          <button
            className="inline-flex items-center gap-2 rounded-lg bg-brand-500 px-3 py-2 text-sm font-medium text-white hover:bg-brand-600"
            onClick={() => setUploadOpen(true)}
          >
            <CloudArrowUpIcon className="h-5 w-5" /> Upload
          </button>
        </header>
        <div className="flex-1 overflow-auto bg-slate-50">{children}</div>
      </main>
      <UploadDrawer open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <UserModal open={userModalOpen} onClose={() => setUserModalOpen(false)} />
    </div>
  );
}
