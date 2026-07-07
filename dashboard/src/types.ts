export interface SystemMetrics {
  ts: number;
  cpu_percent: number;
  ram_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  disk_percent: number;
  disk_used_gb: number;
  disk_total_gb: number;
  uptime_hours: number;
  hostname: string;
  os: string;
  num_cpu: number;
}

export interface ClientInfo {
  pc_name: string;
  hostname: string;
  version: string;
  client_ip: string;
  connected_at: number;
  last_seen: number;
  last_metrics: SystemMetrics | null;
  online: boolean;
  idle_seconds: number;
}

export interface TaskResult {
  task_id: string;
  pc_name: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  error: string;
  timestamp: string;
}

export interface WebhookConfigData {
  url: string;
  interval_seconds: number;
  enabled: boolean;
  last_sent_at: number;
  last_status_code: number;
  last_error: string;
}
