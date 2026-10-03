import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * One action in an editor's action row (UI doc, *The editor head*): an icon
 * and its label, quiet until pointed at, so the row reads as a list of
 * things you can do rather than a second set of primary buttons beside
 * Deploy.
 *
 * `tone="danger"` stays as quiet as its neighbours and turns red only on
 * hover; `tone="done"` is a settled state (Mark reviewed, once pressed).
 */
export function ActionLink({
  icon,
  children,
  tone,
  className,
  ...button
}: {
  icon: ReactNode;
  children: ReactNode;
  tone?: "danger" | "done";
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const classes = ["action-link", tone ? `action-link--${tone}` : "", className ?? ""]
    .filter(Boolean)
    .join(" ");
  return (
    <button type="button" className={classes} {...button}>
      {icon}
      {children}
    </button>
  );
}

/** The divider between an action row's groups. */
export function ActionDivider() {
  return <span className="action-row__divider" aria-hidden="true" />;
}
