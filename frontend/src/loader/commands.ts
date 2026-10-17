/** Commands a shop can send with `Mew('open')`, `Mew('hide')`, ... */
export const COMMANDS = ["open", "close", "show", "hide"] as const;
export type Command = (typeof COMMANDS)[number];

export function isCommand(value: unknown): value is Command {
  return typeof value === "string" && (COMMANDS as readonly string[]).includes(value);
}
