import { useState, useEffect } from 'react';
import { ClientInfo, WebhookConfigData } from './types';
import ClientCard from './ClientCard';
import ChatPanel from './ChatPanel';
import WebhookConfig from './WebhookConfig';

const POLL_INTERVAL = 3000; // 3 seconds

export default function App() {
  const [clients, setClients] = useState<ClientInfo[]>([]);
  const [totalClients, setTotalClients] = useState(0);
  const [onlineClients, setOnlineClients] = useState(0);
  const [selectedClient, setSelectedClient] = useState<string | null>(null);
  const [showWebhook, setShowWebhook] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [serverStatus, setServerStatus] = useState('connecting...');

  // Poll clients list
  useEffect(() => {
    const fetchClients = async () => {
      try {
        const res = await fetch('/api/clients');
        const data = await res.json();
        setClients(data.clients || []);
        setTotalClients(data.total || 0);
        setOnlineClients(data.online || 0);

        // Update selected client data if still selected
        if (selectedClient) {
          const updated = (data.clients || []).find(
            (c: ClientInfo) => c.pc_name === selectedClient
          );
          if (!updated?.online) {
            // Client went offline, keep selected but show offline state
          }
        }
      } catch (e) {
        // Server probably not running
      }
    };

    fetchClients();
    const interval = setInterval(fetchClients, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [selectedClient]);

  // Check server status + repo URL
  useEffect(() => {
    fetch('/api/status')
      .then(r => r.json())
      .then(d => {
        setServerStatus(d.status === 'ok' ? 'online' : 'error');
        setRepoUrl(d.client_repo_url || '');
      })
      .catch(() => setServerStatus('offline'));
  }, []);

  // Repo URL management
  const updateRepoUrl = async (newUrl: string) => {
    try {
      await fetch('/api/repo-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: newUrl }),
      });
      setRepoUrl(newUrl);
    } catch (e) {
      console.error('Failed to update repo URL', e);
    }
  };

  const selectedClientData = clients.find(c => c.pc_name === selectedClient);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🖥️</span>
            <div>
              <h1 className="text-lg font-semibold">ALMA</h1>
              <p className="text-xs text-gray-500">Agent Management Dashboard</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {/* Status badge */}
            <div className="flex items-center gap-2 text-sm">
              <span className={`w-2 h-2 rounded-full ${
                serverStatus === 'online' ? 'bg-green-500 pulse-dot' : 'bg-red-500'
              }`} />
              <span className="text-gray-400">
                {onlineClients}/{totalClients} online
              </span>
            </div>
            {/* Webhook button */}
            <button
              onClick={() => setShowWebhook(!showWebhook)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                showWebhook
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
            >
              ⚡ Webhook
            </button>
          </div>
        </div>
      </header>

      {/* Webhook Config Panel */}
      {showWebhook && (
        <div className="border-b border-gray-800 bg-gray-900/30">
          <div className="max-w-7xl mx-auto px-4 py-4">
            <WebhookConfig />
          </div>
        </div>
      )}

      {/* Repo URL bar */}
      <div className="border-b border-gray-800 bg-gray-900/20">
        <div className="max-w-7xl mx-auto px-4 py-2 flex items-center gap-2 text-sm">
          <span className="text-gray-500">Client Repo:</span>
          <input
            type="text"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            onBlur={() => updateRepoUrl(repoUrl)}
            onKeyDown={(e) => e.key === 'Enter' && updateRepoUrl(repoUrl)}
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300 focus:outline-none focus:border-blue-500 text-xs font-mono"
          />
          <span className="text-xs text-gray-600">(Enter to update → broadcast to all clients)</span>
        </div>
      </div>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {clients.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-500">
            <span className="text-6xl mb-4">📡</span>
            <p className="text-lg">No clients connected</p>
            <p className="text-sm mt-1">
              Run <code className="bg-gray-800 px-2 py-0.5 rounded text-xs">alma-client.exe -server YOUR_IP:8765 -name "PC-Name"</code> on a remote PC
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {clients.map((client) => (
              <ClientCard
                key={client.pc_name}
                client={client}
                isSelected={selectedClient === client.pc_name}
                onSelect={() =>
                  setSelectedClient(
                    selectedClient === client.pc_name ? null : client.pc_name
                  )
                }
              />
            ))}
          </div>
        )}
      </main>

      {/* Chat Panel (slide-over) */}
      {selectedClientData && (
        <ChatPanel
          client={selectedClientData}
          onClose={() => setSelectedClient(null)}
        />
      )}
    </div>
  );
}
