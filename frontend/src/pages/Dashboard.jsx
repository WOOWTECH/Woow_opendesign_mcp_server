import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api";
import StatusCard from "../components/StatusCard";
import {
  RefreshCw,
  Server,
  Radio,
  Cpu,
} from "lucide-react";

export default function Dashboard() {
  const {
    data: health,
    isLoading,
    isError,
    error,
    dataUpdatedAt,
    refetch,
  } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet("/api/health"),
    refetchInterval: 30000,
  });

  const lastRefresh = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString()
    : "--";

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw size={24} className="animate-spin text-gray-500" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 text-red-400">
        Failed to load health data: {error?.message || "Unknown error"}
      </div>
    );
  }

  const mcpServer = health?.mcp_server || {};
  const targetApp = health?.target_app || {};
  const proxy = health?.proxy || {};

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-100">Dashboard</h2>
          <p className="text-sm text-gray-500 mt-1">
            Open Design MCP health overview
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-600">
            Last refresh: {lastRefresh}
          </span>
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-2 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm text-gray-300 transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
      </div>

      {/* Service Status */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatusCard
          title="OD Daemon"
          value={targetApp.healthy ? "Online" : "Offline"}
          subtitle={targetApp.version ? `v${targetApp.version}` : targetApp.error || "No daemon info"}
          status={targetApp.healthy ? "green" : "red"}
          icon={Cpu}
        />
        <StatusCard
          title="MCP Server"
          value={mcpServer.healthy ? "Online" : "Offline"}
          subtitle={mcpServer.pod_name || "No pod info"}
          status={mcpServer.healthy ? "green" : "red"}
          icon={Server}
        />
        <StatusCard
          title="Proxy"
          value={proxy.healthy ? "Active" : "Inactive"}
          subtitle={proxy.pod_name || "No pod info"}
          status={proxy.healthy ? "green" : "red"}
          icon={Radio}
        />
      </div>

      {/* Info Cards */}
      <h3 className="text-lg font-semibold text-gray-300">Open Design Info</h3>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatusCard
          title="Daemon Version"
          value={health?.version || "--"}
          status="gray"
          icon={Cpu}
        />
        <StatusCard
          title="AI Agents"
          value={health?.agent_count ?? "--"}
          status="gray"
          icon={Server}
        />
        <StatusCard
          title="Namespace"
          value={health?.namespace || "--"}
          status="gray"
          icon={Radio}
        />
      </div>
    </div>
  );
}
