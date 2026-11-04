// A small static server for the end-to-end tests. It answers range requests, as the
// tiles host must, and sends the Content-Security-Policy from dist/_headers, so the
// tests see the same policy as the live site.

import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
};

export function serve(root) {
  const policy = readFileSync(join(root, "_headers"), "utf8").match(/Content-Security-Policy: (.*)/)[1];

  const server = createServer((request, response) => {
    const path = normalize(decodeURIComponent(request.url.split("?")[0]));
    const file = join(root, path === "/" ? "index.html" : path);
    if (!file.startsWith(root) || !existsSync(file) || statSync(file).isDirectory()) {
      response.writeHead(404).end();
      return;
    }
    const size = statSync(file).size;
    const headers = {
      "Content-Type": TYPES[extname(file)] ?? "application/octet-stream",
      "Content-Security-Policy": policy,
      "Accept-Ranges": "bytes",
      ETag: `"${size}"`,
    };
    const range = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range ?? "");
    if (range) {
      const start = Number(range[1]);
      const end = range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
      response.writeHead(206, { ...headers, "Content-Range": `bytes ${start}-${end}/${size}`, "Content-Length": end - start + 1 });
      createReadStream(file, { start, end }).pipe(response);
      return;
    }
    response.writeHead(200, { ...headers, "Content-Length": size });
    createReadStream(file).pipe(response);
  });

  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, origin: `http://127.0.0.1:${server.address().port}` }));
  });
}
