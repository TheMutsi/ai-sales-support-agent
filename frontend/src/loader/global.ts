import type { Controller } from "./controller";

type MewCall = (command: string, ...args: unknown[]) => void;
type QueueingMew = MewCall & { q?: IArguments[] };

/**
 * Replaces the shop's queueing stub with the real `Mew` function.
 *
 * The shop's snippet defines `window.Mew` as a function that only pushes its arguments onto
 * `Mew.q`, so `Mew('open')` is safe to call before this script has loaded. Once we are ready we
 * replay that queue in order and from then on run commands immediately (same pattern as
 * Google Analytics and Intercom).
 */
export function installGlobal(target: Window, controller: Controller): void {
  const queued = ((target as unknown as { Mew?: QueueingMew }).Mew?.q ?? []) as ArrayLike<unknown>[];
  const mew: MewCall = (command) => controller.run(command);
  (target as unknown as { Mew: MewCall }).Mew = mew;
  for (const args of Array.from(queued)) mew(...(Array.from(args) as [string, ...unknown[]]));
}

/** Reads the public key out of `<script src=".../mew.js?key=pk_...">`. */
export function readKey(script: HTMLScriptElement | null): string | null {
  if (!script?.src) return null;
  return new URL(script.src, location.href).searchParams.get("key");
}
