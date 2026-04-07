type MessageHandler = (data: Record<string, unknown>) => void;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 2000;
  private maxReconnectDelay = 30000;
  private onStatusChange?: (connected: boolean) => void;

  constructor(url?: string) {
    this.url = url || `ws://${typeof window !== "undefined" ? window.location.hostname : "localhost"}:8000/api/ws`;
  }

  connect(onStatusChange?: (connected: boolean) => void) {
    this.onStatusChange = onStatusChange;
    this._connect();
  }

  private _connect() {
    if (typeof window === "undefined") return;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.reconnectDelay = 2000;
        this.onStatusChange?.(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const type = data.type as string;
          if (type && this.handlers.has(type)) {
            this.handlers.get(type)!.forEach((h) => h(data));
          }
          // Also fire wildcard handlers
          if (this.handlers.has("*")) {
            this.handlers.get("*")!.forEach((h) => h(data));
          }
        } catch {
          // ignore parse errors
        }
      };

      this.ws.onclose = () => {
        this.onStatusChange?.(false);
        this._scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch {
      this._scheduleReconnect();
    }
  }

  private _scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay);
      this._connect();
    }, this.reconnectDelay);
  }

  on(type: string, handler: MessageHandler) {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    this.handlers.get(type)!.add(handler);
    return () => {
      this.handlers.get(type)?.delete(handler);
    };
  }

  send(data: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }
}

// Singleton instance
let _instance: WebSocketClient | null = null;

export function getWebSocket(): WebSocketClient {
  if (!_instance) {
    _instance = new WebSocketClient();
  }
  return _instance;
}
