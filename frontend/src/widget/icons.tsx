import type { ReactNode } from "react";

/** Line icons, drawn inline so the widget stays one script with no image requests. */
function Icon({ children, size = 22 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const CartIcon = () => (
  <Icon>
    <path d="M3 4h2l2.2 10.2a1 1 0 0 0 1 .8h8.6a1 1 0 0 0 1-.8L19.5 8H6" />
    <circle cx="9.5" cy="19" r="1.2" />
    <circle cx="16.5" cy="19" r="1.2" />
  </Icon>
);
export const PinIcon = () => (
  <Icon>
    <path d="M12 21s6-5.6 6-11a6 6 0 1 0-12 0c0 5.4 6 11 6 11Z" />
    <circle cx="12" cy="10" r="2.2" />
  </Icon>
);
export const ExchangeIcon = () => (
  <Icon>
    <path d="M4 12a8 8 0 0 1 13.6-5.7L20 8.5M20 4v4.5h-4.5" />
    <path d="M20 12a8 8 0 0 1-13.6 5.7L4 15.5M4 20v-4.5h4.5" />
  </Icon>
);
export const BadgeIcon = () => (
  <Icon>
    <path d="m12 3 2 1.6 2.5-.2 1 2.3 2.2 1.2-.5 2.5 1.2 2.2-1.9 1.7-.3 2.5-2.5.6L14 20l-2-1.6L10 20l-1.6-2.2-2.5-.6-.3-2.5-1.9-1.7 1.2-2.2-.5-2.5 2.2-1.2 1-2.3 2.5.2L12 3Z" />
    <path d="m12 9 1 2 2.2.3-1.6 1.5.4 2.2L12 14l-2 1 .4-2.2L8.8 11.3 11 11l1-2Z" />
  </Icon>
);
export const TvIcon = () => (
  <Icon>
    <rect x="3" y="6" width="18" height="12" rx="2" />
    <path d="m9 3 3 3 3-3" />
  </Icon>
);
export const ChatIcon = ({ size }: { size?: number }) => (
  <Icon size={size}>
    <path d="M4 5h11a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H9l-3.5 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z" />
    <path d="M18 9h1a2 2 0 0 1 2 2v5a1 1 0 0 1-1 1h-1v2.5L15 17h-4" />
  </Icon>
);
export const ChevronRight = () => (
  <Icon size={18}>
    <path d="m9 6 6 6-6 6" />
  </Icon>
);
export const ChevronDown = ({ size = 22 }: { size?: number }) => (
  <Icon size={size}>
    <path d="m6 9 6 6 6-6" />
  </Icon>
);
export const ChevronLeft = () => (
  <Icon size={16}>
    <path d="m15 6-6 6 6 6" />
  </Icon>
);
export const SendIcon = () => (
  <Icon size={18}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Icon>
);
