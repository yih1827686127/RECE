import { spawn } from "node:child_process";
import { createWriteStream, existsSync } from "node:fs";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RECE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCREENSHOT_DIR = path.join(RECE_ROOT, "examples", "hk_victoria_smoke", "screenshots", "all_examples");
const REPORT_PATH = path.join(SCREENSHOT_DIR, "rece_all_examples_report.json");
const APP_URL = process.env.RECE_URL || "http://127.0.0.1:8787/";
const DEBUG_HOST = "127.0.0.1";
const DEBUG_PORT_START = Number(process.env.CDP_PORT || 9362);
const CASE_TIMEOUT_MS = Number(process.env.RECE_ALL_EXAMPLES_TIMEOUT_MS || 60000);
const CASE_SETTLE_MS = Number(process.env.RECE_ALL_EXAMPLES_SETTLE_MS || 2500);
const PAGE_BOOT_MS = Number(process.env.RECE_ALL_EXAMPLES_PAGE_BOOT_MS || 5000);
const CASE_LIMIT = Number(process.env.RECE_ALL_EXAMPLES_LIMIT || 0);

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function isPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen(port, DEBUG_HOST);
  });
}

async function choosePort(startPort) {
  for (let port = startPort; port < startPort + 30; port += 1) {
    if (await isPortFree(port)) {
      return port;
    }
  }
  throw new Error(`No free CDP port found starting at ${startPort}.`);
}

async function fetchOk(url, timeoutMs = 2500) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

async function waitForUrlOk(url, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await fetchOk(url, 3000)) {
      return true;
    }
    await sleep(500);
  }
  return false;
}

async function ensureReceServer() {
  const app = new URL(APP_URL);
  const healthUrl = new URL("/api/health", app).toString();
  if (await fetchOk(healthUrl)) {
    return { url: app.toString(), process: null, started: false, healthUrl };
  }
  if (process.env.RECE_URL) {
    throw new Error(`RECE_URL is not reachable: ${healthUrl}`);
  }
  const host = app.hostname || "127.0.0.1";
  const port = Number(app.port || 8787);
  const stdoutPath = path.join(RECE_ROOT, "logs", `server_${port}_all_examples_stdout.log`);
  const stderrPath = path.join(RECE_ROOT, "logs", `server_${port}_all_examples_stderr.log`);
  await fs.mkdir(path.dirname(stdoutPath), { recursive: true });
  const server = spawn("python", ["-m", "rece.server", "--host", host, "--port", String(port)], {
    cwd: RECE_ROOT,
    detached: false,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  server.stdout.pipe(createWriteStream(stdoutPath, { flags: "a" }));
  server.stderr.pipe(createWriteStream(stderrPath, { flags: "a" }));
  if (!(await waitForUrlOk(healthUrl))) {
    throw new Error(`RECE server did not become reachable at ${healthUrl}`);
  }
  return { url: app.toString(), process: server, started: true, healthUrl, stdoutPath, stderrPath };
}

function findChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    if (candidate && existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error("Chrome or Edge executable was not found.");
}

async function fetchJson(url, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`${url} returned ${response.status}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function waitForJson(url, timeoutMs = 30000) {
  const start = Date.now();
  let lastError;
  while (Date.now() - start < timeoutMs) {
    try {
      return await fetchJson(url, 3000);
    } catch (error) {
      lastError = error;
      await sleep(500);
    }
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("WebSocket connect timeout")), 10000);
      this.ws.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.ws.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("WebSocket error"));
      }, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) {
          reject(new Error(`${message.error.message}: ${message.error.data || ""}`));
        } else {
          resolve(message.result || {});
        }
        return;
      }
      if (message.method) {
        this.events.push(message);
      }
    });
  }

  send(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.ws?.close();
  }
}

async function runtimeValue(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(`Runtime exception: ${result.exceptionDetails.text}`);
  }
  return result.result?.value;
}

async function waitForReadyState(client) {
  const start = Date.now();
  while (Date.now() - start < 30000) {
    const ready = await runtimeValue(client, "document.readyState");
    if (ready === "complete" || ready === "interactive") {
      return;
    }
    await sleep(300);
  }
  throw new Error("Page did not reach ready state.");
}

function pageLogsFromEvents(events) {
  return events
    .filter((event) => event.method === "Runtime.consoleAPICalled" || event.method === "Runtime.exceptionThrown")
    .map((event) => {
      if (event.method === "Runtime.exceptionThrown") {
        const details = event.params?.exceptionDetails || {};
        const frames = details.stackTrace?.callFrames || [];
        return {
          level: "exception",
          text: details.exception?.description || details.text || "Runtime exception",
          stack: frames
            .map((frame) => `${frame.functionName || "(anonymous)"} ${frame.url}:${frame.lineNumber + 1}:${frame.columnNumber + 1}`)
            .join("\n"),
        };
      }
      return {
        level: event.params?.type || "log",
        text: (event.params?.args || [])
          .map((arg) => arg.value ?? arg.description ?? arg.unserializableValue ?? "")
          .join(" "),
      };
    });
}

function unexpectedLog(entry) {
  const level = String(entry.level || "");
  const text = String(entry.text || "");
  if (/powerPreference option is currently ignored/i.test(text)) {
    return false;
  }
  if (/Unable to load Google Maps overlay; continuing without it/i.test(text)) {
    return false;
  }
  if (/favicon\.ico|net::ERR_ABORTED/i.test(text)) {
    return false;
  }
  return /error|exception/i.test(level) || /failed|uncaught|unhandledrejection|window\.error/i.test(text);
}

async function pageState(client) {
  return runtimeValue(client, `(() => {
    const canvas = document.getElementById('webgpuCanvas');
    const statusText = document.getElementById('simstatus-container')?.innerText || "";
    return {
      title: document.title,
      url: location.href,
      gpu: !!navigator.gpu,
      canvasWidth: canvas?.width || 0,
      canvasHeight: canvas?.height || 0,
      canvasClientWidth: canvas?.clientWidth || 0,
      canvasClientHeight: canvas?.clientHeight || 0,
      statusText,
      bodyText: document.body.innerText.slice(0, 1200),
      selectedExample: document.getElementById('run_example-select')?.value || null,
    };
  })()`);
}

async function waitForScenarioState(client, timeoutMs) {
  const start = Date.now();
  let state = null;
  while (Date.now() - start < timeoutMs) {
    state = await pageState(client);
    if (
      /^(RECE WebGPU|Celeris-WebGPU)$/i.test(state?.title || "")
      && state?.gpu
      && state?.canvasWidth >= 64
      && state?.canvasHeight >= 64
      && state?.canvasClientWidth > 0
      && /Simulated Time|Faster-than-Realtime|Simulation/i.test(state?.statusText || "")
    ) {
      return state;
    }
    await sleep(750);
  }
  return state;
}

async function captureFailure(client, option) {
  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  const safe = `${String(option.value).padStart(2, "0")}_${option.label.replace(/[^a-z0-9]+/gi, "_").slice(0, 42) || "example"}.png`;
  const screenshotPath = path.join(SCREENSHOT_DIR, safe);
  const screenshot = await client.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await fs.writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return screenshotPath;
}

async function runExample(client, option) {
  const beforeEventCount = client.events.length;
  const startedAt = new Date().toISOString();
  await runtimeValue(client, `(() => {
    const select = document.getElementById('run_example-select');
    const button = document.getElementById('run-example-simulation-btn');
    if (!select || !button) throw new Error('Missing run example controls');
    select.value = ${JSON.stringify(option.value)};
    select.dispatchEvent(new Event('change', { bubbles: true }));
    button.click();
    return select.value;
  })()`);
  await sleep(CASE_SETTLE_MS);
  const state = await waitForScenarioState(client, CASE_TIMEOUT_MS);
  const logs = pageLogsFromEvents(client.events.slice(beforeEventCount));
  const blockingLogs = logs.filter(unexpectedLog);
  const passed = Boolean(
    state?.gpu
    && state?.canvasWidth >= 64
    && state?.canvasHeight >= 64
    && /Simulated Time|Faster-than-Realtime|Simulation/i.test(state?.statusText || "")
    && blockingLogs.length === 0
  );
  const result = {
    value: option.value,
    label: option.label,
    startedAt,
    passed,
    state,
    blockingLogs,
    logSample: logs.slice(-12),
  };
  if (!passed) {
    result.screenshot = await captureFailure(client, option);
  }
  return result;
}

async function main() {
  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  const serverInfo = await ensureReceServer();
  const chromePath = findChrome();
  const cdpPort = await choosePort(DEBUG_PORT_START);
  const profileDir = path.join(RECE_ROOT, "tmp", `chrome_profile_rece_all_examples_${cdpPort}`);
  await fs.rm(profileDir, { recursive: true, force: true });
  await fs.mkdir(profileDir, { recursive: true });
  const chrome = spawn(chromePath, [
    `--remote-debugging-port=${cdpPort}`,
    `--user-data-dir=${profileDir}`,
    "--headless=new",
    "--enable-unsafe-webgpu",
    "--enable-features=Vulkan,UseSkiaRenderer",
    "--disable-gpu-sandbox",
    "--allow-file-access-from-files",
    "--no-first-run",
    "--no-default-browser-check",
    serverInfo.url,
  ], {
    stdio: "ignore",
    windowsHide: true,
  });

  let client;
  try {
    const version = await waitForJson(`http://${DEBUG_HOST}:${cdpPort}/json/version`, 45000);
    const pages = await waitForJson(`http://${DEBUG_HOST}:${cdpPort}/json/list`, 45000);
    const page = pages.find((entry) => entry.type === "page") || pages[0];
    if (!page?.webSocketDebuggerUrl) {
      throw new Error("No CDP page target was available.");
    }
    client = new CdpClient(page.webSocketDebuggerUrl);
    await client.connect();
    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("Log.enable");
    await client.send("Page.navigate", { url: serverInfo.url });
    await waitForReadyState(client);
    const options = await runtimeValue(client, `(() => Array.from(document.querySelectorAll('#run_example-select option')).map((option) => ({
      value: option.value,
      label: option.textContent.trim()
    })))()`);
    const selectedOptions = CASE_LIMIT > 0 ? options.slice(0, CASE_LIMIT) : options;
    const results = [];
    for (const option of selectedOptions) {
      await client.send("Page.navigate", { url: serverInfo.url });
      await waitForReadyState(client);
      await sleep(PAGE_BOOT_MS);
      client.events = [];
      results.push(await runExample(client, option));
    }
    const report = {
      passed: results.every((result) => result.passed),
      appUrl: serverInfo.url,
      serverInfo,
      chromePath,
      browserVersion: version.Browser,
      cdpPort,
      checked: results.length,
      totalOptions: options.length,
      caseTimeoutMs: CASE_TIMEOUT_MS,
      results,
      generatedAt: new Date().toISOString(),
    };
    await fs.writeFile(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(JSON.stringify({ passed: report.passed, checked: report.checked, report: REPORT_PATH }, null, 2));
    if (!report.passed) {
      process.exitCode = 1;
    }
  } finally {
    client?.close();
    if (!process.env.RECE_KEEP_BROWSER && chrome.pid) {
      try {
        chrome.kill();
      } catch {
        // Best effort cleanup for Chrome.
      }
    }
    if (serverInfo.started && serverInfo.process?.pid) {
      try {
        serverInfo.process.kill();
      } catch {
        // Best effort cleanup for the temporary RECE server.
      }
    }
  }
}

main().catch(async (error) => {
  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  await fs.writeFile(REPORT_PATH, `${JSON.stringify({
    passed: false,
    error: error.message,
    generatedAt: new Date().toISOString(),
  }, null, 2)}\n`, "utf8");
  console.error(error);
  process.exit(1);
});
