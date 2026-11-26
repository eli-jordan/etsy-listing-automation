import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
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

export function ActionDivider() {
  return <span className="action-row__divider" aria-hidden="true" />;
}
