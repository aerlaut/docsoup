declare module 'myambient' {
  /**
   * Mounts a component onto the target element.
   */
  export function mount(component: any, options: MountOptions): ComponentHandle;

  /** Unmounts a previously mounted component. */
  export function unmount(handle: ComponentHandle): void;

  export interface MountOptions {
    target: Element;
    props?: Record<string, any>;
  }

  export interface ComponentHandle {
    destroy(): void;
  }

  export type ComponentType = 'client' | 'server';
}

declare module 'myambient/utils' {
  export function noop(): void;
  export const VERSION: string;
}
