import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const port = Number.parseInt(process.env.PORT ?? "4173", 10);
const root = join(import.meta.dirname, "dist");
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

async function sendFile(pathname, response) {
  const requestedPath = normalize(pathname).replace(/^(\.\.(\/|\\|$))+/, "");
  let filePath = join(root, requestedPath === "/" ? "index.html" : requestedPath);

  try {
    const fileStats = await stat(filePath);
    if (!fileStats.isFile()) {
      filePath = join(root, "index.html");
    }
  } catch {
    filePath = join(root, "index.html");
  }

  response.writeHead(200, {
    "Content-Type": contentTypes[extname(filePath)] ?? "application/octet-stream",
    "X-Content-Type-Options": "nosniff",
  });
  createReadStream(filePath).pipe(response);
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");
  if (url.pathname === "/health/live") {
    response.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ status: "alive" }));
    return;
  }
  void sendFile(url.pathname, response);
});

server.listen(port, "0.0.0.0");
