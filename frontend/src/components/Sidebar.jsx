import React from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Wrench,
  KeyRound,
  ScrollText,
  Settings,
  LogOut,
} from "lucide-react";
import { apiGet, clearToken } from "../api";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/tools", icon: Wrench, label: "Tools (15)" },
  { to: "/tokens", icon: KeyRound, label: "Tokens" },
  { to: "/logs", icon: ScrollText, label: "Logs" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export default function Sidebar() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet("/api/health"),
    refetchInterval: 30000,
    retry: false,
  });

  const handleLogout = () => {
    clearToken();
    window.location.href = "/login";
  };

  return (
    <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col h-screen sticky top-0">
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <h1 className="text-lg font-bold text-blue-400">OD MCP Admin</h1>
        <p className="text-xs text-gray-500 mt-1">Open Design MCP Service</p>
        <p className="text-xs text-gray-500">15 tools · streamableHttp</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-blue-500/10 text-blue-400 font-medium"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
              }`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-gray-800">
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-400 hover:text-red-400 hover:bg-gray-800 transition-colors w-full"
        >
          <LogOut size={18} />
          Logout
        </button>
      </div>
    </aside>
  );
}
