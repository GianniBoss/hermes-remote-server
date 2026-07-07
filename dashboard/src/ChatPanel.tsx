import { useState, useRef, useEffect } from 'react';
import { ClientInfo, TaskResult } from './types';

interface Props {
  client: ClientInfo;
  onClose: () => void;
}

interface ChatMessage {
  id: string;
  type: 'command' | 'result' | 'error' | 'system';
  text: string;
  timestamp: string;
  taskId?: string;
}

export default function ChatPanel({ client, onClose }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Send command
  const sendCommand = async () => {
    const cmd = input.trim();
    if (!cmd) return;

    const clientMsgId = Math.random().toString(36).slice(2, 10);
    setMessages(prev => [...prev, {
      id: clientMsgId,
      type: 'command',
      text: cmd,
      timestamp: new Date().toISOString(),
    }]);
    setInput('');
    setLoading(true);

    try {
      // Send command — server returns the real task_id
      const res = await fetch(`/api/clients/${encodeURIComponent(client.pc_name)}/exec`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd }),
      });
      const data = await res.json();
      const taskId = data.task_id;

      if (!taskId) throw new Error('No task_id returned');

      // Poll for result
      let attempts = 0;
      const maxAttempts = 120; // 2 min
      const pollInterval = setInterval(async () => {
        attempts++;
        try {
          const r = await fetch(`/api/tasks/${taskId}`);
          const result = await r.json();
          if (result.status === 'pending') {
            // Not done yet — keep polling
            if (attempts >= maxAttempts) {
              clearInterval(pollInterval);
              setLoading(false);
              setMessages(prev => [...prev, {
                id: taskId + '-timeout',
                type: 'error',
                text: 'Command timed out (no response after 2 min)',
                timestamp: new Date().toISOString(),
              }]);
            }
          } else {
            // Result received
            clearInterval(pollInterval);
            setLoading(false);
            const output = [
              result.stdout && `STDOUT:\n${result.stdout}`,
              result.stderr && `STDERR:\n${result.stderr}`,
              result.error && `ERROR: ${result.error}`,
            ].filter(Boolean).join('\n\n') || '(no output)';
            setMessages(prev => [...prev, {
              id: taskId + '-result',
              type: result.exit_code === 0 ? 'result' : 'error',
              text: output,
              timestamp: result.timestamp || new Date().toISOString(),
            }]);
          }
        } catch {
          // Network error — keep polling
        }
      }, 1000);
    } catch (e: any) {
      setLoading(false);
      setMessages(prev => [...prev, {
        id: clientMsgId + '-fail',
        type: 'error',
        text: `Failed to send: ${e.message}`,
        timestamp: new Date().toISOString(),
      }]);
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 w-full max-w-md bg-gray-900 border-l border-gray-800 shadow-2xl slide-in z-20 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${client.online ? 'bg-green-500 pulse-dot' : 'bg-gray-600'}`} />
          <h2 className="font-semibold">{client.pc_name}</h2>
        </div>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-300 text-xl leading-none px-2"
        >
          ✕
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <div className="text-center text-gray-600 py-10">
            <p className="text-4xl mb-2">💻</p>
            <p className="text-sm">Send a command to {client.pc_name}</p>
            <p className="text-xs mt-1 text-gray-700">
              Example: <code className="bg-gray-800 px-1 rounded">dir C:\</code> or{' '}
              <code className="bg-gray-800 px-1 rounded">systeminfo</code>
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.type === 'command' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
              msg.type === 'command'
                ? 'bg-blue-600 text-white'
                : msg.type === 'error'
                  ? 'bg-red-900/50 border border-red-800 text-red-200'
                  : 'bg-gray-800 text-gray-200'
            }`}>
              <pre className="whitespace-pre-wrap font-mono text-xs break-all">{msg.text}</pre>
              <div className={`text-xs mt-1 ${
                msg.type === 'command' ? 'text-blue-200' : 'text-gray-500'
              }`}>
                {new Date(msg.timestamp).toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-800 rounded-lg px-3 py-2 text-sm text-gray-400 flex items-center gap-2">
              <span className="inline-flex gap-1">
                <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
              Executing...
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-gray-800">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendCommand()}
            placeholder={`Type a command for ${client.pc_name}...`}
            disabled={!client.online || loading}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 disabled:opacity-50"
            autoFocus
          />
          <button
            onClick={sendCommand}
            disabled={!client.online || loading || !input.trim()}
            className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-600 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            {loading ? '...' : 'Send'}
          </button>
        </div>
        {!client.online && (
          <p className="text-xs text-red-500 mt-2">Client is offline — cannot send commands</p>
        )}
      </div>
    </div>
  );
}
