// Non-exported top-level declarations, re-exported via export clause below.

/** Creates a server instance. */
interface ServerOptions {
  port: number;
  host?: string;
}

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

declare class Server {
  start(): Promise<void>;
  stop(): void;
}

declare function createServer(options: ServerOptions): Server;

// Single export clause re-exporting the above declarations.
export { type ServerOptions, type LogLevel, Server, createServer };
