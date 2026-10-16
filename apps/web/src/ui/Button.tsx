import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  loading?: boolean;
  variant?: ButtonVariant;
};

export function Button({
  children,
  className = "",
  disabled,
  loading = false,
  type = "button",
  variant = "primary",
  ...props
}: ButtonProps) {
  return (
    <button
      className={`button button--${variant} ${className}`.trim()}
      disabled={disabled === true || loading}
      type={type}
      {...props}
    >
      {loading ? <span className="button__spinner" aria-hidden="true" /> : null}
      <span>{children}</span>
      {loading ? <span className="sr-only">, выполняется</span> : null}
    </button>
  );
}
