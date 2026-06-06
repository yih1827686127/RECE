import { spawn } from "node:child_process";
import { createWriteStream, existsSync } from "node:fs";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RECE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BUILD_PYTHON_WINDOWS = path.resolve(RECE_ROOT, "..", "tools", "rece-build-venv", "Scripts", "python.exe");
const BUILD_PYTHON_POSIX = path.resolve(RECE_ROOT, "..", "tools", "rece-build-venv", "bin", "python");
const USER_DATA_DIR = path.join(RECE_ROOT, "tmp", "packaged_runtime_user");
const SCREENSHOT_DIR = path.join(RECE_ROOT, "examples", "hk_victoria_smoke", "screenshots", "packaged_runtime");
const REPORT_PATH = path.join(SCREENSHOT_DIR, "rece_packaged_runtime_report.json");
const SCREENSHOT_PATH = path.join(SCREENSHOT_DIR, "packaged_runtime.png");
const APP_URL = process.env.RECE_URL || "http://127.0.0.1:8792/";
const DEBUG_HOST = "127.0.0.1";
const DEBUG_PORT_START = Number(process.env.CDP_PORT || 9412);

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  "/snap/bin/chromium",
  "/usr/bin/microsoft-edge",
  "/usr/bin/microsoft-edge-stable",
].filter(Boolean);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function recePython() {
  if (process.env.RECE_PYTHON) return process.env.RECE_PYTHON;
  if (existsSync(BUILD_PYTHON_WINDOWS)) return BUILD_PYTHON_WINDOWS;
  if (existsSync(BUILD_PYTHON_POSIX)) return BUILD_PYTHON_POSIX;
  return process.platform === "win32" ? "python" : "python3";
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

async function fetchWithTimeout(url, options = {}, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
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

async function ensureReceServer() {
  const app = new URL(APP_URL);
  const healthUrl = new URL("/api/health", app).toString();
  if (await fetchOk(healthUrl)) {
    return { url: app.toString(), process: null, started: false, healthUrl };
  }
  if (process.env.RECE_URL) {
    throw new Error(`RECE_URL is not reachable: ${healthUrl}`);
  }
  await fs.rm(USER_DATA_DIR, { recursive: true, force: true });
  await fs.mkdir(USER_DATA_DIR, { recursive: true });
  const host = app.hostname || "127.0.0.1";
  const port = Number(app.port || 8792);
  const stdoutPath = path.join(RECE_ROOT, "logs", `server_${port}_packaged_stdout.log`);
  const stderrPath = path.join(RECE_ROOT, "logs", `server_${port}_packaged_stderr.log`);
  await fs.mkdir(path.dirname(stdoutPath), { recursive: true });
  const pythonPath = recePython();
  const server = spawn(pythonPath, ["-m", "rece.server", "--host", host, "--port", String(port)], {
    cwd: RECE_ROOT,
    detached: false,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
    env: {
      ...process.env,
      RECE_RUNTIME_MODE: "package",
      RECE_USER_DATA_DIR: USER_DATA_DIR,
    },
  });
  server.stdout.pipe(createWriteStream(stdoutPath, { flags: "a" }));
  server.stderr.pipe(createWriteStream(stderrPath, { flags: "a" }));
  if (!(await waitForUrlOk(healthUrl))) {
    throw new Error(`RECE server did not become reachable at ${healthUrl}`);
  }
  return { url: app.toString(), process: server, started: true, healthUrl, stdoutPath, stderrPath, pythonPath };
}

function findChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    if (candidate && existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error("Chrome or Edge executable was not found.");
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
    this.ws.addEventListener("message", async (event) => {
      const message = JSON.parse(await decodeWsData(event.data));
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject, timer } = this.pending.get(message.id);
        this.pending.delete(message.id);
        clearTimeout(timer);
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
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP command timed out: ${method}`));
      }, 60000);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.ws?.close();
  }
}

async function decodeWsData(data) {
  if (typeof data === "string") return data;
  if (data instanceof ArrayBuffer) return Buffer.from(data).toString("utf8");
  if (ArrayBuffer.isView(data)) return Buffer.from(data.buffer, data.byteOffset, data.byteLength).toString("utf8");
  if (data && typeof data.text === "function") return await data.text();
  return String(data);
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

async function waitForRuntimeMode(client, expectedMode, timeoutMs = 30000) {
  const start = Date.now();
  let lastMode = "";
  while (Date.now() - start < timeoutMs) {
    lastMode = await runtimeValue(client, "document.body?.dataset?.receRuntimeMode || ''");
    if (lastMode === expectedMode) {
      return lastMode;
    }
    await sleep(300);
  }
  throw new Error(`Timed out waiting for RECE runtime mode ${expectedMode}; last mode was ${lastMode || "empty"}.`);
}

function consoleLogs(events) {
  return events
    .filter((event) => event.method === "Runtime.consoleAPICalled" || event.method === "Runtime.exceptionThrown")
    .map((event) => {
      if (event.method === "Runtime.exceptionThrown") {
        const details = event.params.exceptionDetails || {};
        return { level: "exception", text: details.exception?.description || details.text || "Runtime exception" };
      }
      return {
        level: event.params.type,
        text: (event.params.args || []).map((arg) => arg.value ?? arg.description ?? "").join(" "),
      };
    });
}

async function main() {
  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  const serverInfo = await ensureReceServer();
  const chromePath = findChrome();
  const cdpPort = await choosePort(DEBUG_PORT_START);
  const profileDir = path.join(RECE_ROOT, "tmp", `chrome_profile_rece_packaged_${cdpPort}`);
  await fs.rm(profileDir, { recursive: true, force: true });
  await fs.mkdir(profileDir, { recursive: true });
  const chromeLogDir = path.join(RECE_ROOT, "logs");
  await fs.mkdir(chromeLogDir, { recursive: true });
  const chromeStdoutPath = path.join(chromeLogDir, `chrome_${cdpPort}_packaged_stdout.log`);
  const chromeStderrPath = path.join(chromeLogDir, `chrome_${cdpPort}_packaged_stderr.log`);
  const chromeArgs = [
    `--remote-debugging-port=${cdpPort}`,
    "--remote-allow-origins=*",
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--window-size=1400,1000",
    "about:blank",
  ];
  if (process.platform === "linux") {
    chromeArgs.splice(-1, 0, "--no-sandbox", "--disable-dev-shm-usage");
  }
  const chrome = spawn(chromePath, chromeArgs, { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  chrome.stdout.pipe(createWriteStream(chromeStdoutPath, { flags: "a" }));
  chrome.stderr.pipe(createWriteStream(chromeStderrPath, { flags: "a" }));

  let client;
  try {
    let pageTarget;
    try {
      const created = await fetchWithTimeout(`http://${DEBUG_HOST}:${cdpPort}/json/new?about:blank`, { method: "PUT" });
      if (created.ok) {
        pageTarget = await created.json();
      }
    } catch {
      // Fall back to the initial browser page below.
    }
    if (!pageTarget?.webSocketDebuggerUrl) {
      const targets = await waitForJson(`http://${DEBUG_HOST}:${cdpPort}/json`);
      pageTarget = targets.find((target) => target.type === "page");
    }
    if (!pageTarget?.webSocketDebuggerUrl) {
      throw new Error("Could not acquire a CDP page target.");
    }
    client = new CdpClient(pageTarget.webSocketDebuggerUrl);
    await client.connect();
    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("Log.enable");
    await client.send("Page.navigate", { url: serverInfo.url });
    await waitForReadyState(client);
    await waitForRuntimeMode(client, "package");

    const runtimeInfo = await fetchJson(new URL("/api/runtime", serverInfo.url).toString());
    const pageState = await runtimeValue(client, `(() => {
      const externalScripts = [...document.scripts]
        .map((script) => script.src)
        .filter(Boolean)
        .filter((src) => /^https?:\\/\\//i.test(src) && new URL(src).origin !== window.location.origin);
      const visible = (id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden';
      };
      return {
        title: document.title,
        bodyMode: document.body.dataset.receRuntimeMode || '',
        examplePanelVisible: visible('rece-example-panel'),
        workflowPanelVisible: visible('rece-workflow-panel'),
        startSimulationVisible: visible('start-simulation-btn'),
        reefControlsVisibleBefore: visible('rece-reef3d-controls'),
        externalScripts,
        configInputExists: Boolean(document.getElementById('configFile')),
        bathyInputExists: Boolean(document.getElementById('bathymetryFile')),
        solverSelectExists: Boolean(document.getElementById('rece-solver-select')),
        brandLogoSrc: document.querySelector('.rece-panel-logo')?.getAttribute('src') || '',
        brandLogoLoaded: Boolean((document.querySelector('.rece-panel-logo')?.naturalWidth || 0) > 0),
        unitLogoSrc: document.querySelector('.rece-unit-logo')?.getAttribute('src') || '',
        unitLogoLoaded: Boolean((document.querySelector('.rece-unit-logo')?.naturalWidth || 0) > 0),
        hasRightsText: Boolean(
          (document.querySelector('.rece-brand-panel')?.innerText || '').includes('HKUST-GZ / MHRF')
          && (document.querySelector('.rece-brand-panel')?.innerText || '').includes('Marine Hydrodynamic Research Facility')
          && (document.querySelector('.rece-brand-panel')?.innerText || '').includes('GPL-3.0-or-later')
          && !(document.querySelector('.rece-brand-panel')?.innerText || '').includes('RECE WebGPU')
          && !(document.querySelector('.rece-brand-panel')?.innerText || '').includes('香港科技大学（广州） /')
        ),
      };
    })()`);

    const reefPanelState = await runtimeValue(client, `(() => {
      const solver = document.getElementById('rece-solver-select');
      solver.value = 'reef3d';
      solver.dispatchEvent(new Event('change', { bubbles: true }));
      const el = document.getElementById('rece-reef3d-controls');
      const style = getComputedStyle(el);
      return { solverValue: solver.value, reefControlsVisibleAfter: style.display !== 'none' && style.visibility !== 'hidden' };
    })()`);

    const missingUploadStatus = await runtimeValue(client, `(() => {
      document.getElementById('rece-run-custom-reef3d-btn').click();
      return new Promise((resolve) => setTimeout(() => resolve(document.getElementById('rece-custom-run-status').textContent), 300));
    })()`);

    const hkWorkflowResponse = await fetch(new URL("/api/scenarios/hk_victoria_smoke/run", serverInfo.url), { method: "POST" });
    const screenshot = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await fs.writeFile(SCREENSHOT_PATH, Buffer.from(screenshot.data, "base64"));

    const logs = consoleLogs(client.events);
    const unexpectedLogs = logs.filter((entry) => /exception/i.test(entry.level) || /uncaught|unhandledrejection/i.test(entry.text));
    const report = {
      passed: Boolean(
        runtimeInfo.package_mode === true
        && pageState.bodyMode === "package"
        && pageState.examplePanelVisible === false
        && pageState.workflowPanelVisible === false
        && pageState.startSimulationVisible === true
        && pageState.configInputExists
        && pageState.bathyInputExists
        && pageState.solverSelectExists
        && /assets\/rece-panel-logo\.png$/i.test(pageState.brandLogoSrc || "")
        && pageState.brandLogoLoaded
        && /assets\/hkust-gz-logo\.png$/i.test(pageState.unitLogoSrc || "")
        && pageState.unitLogoLoaded
        && pageState.hasRightsText
        && reefPanelState.solverValue === "reef3d"
        && reefPanelState.reefControlsVisibleAfter === true
        && /Load Celeris config\.json/i.test(missingUploadStatus)
        && hkWorkflowResponse.status === 404
        && pageState.externalScripts.length === 0
        && unexpectedLogs.length === 0
      ),
      appUrl: serverInfo.url,
      serverInfo,
      runtimeInfo,
      chromePath,
      chromeArgs,
      chromeStdoutPath,
      chromeStderrPath,
      cdpPort,
      pageState,
      reefPanelState,
      missingUploadStatus,
      hkWorkflowStatus: hkWorkflowResponse.status,
      relevantLogs: logs.filter((entry) => /error|exception|warn|failed/i.test(`${entry.level} ${entry.text}`)),
      unexpectedLogs,
      screenshot: SCREENSHOT_PATH,
      generatedAt: new Date().toISOString(),
    };
    await fs.writeFile(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(JSON.stringify({ passed: report.passed, report: REPORT_PATH, screenshot: SCREENSHOT_PATH }, null, 2));
    if (!report.passed) {
      process.exitCode = 1;
    }
  } finally {
    client?.close();
    if (chrome?.pid) {
      try {
        chrome.kill();
      } catch {
        // Best effort cleanup.
      }
    }
    if (serverInfo.started && serverInfo.process?.pid) {
      try {
        serverInfo.process.kill();
      } catch {
        // Best effort cleanup.
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
