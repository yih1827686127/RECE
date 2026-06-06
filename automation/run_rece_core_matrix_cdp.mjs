import { spawn } from "node:child_process";
import { createWriteStream, existsSync } from "node:fs";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RECE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BUILD_PYTHON_WINDOWS = path.resolve(RECE_ROOT, "..", "tools", "rece-build-venv", "Scripts", "python.exe");
const BUILD_PYTHON_POSIX = path.resolve(RECE_ROOT, "..", "tools", "rece-build-venv", "bin", "python");
const PROFILE_DIR_BASE = path.join(RECE_ROOT, "tmp", "chrome_profile_rece_core_cdp");
const SCREENSHOT_DIR = path.join(RECE_ROOT, "examples", "hk_victoria_smoke", "screenshots", "core_matrix");
const DOWNLOAD_DIR = path.join(RECE_ROOT, "examples", "hk_victoria_smoke", "browser_downloads");
const REPORT_PATH = path.join(SCREENSHOT_DIR, "rece_core_matrix_report.json");
const APP_URL = process.env.RECE_URL || "http://127.0.0.1:8787/";
const DEBUG_HOST = "127.0.0.1";
const DEBUG_PORT_START = Number(process.env.CDP_PORT || 9342);
const CASE_WAIT_MS = Number(process.env.RECE_CASE_WAIT_MS || 1200);
const WINDOW_SIZE = process.env.RECE_CDP_WINDOW_SIZE || "1400,1000";

const PHYSICS_CONTROL_IDS = [
  "nlsw-select",
  "Theta-input",
  "theta-button",
  "courant-input",
  "courant-button",
  "isManning-select",
  "useBreakingModel-select",
  "useSedTransModel-select",
  "changeSeaLevel-input",
  "changeSeaLevel-button",
  "disturbanceType-select",
  "disturbanceXpos-input",
  "disturbanceXpos-button",
  "disturbanceYpos-input",
  "disturbanceYpos-button",
  "disturbanceCrestamp-input",
  "disturbanceCrestamp-button",
  "disturbanceDir-input",
  "disturbanceDir-button",
  "disturbanceWidth-input",
  "disturbanceWidth-button",
  "disturbanceLength-input",
  "disturbanceLength-button",
  "disturbanceRake-input",
  "disturbanceRake-button",
  "disturbanceDip-input",
  "disturbanceDip-button",
  "disturbance-button",
];

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
  const stdoutPath = path.join(RECE_ROOT, "logs", `server_${port}_core_stdout.log`);
  const stderrPath = path.join(RECE_ROOT, "logs", `server_${port}_core_stderr.log`);
  await fs.mkdir(path.dirname(stdoutPath), { recursive: true });
  const pythonPath = recePython();
  const server = spawn(pythonPath, ["-m", "rece.server", "--host", host, "--port", String(port)], {
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
      }, 15000);
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

async function setSelect(client, id, value) {
  return runtimeValue(client, `(() => {
    const el = document.getElementById(${JSON.stringify(id)});
    if (!el) throw new Error('Missing select ' + ${JSON.stringify(id)});
    if (el.disabled) throw new Error('Select is disabled: ' + ${JSON.stringify(id)});
    el.value = String(${JSON.stringify(value)});
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return el.value;
  })()`);
}

async function setInputAndClick(client, inputId, buttonId, value) {
  return runtimeValue(client, `(() => {
    const input = document.getElementById(${JSON.stringify(inputId)});
    const button = document.getElementById(${JSON.stringify(buttonId)});
    if (!input || !button) throw new Error('Missing input/button ' + ${JSON.stringify(inputId)});
    if (input.disabled || button.disabled) throw new Error('Input/button is disabled: ' + ${JSON.stringify(inputId)});
    input.value = String(${JSON.stringify(value)});
    button.click();
    return input.value;
  })()`);
}

async function clickDomId(client, id) {
  return runtimeValue(client, `(() => {
    const el = document.getElementById(${JSON.stringify(id)});
    if (!el) throw new Error('Missing element ' + ${JSON.stringify(id)});
    if (el.disabled) throw new Error('Element is disabled: ' + ${JSON.stringify(id)});
    el.click();
    return true;
  })()`);
}

async function dragCanvas(client) {
  const box = await runtimeValue(client, `(() => {
    const canvas = document.getElementById('webgpuCanvas');
    if (!canvas) return null;
    canvas.scrollIntoView({ block: 'center', inline: 'center' });
    const rect = canvas.getBoundingClientRect();
    return { x: rect.left, y: rect.top, width: rect.width, height: rect.height };
  })()`);
  if (!box) {
    throw new Error("Canvas not found for drag interaction");
  }
  const startX = Math.round(box.x + box.width * 0.55);
  const startY = Math.round(box.y + box.height * 0.45);
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: startX, y: startY, button: "left", clickCount: 1 });
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: startX + 80, y: startY + 30, button: "left" });
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: startX + 80, y: startY + 30, button: "left", clickCount: 1 });
}

async function getPageState(client) {
  return runtimeValue(client, `(() => {
    const canvas = document.getElementById('webgpuCanvas');
    const text = document.getElementById('simstatus-container')?.innerText || "";
    const control = (id) => {
      const el = document.getElementById(id);
      return el ? { value: el.value ?? null, disabled: !!el.disabled } : null;
    };
    const isLockedControl = (el) => Boolean(
      el?.disabled
      || el?.getAttribute('aria-disabled') === 'true'
      || el?.dataset?.receLocked === 'reef3d'
      || el?.classList?.contains('rece-control-locked')
    );
    const disabledControls = {};
    for (const id of ${JSON.stringify(PHYSICS_CONTROL_IDS)}) {
      const el = document.getElementById(id);
      disabledControls[id] = el ? isLockedControl(el) : null;
    }
    return {
      url: location.href,
      title: document.title,
      gpu: !!navigator.gpu,
      canvasWidth: canvas?.width || 0,
      canvasHeight: canvas?.height || 0,
      canvasClientWidth: canvas?.clientWidth || 0,
      canvasClientHeight: canvas?.clientHeight || 0,
      statusText: text,
      bodyText: document.body.innerText.slice(0, 800),
      controls: {
        runExample: control('run_example-select'),
        overlay: control('GoogleMapOverlay-select'),
        surface: control('surfaceToPlot-select'),
        colorMap: control('colorMap_choice-select'),
        arrows: control('ShowArrows-select'),
        view: control('viewType-select'),
        pause: control('simPause-select'),
        renderStep: control('render_step-input'),
        timeSeries: control('NumberOfTimeSeries-select'),
        logos: control('ShowLogos-select'),
      },
      disabledControls,
    };
  })()`);
}

async function getLayoutState(client) {
  return runtimeValue(client, `(() => {
    const rectObject = (rect) => ({
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height,
    });
    const main = document.getElementById('main-container');
    const horizontal = document.getElementById('horizontalbar');
    const vertical = document.getElementById('verticalbar');
    const consolebar = document.getElementById('consolebar');
    const directHeaders = [...vertical.querySelectorAll(':scope > .window-header')];
    const panelForHeader = (key, header) => {
      const span = header?.querySelector('span');
      const content = key === 'console' ? consolebar?.querySelector('#log-container') : header?.nextElementSibling;
      const style = span ? getComputedStyle(span) : null;
      return {
        key,
        title: span?.innerText?.trim().replace(/\\s+/g, ' ') || '',
        headerRect: header ? rectObject(header.getBoundingClientRect()) : null,
        contentRect: content ? rectObject(content.getBoundingClientRect()) : null,
        fontSize: style ? Number.parseFloat(style.fontSize) : null,
        display: content ? getComputedStyle(content).display : '',
      };
    };
    const panels = [
      panelForHeader('simulation', directHeaders[0]),
      panelForHeader('timeSeries', directHeaders[1]),
      panelForHeader('parameters', directHeaders[2]),
      panelForHeader('console', consolebar?.querySelector('.window-header')),
    ];
    const orderKeys = [];
    for (const child of [...vertical.children]) {
      if (child.classList?.contains('window-header')) {
        const next = child.nextElementSibling;
        if (next?.querySelector('#webgpuCanvas')) orderKeys.push('simulation');
        else if (next?.querySelector('#timeseriesChart')) orderKeys.push('timeSeries');
        else if (next?.id === 'constants-container') orderKeys.push('parameters');
      } else if (child.id === 'consolebar') {
        orderKeys.push('console');
      }
    }
    const gridColumns = getComputedStyle(main).gridTemplateColumns
      .split(' ')
      .map((value) => value.trim())
      .filter(Boolean);
    return {
      viewportWidth: window.innerWidth,
      mainGridColumnCount: gridColumns.length,
      mainRect: rectObject(main.getBoundingClientRect()),
      horizontalRect: rectObject(horizontal.getBoundingClientRect()),
      verticalRect: rectObject(vertical.getBoundingClientRect()),
      consoleRect: rectObject(consolebar.getBoundingClientRect()),
      consoleParentId: consolebar?.parentElement?.id || '',
      orderKeys,
      panels,
    };
  })()`);
}

function evaluateLayoutState(layout) {
  const issues = [];
  const expectedOrder = ["simulation", "timeSeries", "parameters", "console"];
  if (layout.consoleParentId !== "verticalbar") {
    issues.push(`console parent is ${layout.consoleParentId || "missing"}`);
  }
  if (JSON.stringify(layout.orderKeys) !== JSON.stringify(expectedOrder)) {
    issues.push(`panel order is ${layout.orderKeys.join(",")}`);
  }
  const expectedColumns = layout.viewportWidth <= 840 ? 1 : 2;
  if (layout.mainGridColumnCount !== expectedColumns) {
    issues.push(`main grid has ${layout.mainGridColumnCount} columns, expected ${expectedColumns}`);
  }
  if (layout.viewportWidth > 840 && layout.consoleRect.right > layout.verticalRect.right + 2) {
    issues.push("console extends outside the simulation column");
  }
  if (layout.viewportWidth > 840 && layout.verticalRect.width < layout.horizontalRect.width * 1.7) {
    issues.push(`simulation column is not using released width (${layout.verticalRect.width} vs ${layout.horizontalRect.width})`);
  }

  const headerWidths = layout.panels.map((panel) => panel.headerRect?.width || 0);
  const nonzeroWidths = headerWidths.filter((width) => width > 0);
  const widthSpread = Math.max(...nonzeroWidths) - Math.min(...nonzeroWidths);
  if (nonzeroWidths.length !== 4 || widthSpread > 3) {
    issues.push(`panel header widths differ: ${headerWidths.join(", ")}`);
  }

  const fontSizes = layout.panels.map((panel) => panel.fontSize || 0);
  const fontSpread = Math.max(...fontSizes) - Math.min(...fontSizes);
  if (fontSizes.some((size) => size < 14 || size > 15.5) || fontSpread > 0.5) {
    issues.push(`panel title font sizes are not compact and equal: ${fontSizes.join(", ")}`);
  }

  const headerHeights = layout.panels.map((panel) => panel.headerRect?.height || 0);
  const heightSpread = Math.max(...headerHeights) - Math.min(...headerHeights);
  if (headerHeights.some((height) => height < 28 || height > 42) || heightSpread > 3) {
    issues.push(`panel header heights are not compact and equal: ${headerHeights.join(", ")}`);
  }

  return { passed: issues.length === 0, issues, layout };
}

async function checkLayout(client) {
  return evaluateLayoutState(await getLayoutState(client));
}

async function checkTooltipBounds(client) {
  const points = await runtimeValue(client, `(() => {
    const canvas = document.getElementById('webgpuCanvas');
    canvas.scrollIntoView({ block: 'center', inline: 'center' });
    const rect = canvas.getBoundingClientRect();
    const y = Math.round(rect.top + rect.height * 0.48);
    return [
      { name: 'left', x: Math.round(rect.left + 3), y },
      { name: 'center', x: Math.round(rect.left + rect.width * 0.5), y },
      { name: 'right', x: Math.round(rect.right - 3), y },
    ];
  })()`);
  await sleep(300);
  const checks = [];
  for (const point of points) {
    await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y });
    await sleep(220);
    checks.push(await runtimeValue(client, `(() => {
      const canvas = document.getElementById('webgpuCanvas');
      const tooltip = document.getElementById('tooltip');
      const host = canvas.closest('.window-content');
      const rectObject = (rect) => ({
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      });
      const tooltipRect = tooltip.getBoundingClientRect();
      const hostRect = host.getBoundingClientRect();
      const style = getComputedStyle(tooltip);
      return {
        name: ${JSON.stringify(point.name)},
        display: style.display,
        tooltipRect: rectObject(tooltipRect),
        hostRect: rectObject(hostRect),
        inside: style.display !== 'none'
          && tooltipRect.width > 0
          && tooltipRect.height > 0
          && tooltipRect.left >= hostRect.left - 1
          && tooltipRect.right <= hostRect.right + 1
          && tooltipRect.top >= hostRect.top - 1
          && tooltipRect.bottom <= hostRect.bottom + 1,
      };
    })()`));
  }
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 2, y: 2 });
  const failed = checks.filter((check) => !check.inside);
  return { passed: failed.length === 0, checks, failed };
}

function statePasses(state) {
  return Boolean(
    /^(RECE WebGPU|Celeris-WebGPU)$/i.test(state?.title || "")
    && state?.gpu
    && state?.canvasWidth >= 128
    && state?.canvasHeight >= 80
    && /Simulated Time|Faster-than-Realtime|NLSW Simulation/i.test(state?.statusText || "")
  );
}

async function waitForExternalFrames(client, logs, timeoutMs = 90000) {
  const start = Date.now();
  let state = null;
  while (Date.now() - start < timeoutMs) {
    state = await getPageState(client);
    const externalReady = logs.some((entry) => /Loaded REEF3D external frame manifest/i.test(entry.text))
      && logs.some((entry) => /external REEF3D solver mode is active/i.test(entry.text));
    if (statePasses(state) && externalReady) {
      return state;
    }
    await sleep(1000);
  }
  return state;
}

async function captureCase(client, index, slug) {
  await client.send("Runtime.evaluate", {
    expression: "document.getElementById('webgpuCanvas')?.scrollIntoView({ block: 'center', inline: 'center' })",
    awaitPromise: true,
  });
  await sleep(300);
  const name = `${String(index).padStart(2, "0")}_${slug}.png`;
  const screenshotPath = path.join(SCREENSHOT_DIR, name);
  const screenshot = await client.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await fs.writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  const stat = await fs.stat(screenshotPath);
  return { screenshotPath, screenshotBytes: stat.size };
}

function keepLog(entry) {
  const level = String(entry.level || "");
  const text = String(entry.text || "");
  return /warn|warning|error|exception/i.test(level) || /failed|uncaught|unhandledrejection|window\.error/i.test(text);
}

function unexpectedLog(entry) {
  const level = String(entry.level || "");
  const text = String(entry.text || "");
  if (/powerPreference option is currently ignored/i.test(text)) {
    return false;
  }
  return /error|exception/i.test(level) || /failed|uncaught|unhandledrejection|window\.error/i.test(text);
}

async function runScenario(client, logs, scenario, index) {
  const beforeLogCount = logs.length;
  const result = {
    index,
    slug: scenario.slug,
    label: scenario.label,
    startedAt: new Date().toISOString(),
  };
  try {
    await scenario.action?.();
    await sleep(scenario.waitMs ?? CASE_WAIT_MS);
    const state = await getPageState(client);
    const screenshot = await captureCase(client, index, scenario.slug);
    const relevantLogs = logs.slice(beforeLogCount).filter(keepLog);
    result.state = state;
    result.screenshot = screenshot.screenshotPath;
    result.screenshotBytes = screenshot.screenshotBytes;
    result.relevantLogs = relevantLogs;
    result.unexpectedErrors = relevantLogs.filter(unexpectedLog);
    result.passed = statePasses(state) && screenshot.screenshotBytes > 0 && result.unexpectedErrors.length === 0;
    if (scenario.assert) {
      const assertion = scenario.assert(state);
      result.assertion = assertion;
      result.passed = result.passed && assertion.passed;
    }
  } catch (error) {
    result.error = error.message;
    result.passed = false;
  }
  result.finishedAt = new Date().toISOString();
  console.log(`${result.passed ? "PASS" : "FAIL"} ${String(index).padStart(2, "0")} ${scenario.slug}`);
  return result;
}

async function listDownloads() {
  try {
    const entries = await fs.readdir(DOWNLOAD_DIR, { withFileTypes: true });
    const files = [];
    for (const entry of entries) {
      if (entry.isFile()) {
        const filePath = path.join(DOWNLOAD_DIR, entry.name);
        const stat = await fs.stat(filePath);
        files.push({ name: entry.name, path: filePath, bytes: stat.size, mtimeMs: stat.mtimeMs });
      }
    }
    return files.sort((a, b) => a.name.localeCompare(b.name));
  } catch {
    return [];
  }
}

async function waitForNewDownload(before, predicate, timeoutMs = 30000) {
  const beforeByName = new Map(before.map((file) => [file.name, file]));
  const stableTemporary = new Map();
  const matchFile = (file) => {
    const temporary = file.name.endsWith(".crdownload");
    const visibleName = temporary ? file.name.replace(/\.crdownload$/i, "") : file.name;
    const old = beforeByName.get(file.name) || beforeByName.get(visibleName);
    if (old && old.mtimeMs >= file.mtimeMs && old.bytes === file.bytes) {
      return { matched: false, temporary, comparable: null };
    }
    const comparable = { ...file, name: visibleName, temporary };
    return { matched: Boolean(predicate(comparable) && file.bytes > 0), temporary, comparable };
  };
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const current = await listDownloads();
    for (const file of current) {
      const { matched, temporary, comparable } = matchFile(file);
      if (!matched) {
        continue;
      }
      if (!temporary) {
        return file;
      }
      const seen = stableTemporary.get(file.name);
      const now = Date.now();
      if (seen && seen.bytes === file.bytes && now - seen.firstSeenMs >= 1500) {
        return comparable;
      }
      stableTemporary.set(file.name, { bytes: file.bytes, firstSeenMs: now });
    }
    await sleep(500);
  }
  for (const file of await listDownloads()) {
    const { matched, temporary, comparable } = matchFile(file);
    if (matched && !temporary) {
      return file;
    }
    if (matched && comparable) {
      return comparable;
    }
  }
  return null;
}

async function main() {
  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  await fs.rm(DOWNLOAD_DIR, { recursive: true, force: true });
  await fs.mkdir(DOWNLOAD_DIR, { recursive: true });
  const serverInfo = await ensureReceServer();
  const cdpPort = await choosePort(DEBUG_PORT_START);
  const profileDir = `${PROFILE_DIR_BASE}_${cdpPort}`;
  await fs.mkdir(profileDir, { recursive: true });
  const chromePath = findChrome();
  const chromeArgs = [
    `--remote-debugging-port=${cdpPort}`,
    "--remote-allow-origins=*",
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-popup-blocking",
    "--safebrowsing-disable-download-protection",
    "--enable-unsafe-webgpu",
    "--enable-webgpu-developer-features",
    "--ignore-gpu-blocklist",
    "--use-angle=d3d11",
    `--window-size=${WINDOW_SIZE}`,
    "--window-position=40,40",
    "about:blank",
  ];
  const chrome = spawn(chromePath, chromeArgs, {
    detached: false,
    stdio: "ignore",
    windowsHide: true,
  });

  const logs = [];
  let client;
  try {
    const version = await waitForJson(`http://${DEBUG_HOST}:${cdpPort}/json/version`);
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
    await client.send("DOM.enable");
    await client.send("Runtime.enable");
    await client.send("Log.enable");
    await client.send("Browser.setDownloadBehavior", {
      behavior: "allow",
      downloadPath: DOWNLOAD_DIR,
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
        logs.push({
          level: "exception",
          text: message.params.exceptionDetails?.exception?.description || message.params.exceptionDetails?.text || "Runtime exception",
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
    await sleep(2000);
    const pageBefore = await getPageState(client);
    await runtimeValue(client, `(() => {
      const select = document.getElementById('run_example-select');
      if (!select) throw new Error('Missing run example selector');
      select.value = '54';
      select.dispatchEvent(new Event('change', { bubbles: true }));
      document.getElementById('run-example-simulation-btn').click();
      return true;
    })()`);
    const initialState = await waitForExternalFrames(client, logs);
    if (!statePasses(initialState)) {
      throw new Error(`RECE external frame simulation did not start: ${JSON.stringify(initialState)}`);
    }
    const layoutCheck = await checkLayout(client);
    console.log(`${layoutCheck.passed ? "PASS" : "FAIL"} layout_geometry`);
    const tooltipCheck = await checkTooltipBounds(client);
    console.log(`${tooltipCheck.passed ? "PASS" : "FAIL"} tooltip_bounds`);

    let index = 1;
    let pausedText = "";
    const disabledAssert = (state) => {
      const missingOrEnabled = Object.entries(state.disabledControls)
        .filter(([, disabled]) => disabled !== true)
        .map(([id]) => id);
      return {
        passed: missingOrEnabled.length === 0,
        missingOrEnabled,
      };
    };

    const scenarios = [
      {
        slug: "base_external_frames",
        label: "RECE external frames baseline",
        assert: (state) => ({
          passed: state.controls.runExample?.value === "54" && state.controls.logos?.value === "1",
          runExample: state.controls.runExample,
          logos: state.controls.logos,
        }),
      },
      {
        slug: "physics_controls_disabled",
        label: "Internal Celeris physics controls disabled",
        assert: disabledAssert,
      },
      { slug: "overlay_off", label: "Overlay off", action: async () => setSelect(client, "GoogleMapOverlay-select", 0) },
      { slug: "overlay_local", label: "Local RECE overlay", action: async () => setSelect(client, "GoogleMapOverlay-select", 2) },
      { slug: "surface_eta_ocean", label: "Free surface plot", action: async () => setSelect(client, "surfaceToPlot-select", 0) },
      { slug: "surface_bathy", label: "Bathymetry/topography plot", action: async () => setSelect(client, "surfaceToPlot-select", 6) },
      {
        slug: "surface_speed_turbo",
        label: "Speed plot with Turbo colormap",
        action: async () => {
          await setSelect(client, "surfaceToPlot-select", 1);
          await setSelect(client, "colorMap_choice-select", 2);
        },
      },
      { slug: "arrows_off", label: "Velocity arrows off", action: async () => setSelect(client, "ShowArrows-select", 0) },
      {
        slug: "arrows_on_scaled",
        label: "Velocity arrows on with scale/density",
        action: async () => {
          await setSelect(client, "ShowArrows-select", 1);
          await setInputAndClick(client, "arrow_scale-input", "arrow_scale-button", 2);
          await setInputAndClick(client, "arrow_density-input", "arrow_density-button", 2);
        },
      },
      { slug: "view_design_2d", label: "2D Design view", action: async () => setSelect(client, "viewType-select", 1) },
      {
        slug: "view_explorer_3d",
        label: "3D Explorer view with drag",
        waitMs: 1800,
        action: async () => {
          await setSelect(client, "viewType-select", 2);
          await sleep(600);
          await dragCanvas(client);
        },
      },
      {
        slug: "pause",
        label: "Pause external frame playback",
        waitMs: 1800,
        action: async () => setSelect(client, "simPause-select", 1),
        assert: (state) => {
          pausedText = state.statusText;
          return { passed: state.controls.pause?.value === "1", statusText: state.statusText };
        },
      },
      {
        slug: "resume",
        label: "Resume external frame playback",
        waitMs: 1800,
        action: async () => setSelect(client, "simPause-select", -1),
        assert: (state) => ({
          passed: state.controls.pause?.value === "-1" && state.statusText !== pausedText,
          pausedText,
          statusText: state.statusText,
        }),
      },
      {
        slug: "render_step_two",
        label: "Render frame interval remains usable",
        action: async () => setInputAndClick(client, "render_step-input", "render_step-button", 2),
        assert: (state) => ({ passed: String(state.controls.renderStep?.value) === "2", renderStep: state.controls.renderStep }),
      },
      {
        slug: "time_series_one_point",
        label: "One time-series point",
        waitMs: 1800,
        action: async () => {
          await setSelect(client, "NumberOfTimeSeries-select", 1);
          await setInputAndClick(client, "changeXTimeSeries-input", "changeXTimeSeries-button", 3000);
          await setInputAndClick(client, "changeYTimeSeries-input", "changeYTimeSeries-button", 2000);
        },
        assert: (state) => ({ passed: state.controls.timeSeries?.value === "1", timeSeries: state.controls.timeSeries }),
      },
    ];

    const results = [];
    for (const scenario of scenarios) {
      results.push(await runScenario(client, logs, scenario, index));
      index += 1;
    }

    const downloads = [
      {
        slug: "download_current_jpg",
        label: "Download current JPG",
        action: async () => clickDomId(client, "downloadJPG-button"),
        predicate: (file) => /\.jpg$/i.test(file.name),
      },
      {
        slug: "download_config_json",
        label: "Download config JSON",
        action: async () => clickDomId(client, "download-button"),
        predicate: (file) => /config.*\.json$/i.test(file.name),
      },
      {
        slug: "download_single_surface_bin",
        label: "Download single surface binary",
        action: async () => {
          await setSelect(client, "which_surface_to_write-select", 0);
          await clickDomId(client, "downloadSingleSurface-button");
        },
        predicate: (file) => /\.bin$/i.test(file.name),
      },
    ];

    const downloadResults = [];
    for (const item of downloads) {
      const before = await listDownloads();
      const result = {
        index,
        slug: item.slug,
        label: item.label,
        startedAt: new Date().toISOString(),
      };
      try {
        await item.action();
        const file = await waitForNewDownload(before, item.predicate);
        await sleep(700);
        const state = await getPageState(client);
        const screenshot = await captureCase(client, index, item.slug);
        result.state = state;
        result.download = file;
        result.screenshot = screenshot.screenshotPath;
        result.screenshotBytes = screenshot.screenshotBytes;
        result.passed = Boolean(file && file.path.startsWith(DOWNLOAD_DIR) && file.bytes > 0 && statePasses(state));
      } catch (error) {
        result.error = error.message;
        result.passed = false;
      }
      result.finishedAt = new Date().toISOString();
      console.log(`${result.passed ? "PASS" : "FAIL"} ${String(index).padStart(2, "0")} ${item.slug}`);
      downloadResults.push(result);
      index += 1;
    }

    const relevantLogs = logs.filter(keepLog);
    const unexpectedErrors = relevantLogs.filter(unexpectedLog);
    const report = {
      passed: results.every((result) => result.passed)
        && downloadResults.every((result) => result.passed)
        && layoutCheck.passed
        && tooltipCheck.passed
        && unexpectedErrors.length === 0,
      appUrl: serverInfo.url,
      serverInfo: {
        started: serverInfo.started,
        healthUrl: serverInfo.healthUrl,
        stdoutPath: serverInfo.stdoutPath || null,
        stderrPath: serverInfo.stderrPath || null,
      },
      chromePath,
      browserVersion: version.Browser,
      cdpPort,
      profileDir,
      screenshotDir: SCREENSHOT_DIR,
      downloadDir: DOWNLOAD_DIR,
      pageBefore,
      initialState,
      layoutCheck,
      tooltipCheck,
      externalManifestLoaded: logs.some((entry) => /Loaded REEF3D external frame manifest/i.test(entry.text)),
      externalModeActive: logs.some((entry) => /external REEF3D solver mode is active/i.test(entry.text)),
      scenarios: results,
      downloads: downloadResults,
      allDownloadedFiles: await listDownloads(),
      relevantLogs,
      unexpectedErrors,
      generatedAt: new Date().toISOString(),
    };
    await fs.writeFile(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(JSON.stringify({
      passed: report.passed,
      scenarios: results.length,
      downloads: downloadResults.length,
      report: REPORT_PATH,
      screenshots: SCREENSHOT_DIR,
      downloadDir: DOWNLOAD_DIR,
    }, null, 2));
    if (!report.passed) {
      process.exitCode = 1;
    }
  } finally {
    client?.close();
    if (chrome?.pid) {
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
