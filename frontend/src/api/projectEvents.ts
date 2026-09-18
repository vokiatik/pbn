import { buildWebSocketUrl } from "./client";

// Cloudflare and deploys can close otherwise healthy sockets. Reconcile saved
// state on each connection, since events during a disconnect are not replayed.
export function subscribeToProjectEvents(
    publicId: string,
    onMessage: (event: MessageEvent) => void,
    onConnected: () => void,
): () => void {
    let stopped = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let socket: WebSocket;

    const connect = () => {
        socket = new WebSocket(buildWebSocketUrl(publicId));
        socket.onopen = () => {
            retry = 0;
            if (!stopped) onConnected();
        };
        socket.onmessage = (event) => {
            if (!stopped) onMessage(event);
        };
        socket.onerror = () => socket.close();
        socket.onclose = () => {
            if (stopped) return;
            const delay = Math.min(30_000, 1_000 * 2 ** Math.min(retry++, 5));
            timer = setTimeout(connect, delay + Math.random() * 500);
        };
    };

    connect();
    return () => {
        stopped = true;
        clearTimeout(timer);
        socket.close();
    };
}
