import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

import { decimalSeparator } from "./money";

interface FieldFrameProps {
  children: (inputId: string, describedBy: string | undefined) => ReactNode;
  error?: string | undefined;
  hint?: string | undefined;
  id?: string | undefined;
  label: string;
}

function FieldFrame({ children, error, hint, id, label }: FieldFrameProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = hint === undefined ? undefined : `${inputId}-hint`;
  const errorId = error === undefined ? undefined : `${inputId}-error`;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={`field ${error === undefined ? "" : "field--error"}`.trim()}>
      <label className="field__label" htmlFor={inputId}>
        {label}
      </label>
      {children(inputId, describedBy)}
      {hint === undefined ? null : (
        <span className="field__hint" id={hintId}>
          {hint}
        </span>
      )}
      {error === undefined ? null : (
        <span className="field__error" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

type InputFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  error?: string | undefined;
  hint?: string | undefined;
  id?: string | undefined;
  label: string;
};

export function InputField({ error, hint, id, label, className = "", ...props }: InputFieldProps) {
  return (
    <FieldFrame error={error} hint={hint} id={id} label={label}>
      {(inputId, describedBy) => (
        <input
          aria-describedby={describedBy}
          aria-invalid={error === undefined ? undefined : true}
          className={`control ${className}`.trim()}
          id={inputId}
          {...props}
        />
      )}
    </FieldFrame>
  );
}

type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> & {
  children: ReactNode;
  error?: string | undefined;
  hint?: string | undefined;
  id?: string | undefined;
  label: string;
};

export function SelectField({
  children,
  error,
  hint,
  id,
  label,
  className = "",
  ...props
}: SelectFieldProps) {
  return (
    <FieldFrame error={error} hint={hint} id={id} label={label}>
      {(inputId, describedBy) => (
        <select
          aria-describedby={describedBy}
          aria-invalid={error === undefined ? undefined : true}
          className={`control control--select ${className}`.trim()}
          id={inputId}
          {...props}
        >
          {children}
        </select>
      )}
    </FieldFrame>
  );
}

interface MoneyInputProps {
  currency: string;
  error?: string | undefined;
  id?: string | undefined;
  label: string;
  locale: string;
  onChange: (value: string) => void;
  value: string;
}

export function MoneyInput({
  currency,
  error,
  id,
  label,
  locale,
  onChange,
  value,
}: MoneyInputProps) {
  const separator = decimalSeparator(locale);
  return (
    <FieldFrame
      error={error}
      hint={`Введите сумму в формате 1 250${separator}00. Значение уйдёт как точная decimal-строка.`}
      id={id}
      label={label}
    >
      {(inputId, describedBy) => (
        <div className="money-control">
          <input
            aria-describedby={describedBy}
            aria-invalid={error === undefined ? undefined : true}
            autoComplete="off"
            className="control money-control__input"
            id={inputId}
            inputMode="decimal"
            onChange={(event) => {
              onChange(event.target.value);
            }}
            placeholder={`0${separator}00`}
            spellCheck={false}
            type="text"
            value={value}
          />
          <span className="money-control__currency" aria-hidden="true">
            {currency}
          </span>
        </div>
      )}
    </FieldFrame>
  );
}

type DateControlProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type"> & {
  error?: string | undefined;
  id?: string | undefined;
  label: string;
};

export function DateControl({ error, id, label, ...props }: DateControlProps) {
  return <InputField error={error} id={id} label={label} type="date" {...props} />;
}
