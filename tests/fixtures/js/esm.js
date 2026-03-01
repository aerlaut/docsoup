/**
 * Adds two numbers together.
 * @param {number} a - First number
 * @param {number} b - Second number
 * @returns {number}
 */
export function add(a, b) {
  return a + b;
}

// Simple subtraction
export function subtract(a, b) {
  return a - b;
}

/**
 * A simple event emitter.
 */
export class EventEmitter {
  /** Register an event listener. */
  on(event, listener) {}

  /** Remove an event listener. */
  off(event, listener) {}

  /** Emit an event. */
  emit(event, ...args) {}
}

/** Library version string. */
export const VERSION = "1.0.0";

export let counter = 0;

export default function defaultExport() {}
