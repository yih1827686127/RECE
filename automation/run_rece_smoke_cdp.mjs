import { spawn } from "node:child_process";
import { createWriteStream, existsSync } from "node:fs";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RECE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PROFILE_DIR_BASE = path.join(RECE_ROOT, "tmp", "chrome_profile_rece_cdp");
const SCREENSHOT_DIR = path.join(RECE_ROOT, "examples", "hk_victoria_smoke", "screenshots");
const REPORT_PATH = path.join(SCREENSHOT_DIR, "rece_cdp_report.json");
const SCREENSHOT_PATH = path.join(SCREENSHOT_DIR, "rece_hk_external_frames.png");
const APP_URL = process.env.RECE_URL || "http://127.0.0.1:8787/";
const DEBUG_HOST = "127.0.0.1";
const DEBUG_PORT_START = Number(process.env.CDP_PORT || 9322);
const KEEP_BROWSER_OPEN = process.env.RECE_KEEP_BROWSER === "1";
const SHOW_BROWSER = KEEP_BROWSER_OPEN || process.env.RECE_SHOW_BROWSER === "1";

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
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, DEBUG_HOST);
  });
}

async function choosePort() {
  for (let port = DEBUG_PORT_START; port < DEBUG_PORT_START + 20; port += 1) {
    if (await isPortFree(port)) {
      return port;
    }
  }
  throw new Error("No free CDP port found.");
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
  const stdoutPath = path.join(RECE_ROOT, "logs", `server_${port}_smoke_stdout.log`);
  const stderrPath = path.join(RECE_ROOT, "logs", `server_${port}_smoke_stderr.log`);
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
    const payload = JSON.stringify({ id, method, params });
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(payload);
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
    const state = await runtimeValue(client, "document.readyState");
    if (state === "complete" || state === "interactive") {
      return;
    }
    await sleep(250);
  }
  throw new Error("Timed out waiting for DOM ready state.");
}

async function waitForExternalFrames(client) {
  const start = Date.now();
  let last;
  while (Date.now() - start < 60000) {
    last = await runtimeValue(client, `(() => {
      const canvas = document.getElementById('webgpuCanvas');
      const status = document.getElementById('status-container')?.innerText
        || document.getElementById('parameters-container')?.innerText
        || document.body.innerText;
      return {
        gpu: !!navigator.gpu,
        canvasWidth: canvas?.width || 0,
        canvasHeight: canvas?.height || 0,
        canvasRect: canvas ? (() => {
          const rect = canvas.getBoundingClientRect();
          return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
        })() : null,
        simStatusText: document.getElementById('simstatus-container')?.innerText || "",
        statusText: status.slice(0, 1000),
        hasReceButton: !!document.getElementById('rece-run-workflow-btn'),
        selectedExample: document.getElementById('run_example-select')?.value || null,
        bodyText: document.body.innerText.slice(0, 1000),
      };
    })()`);
    if (
      last.gpu
      && last.canvasWidth >= 128
      && last.canvasHeight >= 80
      && last.canvasWidth !== 300
      && /Simulated Time|Faster-than-Realtime|Fluid Solver|External/i.test(last.statusText + last.bodyText)
    ) {
      return last;
    }
    await sleep(1000);
  }
  return last;
}

async function main() {
  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  const serverInfo = await ensureReceServer();
  const port = await choosePort();
  const profileDir = process.env.RECE_CHROME_PROFILE || `${PROFILE_DIR_BASE}_${port}`;
  await fs.mkdir(profileDir, { recursive: true });
  const chromePath = findChrome();
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--enable-unsafe-webgpu",
    "--enable-webgpu-developer-features",
    "--ignore-gpu-blocklist",
    "--use-angle=d3d11",
    "--window-size=1400,1000",
    "--window-position=40,40",
    "about:blank",
  ];

  const chrome = spawn(chromePath, args, {
    detached: KEEP_BROWSER_OPEN,
    stdio: "ignore",
    windowsHide: !SHOW_BROWSER,
  });
  if (KEEP_BROWSER_OPEN) {
    chrome.unref();
  }

  const logs = [];
  let client;
  let report;
  try {
    const version = await waitForJson(`http://${DEBUG_HOST}:${port}/json/version`);
    let targets = await waitForJson(`http://${DEBUG_HOST}:${port}/json`);
    let pageTarget = targets.find((target) => target.type === "page");
    if (!pageTarget) {
      await fetch(`http://${DEBUG_HOST}:${port}/json/new?about:blank`, { method: "PUT" });
      targets = await waitForJson(`http://${DEBUG_HOST}:${port}/json`);
      pageTarget = targets.find((target) => target.type === "page");
    }
    if (!pageTarget?.webSocketDebuggerUrl) {
      throw new Error("Could not acquire a CDP page target.");
    }

    client = new CdpClient(pageTarget.webSocketDebuggerUrl);
    await client.connect();
    await client.send("Page.enable");
    await client.send("DOM.enable");
    await client.send("Runtime.enable");
    await client.send("Log.enable");
    await client.send("Page.addScriptToEvaluateOnNewDocument", {
      source: `
        window.addEventListener('error', (event) => {
          console.error('[window.error]', event.message, event.filename, event.lineno, event.colno, event.error && (event.error.stack || event.error.message || event.error));
        });
        window.addEventListener('unhandledrejection', (event) => {
          const reason = event.reason;
          console.error('[unhandledrejection]', reason && (reason.stack || reason.message || reason));
        });
      `,
    });

    client.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.method === "Runtime.consoleAPICalled") {
        logs.push({
          level: message.params.type,
          text: (message.params.args || []).map((arg) => arg.value ?? arg.description ?? "").join(" "),
        });
      }
      if (message.method === "Runtime.exceptionThrown") {
        const details = message.params.exceptionDetails || {};
        const exception = details.exception || {};
        logs.push({
          level: "exception",
          text: exception.description || exception.value || details.text || "Runtime exception",
        });
      }
      if (message.method === "Log.entryAdded") {
        logs.push({
          level: message.params.entry?.level || "log",
          text: message.params.entry?.text || "",
        });
      }
    });

    await client.send("Page.navigate", { url: serverInfo.url });
    await waitForReadyState(client);
    await sleep(5000);

    const pageBefore = await runtimeValue(client, `(() => ({
      url: location.href,
      title: document.title,
      gpu: !!navigator.gpu,
      hasReceButton: !!document.getElementById('rece-run-workflow-btn'),
      hasRunExampleButton: !!document.getElementById('run-example-simulation-btn'),
      hasReceOption: !![...document.querySelectorAll('#run_example-select option')].find((o) => o.value === '54'),
        bodyTextStart: document.body.innerText.slice(0, 500),
        scripts: [...document.scripts].map((script) => script.src || script.textContent.slice(0, 80)),
    }))()`);

    await client.send("Runtime.evaluate", {
      expression: `(() => {
        const select = document.getElementById('run_example-select');
        select.value = '54';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        document.getElementById('run-example-simulation-btn').click();
      })()`,
      awaitPromise: true,
    });

    const simState = await waitForExternalFrames(client);
    const renderWaitStart = Date.now();
    while (
      Date.now() - renderWaitStart < 30000
      && !logs.some((entry) => /Compute \/ Render loop starting/i.test(entry.text))
    ) {
      await sleep(1000);
    }
    await sleep(3000);
    await client.send("Runtime.evaluate", {
      expression: "document.getElementById('webgpuCanvas')?.scrollIntoView({ block: 'center', inline: 'center' })",
      awaitPromise: true,
    });
    await sleep(500);
    const canvasClip = await runtimeValue(client, `(() => {
      const canvas = document.getElementById('webgpuCanvas');
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      const x = Math.max(0, rect.x + window.scrollX);
      const y = Math.max(0, rect.y + window.scrollY);
      const width = Math.max(1, rect.width);
      const height = Math.max(1, rect.height);
      return { x, y, width, height, scale: 1 };
    })()`);
    const screenshot = await client.send("Page.captureScreenshot", {
      format: "png",
      clip: canvasClip || undefined,
      captureBeyondViewport: false,
    });
    await fs.writeFile(SCREENSHOT_PATH, Buffer.from(screenshot.data, "base64"));

    const externalManifestLoaded = logs.some((entry) => /Loaded REEF3D external frame manifest/i.test(entry.text));
    const externalModeActive = logs.some((entry) => /external REEF3D solver mode is active/i.test(entry.text));
    const renderLoopStarted = logs.some((entry) => /Compute \/ Render loop starting/i.test(entry.text));
    const blockingLogs = logs.filter((entry) => {
      const level = String(entry.level || "");
      const text = String(entry.text || "");
      return /exception|error/i.test(level) || /unhandledrejection|window\.error|failed|uncaught|exception/i.test(text);
    });
    const relevantLogs = logs.filter((entry) => /error|exception|warning|warn/i.test(entry.level) || /error|failed|exception|unhandledrejection/i.test(entry.text));
    report = {
      passed: Boolean(
        pageBefore.gpu
        && pageBefore.hasReceButton
        && pageBefore.hasReceOption
        && externalManifestLoaded
        && externalModeActive
        && blockingLogs.length === 0
        && simState?.canvasWidth >= 128
        && simState?.canvasHeight >= 80
        && simState?.canvasWidth !== 300
      ),
      appUrl: serverInfo.url,
      serverInfo: {
        started: serverInfo.started,
        healthUrl: serverInfo.healthUrl,
        stdoutPath: serverInfo.stdoutPath || null,
        stderrPath: serverInfo.stderrPath || null,
      },
      chromePath,
      cdpPort: port,
      browserVersion: version.Browser,
      pageBefore,
      simulationState: simState,
      canvasClip,
      externalManifestLoaded,
      externalModeActive,
      renderLoopStarted,
      relevantLogs,
      blockingLogs,
      allLogs: logs,
      screenshot: SCREENSHOT_PATH,
      generatedAt: new Date().toISOString(),
    };
    await fs.writeFile(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(JSON.stringify(report, null, 2));
  } finally {
    client?.close();
    if (!KEEP_BROWSER_OPEN && chrome?.pid) {
      try {
        chrome.kill();
      } catch {
        // Best effort; the profile is under RECE if Chrome keeps cleanup files.
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
  const report = {
    passed: false,
    error: error.message,
    generatedAt: new Date().toISOString(),
  };
  await fs.writeFile(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.error(error);
  process.exit(1);
});
