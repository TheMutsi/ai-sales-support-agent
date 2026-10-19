import type { ReactNode } from "react";
import { BadgeIcon, CartIcon, ChatIcon, ChevronDown, ChevronRight, ExchangeIcon, PinIcon, TvIcon } from "./icons";

export const Logo = ({ online = false }: { online?: boolean }) => (
  <span className="mew-logo" aria-hidden="true">
    M{online && <i className="mew-online" />}
  </span>
);

interface Entry {
  label: string;
  icon: ReactNode;
  /** Only an entry with a handler does anything; the others are placeholders for later. */
  onSelect?: () => void;
}

/**
 * The home view: a greeting and the things a visitor can do. Only "Help & Support" leads
 * anywhere (to the chat); the other entries are drawn but do nothing yet.
 */
export function Menu({
  unread = 0,
  onHelp,
  onClose,
}: {
  unread?: number;
  onHelp: () => void;
  onClose: () => void;
}) {
  const entries: Entry[] = [
    { label: "Manage Order", icon: <CartIcon /> },
    { label: "Track my Order", icon: <PinIcon /> },
    { label: "Exchanges & Returns", icon: <ExchangeIcon /> },
    { label: "Manage Memberships", icon: <BadgeIcon /> },
    { label: "Manage my TV Show Order", icon: <TvIcon /> },
    { label: "Help & Support", icon: <ChatIcon />, onSelect: onHelp },
  ];
  return (
    <>
      <header className="mew-header">
        <Logo online />
        <div className="mew-title">
          <strong>Hi There 👋</strong>
          <span>How can we help you today?</span>
        </div>
        <button type="button" className="mew-collapse" aria-label="Minimize chat" onClick={onClose}>
          <ChevronDown />
        </button>
      </header>
      <nav className="mew-menu" aria-label="Menu">
        {entries.map((entry) => (
          <button
            key={entry.label}
            type="button"
            className={entry.onSelect ? "mew-menu-item" : "mew-menu-item mew-inert"}
            aria-disabled={entry.onSelect ? undefined : true}
            onClick={entry.onSelect}
          >
            <span className="mew-menu-icon">{entry.icon}</span>
            <span className="mew-menu-label">{entry.label}</span>
            {entry.onSelect && unread > 0 && (
              <span className="mew-menu-badge" role="status" aria-label={`${unread} unread`}>{unread > 9 ? "9+" : unread}</span>
            )}
            <ChevronRight />
          </button>
        ))}
      </nav>
    </>
  );
}
