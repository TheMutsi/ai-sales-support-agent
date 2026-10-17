import { isCommand, type Command } from "./commands";

export interface WidgetState {
  /** The chat panel is expanded. */
  open: boolean;
  /** The launcher button is on screen at all (`hide` removes it, `show` brings it back). */
  visible: boolean;
}

/**
 * The widget's state lives outside React so the shop's `Mew(...)` calls can change it
 * before, during or after the UI mounts. React reads it with `useSyncExternalStore`.
 */
export function createController() {
  let state: WidgetState = { open: false, visible: true };
  const listeners = new Set<() => void>();

  const set = (patch: Partial<WidgetState>) => {
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener());
  };

  const reducers: Record<Command, () => void> = {
    open: () => set({ open: true, visible: true }),
    close: () => set({ open: false }),
    show: () => set({ visible: true }),
    hide: () => set({ visible: false, open: false }),
  };

  return {
    getState: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    run(command: unknown) {
      if (!isCommand(command)) {
        console.warn(`Mew: unknown command "${String(command)}"`);
        return;
      }
      reducers[command]();
    },
  };
}

export type Controller = ReturnType<typeof createController>;
