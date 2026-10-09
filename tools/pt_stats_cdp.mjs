#!/usr/bin/env node
/* Look at a page in a real browser and report what it actually did.
 *
 *   node tools/pt_stats_cdp.mjs --url http://127.0.0.1:8899/ --out /tmp/page.png \
 *        [--width 1440] [--height 1000] [--full] [--wait 2500]
 *        [--click '[data-deck="words"]'] [--read 'document.title']
 *
 * Speaks the DevTools protocol over the WebSocket that Node already has, so no browser
 * driver is needed. It prints every console message and page error it saw, then the
 * result of `--read`, and exits non-zero if the page threw - which is the point: a
 * screenshot that looks fine while the console is full of failures is not a pass.
 *
 * Assumes a browser is already listening on --port (Chrome with --remote-debugging-port).
 */
import { writeFileSync } from "node:fs";

const argv = process.argv.slice(2);
const arg = (name, fallback = undefined) => {
  const index = argv.indexOf(`--${name}`);
  return index === -1 ? fallback : argv[index + 1];
};
const flag = (name) => argv.includes(`--${name}`);

const url = arg("url", "http://127.0.0.1:8899/");
const port = arg("port", "9222");
const width = Number(arg("width", 1440));
const height = Number(arg("height", 1000));
const wait = Number(arg("wait", 2500));
const out = arg("out");
const click = arg("click");
const scrollTo = arg("scroll");
const read = arg("read");
const scale = Number(arg("scale", 1));

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((t) => t.type === "page");
if (!page) {
  console.error("no page target is open in the browser");
  process.exit(2);
}

const socket = new WebSocket(page.webSocketDebuggerUrl);
const pending = new Map();
const console_lines = [];
const errors = [];
let nextId = 0;

const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  pending.set(id, { resolve, reject });
  socket.send(JSON.stringify({ id, method, params }));
});

function describe(value) {
  if (value === undefined) return "undefined";
  if (value === null) return "null";
  if (typeof value === "object") {
    const text = value.description ?? value.value;
    return text === undefined ? JSON.stringify(value) : String(text);
  }
  return String(value);
}

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    return message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
  }
  if (message.method === "Runtime.consoleAPICalled") {
    const text = message.params.args.map(describe).join(" ");
    console_lines.push(`${message.params.type}: ${text}`);
    if (message.params.type === "error") errors.push(text);
  }
  if (message.method === "Runtime.exceptionThrown") {
    const d = message.params.exceptionDetails;
    errors.push(d.exception?.description ?? d.text);
  }
  if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
    errors.push(`${message.params.entry.text} ${message.params.entry.url ?? ""}`.trim());
  }
});

await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve);
  socket.addEventListener("error", () => reject(new Error("could not open the debug socket")));
});

await send("Runtime.enable");
await send("Log.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride",
           { width, height, deviceScaleFactor: scale, mobile: false });

const loaded = new Promise((resolve) => {
  const onLoad = (event) => {
    if (event.method === "Page.loadEventFired") resolve();
  };
  const listener = (event) => onLoad(JSON.parse(event.data));
  socket.addEventListener("message", listener);
  setTimeout(resolve, 15000);
});
await send("Page.navigate", { url });
await loaded;
await sleep(wait);

async function evaluate(expression) {
  const result = await send("Runtime.evaluate",
                            { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text);
  }
  return result.result.value;
}

if (click) {
  await evaluate(`document.querySelector(${JSON.stringify(click)}).click()`);
  await sleep(wait);
}

// Scrolling before the shot matters when the page is taller than the viewport and the
// charts below the fold are the ones being checked.
if (scrollTo !== undefined) {
  await evaluate(`window.scrollTo(0, ${Number(scrollTo)})`);
  await sleep(700);
}

if (out) {
  const shot = await send("Page.captureScreenshot",
                          { format: "png", captureBeyondViewport: flag("full") });
  writeFileSync(out, Buffer.from(shot.data, "base64"));
  console.log(`screenshot: ${out}`);
}

console.log(`console messages: ${console_lines.length}`);
for (const line of console_lines.slice(-25)) console.log(`  ${line}`);
if (read) {
  console.log(`read ${read}:\n${JSON.stringify(await evaluate(read), null, 1)}`);
}
if (errors.length) {
  console.log(`PAGE ERRORS: ${errors.length}`);
  for (const line of errors) console.log(`  ${line}`);
} else {
  console.log("PAGE ERRORS: none");
}
socket.close();
process.exit(errors.length ? 1 : 0);
