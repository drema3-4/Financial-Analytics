import type { Key, ReactNode } from "react";

interface Column<T> {
  key: string;
  label: string;
  numeric?: boolean;
  render: (row: T) => ReactNode;
}

interface ResponsiveDataViewProps<T> {
  caption: string;
  columns: Column<T>[];
  getKey: (row: T) => Key;
  rows: T[];
}

export function ResponsiveDataView<T>({
  caption,
  columns,
  getKey,
  rows,
}: ResponsiveDataViewProps<T>) {
  return (
    <>
      <div className="data-table-wrap">
        <table className="data-table">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  className={column.numeric === true ? "data-cell--numeric" : ""}
                  key={column.key}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={getKey(row)}>
                {columns.map((column) => (
                  <td
                    className={column.numeric === true ? "data-cell--numeric" : ""}
                    key={column.key}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="data-list" aria-label={caption}>
        {rows.map((row) => (
          <li className="data-list__item" key={getKey(row)}>
            {columns.map((column) => (
              <div className="data-list__field" key={column.key}>
                <span>{column.label}</span>
                <strong className={column.numeric === true ? "data-cell--numeric" : ""}>
                  {column.render(row)}
                </strong>
              </div>
            ))}
          </li>
        ))}
      </ul>
    </>
  );
}
