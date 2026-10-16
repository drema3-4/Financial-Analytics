import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ResponsiveDataView } from "./DataView";
import { MoneyInput } from "./Fields";
import { Dialog } from "./Overlay";

describe("foundation components", () => {
  it("connects money input labels, hint, and error semantics", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <MoneyInput
        currency="RUB"
        error="Некорректная сумма"
        label="Сумма"
        locale="ru-RU"
        onChange={onChange}
        value=""
      />,
    );
    const input = screen.getByLabelText("Сумма");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/точная decimal-строка.*Некорректная сумма/u);
    await user.type(input, "10,25");
    expect(onChange).toHaveBeenLastCalledWith("5");
  });

  it("renders one data model as both desktop table and mobile list", () => {
    render(
      <ResponsiveDataView
        caption="Тестовые счета"
        columns={[{ key: "name", label: "Счёт", render: (row: { name: string }) => row.name }]}
        getKey={(row) => row.name}
        rows={[{ name: "Карта" }]}
      />,
    );
    expect(screen.getByRole("table", { name: "Тестовые счета" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Тестовые счета" })).toBeInTheDocument();
  });

  it("provides a labelled native dialog and an explicit close action", async () => {
    const close = vi.fn();
    const user = userEvent.setup();
    render(
      <Dialog onClose={close} open title="Профиль">
        Содержимое
      </Dialog>,
    );
    expect(screen.getByRole("dialog", { name: "Профиль", hidden: true })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Закрыть", hidden: true }));
    expect(close).toHaveBeenCalledOnce();
  });
});
