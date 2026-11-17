import type { GetToken } from "../data/auth";
import type { Controller } from "./controller";

export interface MewConfig {
  getToken?: GetToken;
  sound?: boolean;
}

export type ContextCommand = "addProperty" | "removeProperty" | "addTag" | "removeTag";
const CONTEXT_COMMANDS: readonly string[] = ["addProperty", "removeProperty", "addTag", "removeTag"];

type MewCall = (command: string, ...args: unknown[]) => void;
type QueueingMew = MewCall & { q?: IArguments[] };

export function installGlobal(
  target: Window,
  controller: Controller,
  onConfig: (options: MewConfig) => void = () => {},
  onContext: (command: ContextCommand, ...args: unknown[]) => void = () => {},
): void {
  const queued = ((target as unknown as { Mew?: QueueingMew }).Mew?.q ?? []) as ArrayLike<unknown>[];
  const mew: MewCall = (command, ...args) => {
    if (command === "config") onConfig((args[0] ?? {}) as MewConfig);
    else if (CONTEXT_COMMANDS.includes(command)) onContext(command as ContextCommand, ...args);
    else controller.run(command);
  };
  (target as unknown as { Mew: MewCall }).Mew = mew;
  for (const args of Array.from(queued)) mew(...(Array.from(args) as [string, ...unknown[]]));
}

export function readKey(script: HTMLScriptElement | null): string | null {
  if (!script?.src) return null;
  return new URL(script.src, location.href).searchParams.get("key");
}
