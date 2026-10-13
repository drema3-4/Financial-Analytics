from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from financial_analytics_api.main import create_app
from financial_analytics_infra.settings import AppEnvironment, Settings

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "docs" / "openapi.json"
CLIENT_PATH = ROOT / "packages" / "frontend" / "api" / "src" / "generated" / "client.ts"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _schema_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", maxsplit=1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(item, ensure_ascii=False) for item in schema["enum"])
    for keyword, separator in (("anyOf", " | "), ("oneOf", " | "), ("allOf", " & ")):
        if keyword in schema:
            return separator.join(f"({_schema_type(item)})" for item in schema[keyword])
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return " | ".join(_schema_type({"type": item}) for item in schema_type)
    if schema_type == "string":
        return "string"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "array":
        return f"Array<{_schema_type(schema.get('items', {}))}>"
    if schema_type == "object" or "properties" in schema:
        required = set(schema.get("required", []))
        fields = []
        for name, value in schema.get("properties", {}).items():
            optional = "" if name in required else "?"
            fields.append(f"  {_property_name(name)}{optional}: {_schema_type(value)};")
        additional = schema.get("additionalProperties")
        if additional is True:
            fields.append("  [key: string]: unknown;")
        elif isinstance(additional, dict):
            fields.append(f"  [key: string]: {_schema_type(additional)};")
        if not fields:
            return "Record<string, unknown>"
        return "{\n" + "\n".join(fields) + "\n}"
    return "unknown"


def _property_name(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value) else json.dumps(value)


def _camel(value: str) -> str:
    words = re.split(r"[^A-Za-z0-9]+", value)
    first, *rest = [word for word in words if word]
    return first.lower() + "".join(word[:1].upper() + word[1:] for word in rest)


def _response_type(operation: dict[str, Any]) -> str:
    for status_code in sorted(operation.get("responses", {})):
        if not str(status_code).startswith("2"):
            continue
        response = operation["responses"][status_code]
        content = response.get("content", {})
        for media_type in ("application/json", "text/csv", "text/plain"):
            if media_type in content:
                if media_type != "application/json":
                    return "string"
                return _schema_type(content[media_type].get("schema", {}))
        return "void"
    return "void"


def _request_body_type(operation: dict[str, Any]) -> tuple[str, bool] | None:
    request_body = operation.get("requestBody")
    if request_body is None:
        return None
    schema = request_body.get("content", {}).get("application/json", {}).get("schema", {})
    return _schema_type(schema), bool(request_body.get("required", False))


def _client_method(method: str, path: str, operation: dict[str, Any]) -> str:
    operation_id = operation["operationId"]
    parameters = operation.get("parameters", [])
    args: list[tuple[str, str, bool]] = []
    names: dict[tuple[str, str], str] = {}
    for parameter in parameters:
        name = _camel(parameter["name"])
        names[(parameter["in"], parameter["name"])] = name
        args.append(
            (
                name,
                _schema_type(parameter.get("schema", {})),
                parameter.get("required", False),
            )
        )
    body = _request_body_type(operation)
    if body is not None:
        args.append(("body", body[0], body[1]))
    required_args = any(required for _, _, required in args)
    if not args:
        signature = ""
    else:
        properties = " ".join(
            f"{name}{'' if required else '?'}: {value_type};" for name, value_type, required in args
        )
        signature = f"args: {{ {properties} }}"
        if not required_args:
            signature += " = {}"

    lines = [
        f"  async {operation_id}({signature}): Promise<{_response_type(operation)}> {{",
        f"    let path = {json.dumps(path)};",
    ]
    for parameter in parameters:
        if parameter["in"] == "path":
            arg_name = names[("path", parameter["name"])]
            lines.append(
                f"    path = path.replace({json.dumps('{' + parameter['name'] + '}')}, "
                f"encodeURIComponent(String(args.{arg_name})));"
            )
    lines.append("    const query = new URLSearchParams();")
    for parameter in parameters:
        if parameter["in"] != "query":
            continue
        arg_name = names[("query", parameter["name"])]
        raw_name = json.dumps(parameter["name"])
        lines.extend(
            [
                f"    if (args.{arg_name} !== undefined && args.{arg_name} !== null) {{",
                f"      const value = args.{arg_name};",
                "      if (Array.isArray(value)) {",
                f"        for (const item of value) query.append({raw_name}, String(item));",
                "      } else {",
                f"        query.set({raw_name}, String(value));",
                "      }",
                "    }",
            ]
        )
    lines.append("    const headers: Record<string, string> = {};")
    for parameter in parameters:
        if parameter["in"] != "header":
            continue
        arg_name = names[("header", parameter["name"])]
        raw_name = json.dumps(parameter["name"])
        lines.extend(
            [
                f"    if (args.{arg_name} !== undefined && args.{arg_name} !== null) {{",
                f"      headers[{raw_name}] = String(args.{arg_name});",
                "    }",
            ]
        )
    body_expression = "args.body" if body is not None else "undefined"
    lines.append(
        f"    return this.request<{_response_type(operation)}>("
        f"{json.dumps(method.upper())}, path, query, {body_expression}, headers);"
    )
    lines.append("  }")
    return "\n".join(lines)


def _generate_client(schema: dict[str, Any]) -> str:
    lines = [
        "// Generated by scripts/generate_api_client.py. DO NOT EDIT.",
        "/* eslint-disable */",
        "",
    ]
    schemas = schema.get("components", {}).get("schemas", {})
    for name in sorted(schemas):
        lines.append(f"export type {name} = {_schema_type(schemas[name])};")
        lines.append("")
    lines.extend(
        [
            "export class ApiError extends Error {",
            "  constructor(",
            "    public readonly status: number,",
            "    public readonly payload: ProblemDetails | unknown,",
            "  ) {",
            "    super(`API request failed with status ${status}`);",
            '    this.name = "ApiError";',
            "  }",
            "}",
            "",
            "export class FinancialAnalyticsClient {",
            '  constructor(private readonly baseUrl: string = "") {}',
            "",
        ]
    )
    for path, path_item in schema.get("paths", {}).items():
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if operation is not None:
                lines.append(_client_method(method, path, operation))
                lines.append("")
    lines.extend(
        [
            "  private async request<T>(",
            "    method: string,",
            "    path: string,",
            "    query: URLSearchParams,",
            "    body: unknown,",
            "    headers: Record<string, string>,",
            "  ): Promise<T> {",
            "    const queryString = query.toString();",
            "    const response = await fetch(",
            '      `${this.baseUrl}${path}${queryString ? `?${queryString}` : ""}`,',
            "      {",
            "        method,",
            '        credentials: "include",',
            "        headers: {",
            '          Accept: "application/json, application/problem+json, text/csv",',
            '          ...(body === undefined ? {} : { "Content-Type": "application/json" }),',
            "          ...headers,",
            "        },",
            "        ...(body === undefined ? {} : { body: JSON.stringify(body) }),",
            "      },",
            "    );",
            '    const contentType = response.headers.get("content-type") ?? "";',
            "    if (!response.ok) {",
            '      const payload = contentType.includes("json")',
            "        ? await response.json()",
            "        : await response.text();",
            "      throw new ApiError(response.status, payload);",
            "    }",
            "    if (response.status === 204) return undefined as T;",
            '    if (!contentType.includes("json")) return (await response.text()) as T;',
            "    return (await response.json()) as T;",
            "  }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def _openapi() -> dict[str, Any]:
    app = create_app(Settings(app_env=AppEnvironment.TEST, _env_file=None))
    return app.openapi()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = _openapi()
    openapi_content = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    client_content = _generate_client(schema)
    expected = ((OPENAPI_PATH, openapi_content), (CLIENT_PATH, client_content))
    if args.check:
        stale = [
            path
            for path, content in expected
            if not path.exists() or path.read_text("utf-8") != content
        ]
        if stale:
            for path in stale:
                print(f"generated artifact is stale: {path.relative_to(ROOT)}")
            return 1
        print("OpenAPI snapshot and TypeScript client are current.")
        return 0
    for path, content in expected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"generated {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
