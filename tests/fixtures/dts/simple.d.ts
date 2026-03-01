/**
 * Adds two numbers together.
 * @param a First number
 * @param b Second number
 */
export declare function add(a: number, b: number): number;

/** Subtracts b from a. */
export declare function subtract(a: number, b: number): number;

// No JSDoc — plain function
export declare function noop(): void;

export declare class EventEmitter {
  /** Register an event listener. */
  on(event: string, listener: Function): this;
  /** Remove a listener. */
  off(event: string, listener: Function): this;
  emit(event: string, ...args: any[]): boolean;
}

export interface Config {
  timeout?: number;
  retries: number;
  baseUrl: string;
}

export declare type ID = string | number;

export declare enum LogLevel {
  Debug,
  Info,
  Warn,
  Error,
}

export declare const VERSION: string;
export declare const MAX_RETRIES: number;
