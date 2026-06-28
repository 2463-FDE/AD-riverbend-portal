import type { ReactNode } from "react";

export default function Card({
  title,
  icon,
  action,
  children,
  as: As = "section",
}: {
  title?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  as?: "section" | "div" | "article";
}) {
  return (
    <As className="rb-card">
      {(title || icon || action) && (
        <div className="rb-card__head">
          {icon && <span className="rb-card__icon">{icon}</span>}
          {title && <h2>{title}</h2>}
          {action && <span className="rb-card__action">{action}</span>}
        </div>
      )}
      {children}
    </As>
  );
}
