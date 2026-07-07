import { ClientInfo } from './types';

function Bar({ label, value, color }: { label: string; value: number; color: string }) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-8 text-gray-500">{label}</span>
      <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-10 text-right text-gray-400 tabular-nums">{pct.toFixed(0)}%</span>
    </div>
  );
}

function formatUptime(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${hours.toFixed(0)}h`;
  const d = Math.floor(hours / 24);
  const h = Math.floor(hours % 24);
  return `${d}d ${h}h`;
}

function formatBytes(gb: number): string {
  if (gb >= 1000) return `${(gb / 1000).toFixed(1)}TB`;
  return `${gb.toFixed(0)}GB`;
}

interface Props {
  client: ClientInfo;
  isSelected: boolean;
  onSelect: () => void;
}

export default function ClientCard({ client, isSelected, onSelect }: Props) {
  const m = client.last_metrics;
  const isOnline = client.online;

  return (
    <div
      onClick={onSelect}
      className={`
        fade-in rounded-xl border p-4 cursor-pointer transition-all duration-200
        ${isSelected
          ? 'border-blue-500 bg-blue-500/10 shadow-lg shadow-blue-500/10'
          : isOnline
            ? 'border-gray-700/50 bg-gray-900/50 hover:border-gray-600 hover:bg-gray-900/80'
            : 'border-gray-800 bg-gray-900/30 opacity-60'
        }
      `}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${
            isOnline ? 'bg-green-500 pulse-dot' : 'bg-gray-600'
          }`} />
          <h3 className="font-semibold text-gray-100 truncate max-w-[140px]">
            {client.pc_name}
          </h3>
        </div>
        <span className="text-xs text-gray-500">
          {client.version ? `v${client.version}` : ''}
        </span>
      </div>

      {/* Hostname + IP */}
      <div className="text-xs text-gray-500 mb-3 truncate">
        {m?.hostname || client.hostname || '—'}
        {client.client_ip && <span className="ml-2 text-gray-700">{client.client_ip}</span>}
      </div>

      {/* Metrics bars */}
      {m ? (
        <div className="space-y-2">
          <Bar label="CPU" value={m.cpu_percent} color={m.cpu_percent > 80 ? 'bg-red-500' : m.cpu_percent > 50 ? 'bg-yellow-500' : 'bg-green-500'} />
          <Bar label="RAM" value={m.ram_percent} color={m.ram_percent > 80 ? 'bg-red-500' : m.ram_percent > 50 ? 'bg-yellow-500' : 'bg-blue-500'} />
          <Bar label="DISK" value={m.disk_percent} color={m.disk_percent > 80 ? 'bg-red-500' : m.disk_percent > 50 ? 'bg-yellow-500' : 'bg-purple-500'} />
        </div>
      ) : (
        <div className="text-xs text-gray-600 italic py-2">Waiting for metrics...</div>
      )}

      {/* Footer stats */}
      {m && (
        <div className="mt-3 pt-3 border-t border-gray-800 flex justify-between text-xs text-gray-500">
          <span>🖥 {m.num_cpu} CPU</span>
          <span>💾 {formatBytes(m.ram_total_gb)}</span>
          <span>⏱ {formatUptime(m.uptime_hours)}</span>
        </div>
      )}

      {/* Action hint */}
      {isOnline && (
        <div className="mt-2 text-xs text-center text-gray-600">
          {isSelected ? 'Click to close' : 'Click to send commands'}
        </div>
      )}
    </div>
  );
}
