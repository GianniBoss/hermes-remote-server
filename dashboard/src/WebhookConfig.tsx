import { useState, useEffect } from 'react';
import { WebhookConfigData } from './types';

export default function WebhookConfig() {
  const [config, setConfig] = useState<WebhookConfigData>({
    url: '',
    interval_seconds: 30,
    enabled: false,
    last_sent_at: 0,
    last_status_code: 0,
    last_error: '',
  });
  const [saving, setSaving] = useState(false);
  const [triggerStatus, setTriggerStatus] = useState('');

  // Load current config
  useEffect(() => {
    fetch('/api/webhook/config')
      .then(r => r.json())
      .then(d => setConfig(d))
      .catch(() => {});
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await fetch('/api/webhook/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
    } catch (e) {
      console.error(e);
    }
    setSaving(false);
  };

  const triggerNow = async () => {
    setTriggerStatus('sending...');
    try {
      const r = await fetch('/api/webhook/trigger', { method: 'POST' });
      const d = await r.json();
      setTriggerStatus(d.status === 'sent'
        ? `Sent! HTTP ${d.http_code}, ${d.clients_count} clients`
        : `Error: ${d.error || d.status}`
      );
    } catch (e: any) {
      setTriggerStatus(`Error: ${e.message}`);
    }
    setTimeout(() => setTriggerStatus(''), 5000);
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-300">Webhook Configuration</h3>
      <p className="text-xs text-gray-500">
        JSON with all client data will be POSTed to this URL periodically.
      </p>

      <div className="flex gap-2">
        <input
          type="url"
          value={config.url}
          onChange={e => setConfig({ ...config, url: e.target.value })}
          onBlur={save}
          placeholder="https://your-server.com/webhook"
          className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
        />
        <input
          type="number"
          value={config.interval_seconds}
          onChange={e => setConfig({ ...config, interval_seconds: Math.max(5, parseInt(e.target.value) || 30) })}
          onBlur={save}
          className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          title="Interval in seconds"
        />
        <span className="text-xs text-gray-600 self-center">seconds</span>
      </div>

      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={e => {
              setConfig({ ...config, enabled: e.target.checked });
              setTimeout(save, 100);
            }}
            className="rounded bg-gray-800 border-gray-700"
          />
          <span className="text-sm text-gray-300">Enabled</span>
        </label>

        <button
          onClick={triggerNow}
          disabled={!config.url}
          className="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Test Now
        </button>

        {triggerStatus && (
          <span className={`text-xs ${triggerStatus.startsWith('Sent') ? 'text-green-400' : 'text-yellow-400'}`}>
            {triggerStatus}
          </span>
        )}
      </div>

      {/* Last send status */}
      {config.last_sent_at > 0 && (
        <div className="text-xs text-gray-600">
          Last sent: {new Date(config.last_sent_at * 1000).toLocaleString()}
          {config.last_status_code > 0 && (
            <span className={config.last_status_code < 400 ? 'text-green-500' : 'text-red-500'}>
              {' '}(HTTP {config.last_status_code})
            </span>
          )}
          {config.last_error && (
            <span className="text-red-500"> — {config.last_error}</span>
          )}
        </div>
      )}
    </div>
  );
}
