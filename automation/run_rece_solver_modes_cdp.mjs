import { spawn } from "node:child_process";
import { createWriteStream, existsSync } from "node:fs";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RECE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BUILD_PYTHON_WINDOWS = path.resolve(RECE_ROOT, "..", "tools", "rece-build-venv", "Scripts", "python.exe");
const BUILD_PYTHON_POSIX = path.resolve(RECE_ROOT, "..", "tools", "rece-build-venv", "bin", "python");
const SCREENSHOT_DIR = path.join(RECE_ROOT, "examples", "hk_victoria_smoke", "screenshots", "solver_modes");
const REPORT_PATH = path.join(SCREENSHOT_DIR, "rece_solver_modes_report.json");
const SCREENSHOT_PATH = path.join(SCREENSHOT_DIR, "solver_modes.png");
const CDP_COMMAND_TIMEOUT_MS = Number(process.env.RECE_CDP_COMMAND_TIMEOUT_MS || 45000);
const APP_URL = process.env.RECE_URL || "http://127.0.0.1:8791/";
const DEBUG_HOST = "127.0.0.1";
const DEBUG_PORT_START = Number(process.env.CDP_PORT || 9382);

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
  const host = app.hostname || "127.0.0.1";
  const port = Number(app.port || 8787);
  const stdoutPath = path.join(RECE_ROOT, "logs", `server_${port}_solver_modes_stdout.log`);
  const stderrPath = path.join(RECE_ROOT, "logs", `server_${port}_solver_modes_stderr.log`);
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
      }, CDP_COMMAND_TIMEOUT_MS);
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

async function postForm(url, fields) {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    form.append(key, value);
  }
  const response = await fetch(url, { method: "POST", body: form });
  const body = await response.json().catch(() => ({}));
  return { status: response.status, ok: response.ok, body };
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
  const profileDir = path.join(RECE_ROOT, "tmp", `chrome_profile_rece_solver_modes_${cdpPort}`);
  await fs.rm(profileDir, { recursive: true, force: true });
  await fs.mkdir(profileDir, { recursive: true });
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
  const chrome = spawn(chromePath, chromeArgs, { stdio: "ignore", windowsHide: true });

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
    await sleep(5000);

    const panelState = await runtimeValue(client, `(() => new Promise((resolve) => {
      document.querySelector('[data-lang="cn"]')?.click();
      const solver = document.getElementById('rece-solver-select');
      solver.value = 'reef3d';
      solver.dispatchEvent(new Event('change', { bubbles: true }));
      const lockedIds = [
        'start-simulation-btn',
        'nlsw-select',
        'courant-input',
        'incident_wave_H-input',
        'disturbance-button',
      ];
      const isLocked = (el) => Boolean(
        el?.getAttribute('aria-disabled') === 'true'
        && el?.dataset?.receLocked === 'reef3d'
        && el?.classList?.contains('rece-control-locked')
      );
      setTimeout(() => {
        const lockedControls = {};
        for (const id of lockedIds) {
          const el = document.getElementById(id);
          lockedControls[id] = el ? {
            locked: isLocked(el),
            ariaDisabled: el.getAttribute('aria-disabled'),
            receLocked: el.dataset.receLocked || '',
            readOnly: 'readOnly' in el ? Boolean(el.readOnly) : null,
            className: el.className,
          } : null;
        }
        const bodyText = document.body.innerText;
        document.getElementById('rece-run-custom-reef3d-btn')?.click();
        setTimeout(() => {
          const missingFilesStatus = document.getElementById('rece-custom-run-status')?.textContent || '';
          const brand = document.querySelector('.rece-brand-panel');
          const logo = document.querySelector('.rece-panel-logo');
          const unitLogo = document.querySelector('.rece-unit-logo');
          resolve({
            title: document.title,
            language: document.documentElement.lang,
            solverValue: solver.value,
            controlsHidden: document.getElementById('rece-reef3d-controls').classList.contains('rece-runner-hidden'),
            zipHidden: document.getElementById('rece-reef-zip-panel').classList.contains('rece-runner-hidden'),
            bodyHasCnSolverMode: bodyText.includes('\\u6c42\\u89e3\\u5668\\u6a21\\u5f0f'),
            bodyHasCnBackendJob: bodyText.includes('REEF3D \\u540e\\u7aef\\u4f5c\\u4e1a'),
            bodyHasCnOutputFrames: bodyText.includes('\\u8f93\\u51fa\\u5e27\\u6570'),
            missingFilesStatus,
            hasCnMissingFilesStatus: missingFilesStatus.includes('\\u52a0\\u8f7d Celeris config.json'),
            lockedControls,
            brandText: brand?.innerText.trim() || '',
            brandLogoSrc: logo?.getAttribute('src') || '',
            brandLogoWidth: logo?.naturalWidth || 0,
            brandLogoHeight: logo?.naturalHeight || 0,
            unitLogoSrc: unitLogo?.getAttribute('src') || '',
            unitLogoWidth: unitLogo?.naturalWidth || 0,
            unitLogoHeight: unitLogo?.naturalHeight || 0,
            hasRightsText: Boolean(
              (brand?.innerText || '').includes('HKUST-GZ / MHRF')
              && (brand?.innerText || '').includes('Marine Hydrodynamic Research Facility')
              && (brand?.innerText || '').includes('GPL-3.0-or-later')
              && !(brand?.innerText || '').includes('RECE WebGPU')
              && !(brand?.innerText || '').includes('香港科技大学（广州） /')
            ),
          });
        }, 350);
      }, 500);
    }))()`);

    const lockHintState = await runtimeValue(client, `(() => {
      document.getElementById('start-simulation-btn')?.click();
      return new Promise((resolve) => setTimeout(() => {
        const toast = document.getElementById('rece-lock-toast');
        resolve({
          visible: toast?.classList.contains('is-visible') || false,
          text: toast?.textContent || '',
          hasCnHint: (toast?.textContent || '').includes('\\u6c42\\u89e3\\u5668\\u63a7\\u4ef6\\u5df2\\u9501\\u5b9a'),
        });
      }, 350));
    })()`);

    const uploadLimitState = await runtimeValue(client, `(() => {
      const oldAlert = window.alert;
      let message = "";
      window.alert = (value) => { message = String(value); };
      const ok = window.RECE_TEST_HOOKS?.validateUploadFiles?.([{ name: "huge_case.zip", size: 1073741824 + 1 }]);
      window.alert = oldAlert;
      return {
        ok,
        message,
        hasEnglish: /browser uploads are limited/i.test(message),
        hasChinese: /浏览器上传限制/.test(message),
      };
    })()`);

    const localImportState = await runtimeValue(client, `(() => new Promise((resolve) => {
      const solver = document.getElementById('rece-solver-select');
      solver.value = 'reef3d';
      solver.dispatchEvent(new Event('change', { bubbles: true }));
      const mode = document.getElementById('rece-reef-input-mode');
      mode.value = 'local_directory';
      mode.dispatchEvent(new Event('change', { bubbles: true }));
      const originalFetch = window.fetch.bind(window);
      let phase = 'running';
      let cancelCalled = false;
      let outputPickerCalled = false;
      const runRequests = [];
      window.fetch = async (url, options = {}) => {
        const textUrl = String(url);
        if (textUrl.includes('/api/runs') && String(options.method || '').toUpperCase() === 'POST' && options.body) {
          const body = JSON.parse(String(options.body));
          runRequests.push(body);
          if (body.mode === 'view') {
            return new Response(JSON.stringify({
              id: 'mock-view-run',
              status: 'complete',
              phase: 'complete',
              frame_count: 0,
              config_url: '/mock-view-run/assets/config.json',
              manifest_url: '/mock-view-run/manifest',
            }), { status: 202, headers: { 'Content-Type': 'application/json' } });
          }
          if (body.mode === 'solve') {
            return new Response(JSON.stringify({
              id: 'mock-solve-run',
              status: 'queued',
              phase: 'queued',
              frame_count: 0,
              status_url: '/api/runs/mock-solve-run/status',
              cancel_url: '/api/runs/mock-solve-run/cancel',
            }), { status: 202, headers: { 'Content-Type': 'application/json' } });
          }
        }
        if (textUrl.includes('/api/runs/mock-solve-run/status')) {
          return new Response(JSON.stringify({
            id: 'mock-solve-run',
            status: 'complete',
            phase: 'complete',
            frame_count: 0,
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        if (textUrl.includes('/mock-import-running/status')) {
          return new Response(JSON.stringify({
            id: 'mock-import-running',
            status: 'running',
            phase: 'scanning',
            files_scanned: 7,
            bytes_scanned: 2048,
            estimated_total_bytes: 4096,
            progress: 0.42,
            eta_seconds: 12,
            cancel_url: '/mock-import-running/cancel',
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        if (textUrl.includes('/mock-import-running/cancel')) {
          cancelCalled = true;
          return new Response(JSON.stringify({
            id: 'mock-import-running',
            status: 'cancelled',
            phase: 'cancelled',
            files_scanned: 7,
            bytes_scanned: 2048,
            progress: 0,
          }), { status: 202, headers: { 'Content-Type': 'application/json' } });
        }
        if (textUrl.includes('/mock-import-complete/status')) {
          return new Response(JSON.stringify({
            id: 'mock-import-complete',
            status: 'complete',
            phase: 'complete',
            files_scanned: 12,
            bytes_scanned: 8192,
            estimated_total_bytes: 8192,
            progress: 1,
            eta_seconds: 0,
            result_index_url: '/mock-import-complete/result_index',
            lod_manifest_url: '/mock-import-complete/lod/manifest',
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        if (textUrl.includes('/mock-import-complete/result_index')) {
          return new Response(JSON.stringify({
            summary: { free_surface_files: 2, volume_field_files: 1, diagnostic_logs: 3 },
            result_files: [
              { id: 'fsf', category: 'free_surface', relative_path: 'REEF3D_NHFLOW_VTP_FSF/f0.vtp', url: '/mock-file/fsf' },
              { id: 'vol', category: 'volume_field', relative_path: 'REEF3D_NHFLOW_VTU/u0.vtu', url: '/mock-file/vol' },
            ],
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        if (textUrl.includes('/mock-import-complete/lod/manifest')) {
          return new Response(JSON.stringify({
            default_lod_factor: 4,
            lod_levels: [
              { factor: 2, is_default: false, visualization_grid: { width: 2000, height: 1000 } },
              { factor: 4, is_default: true, visualization_grid: { width: 1000, height: 500 } },
            ],
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        return originalFetch(url, options);
      };
      window.pywebview = {
        api: {
          choose_case_directory: async () => {
            if (phase === 'complete') {
              return { id: 'mock-import-complete', status_url: '/mock-import-complete/status', cancel_url: '/mock-import-complete/cancel' };
            }
            return { id: 'mock-import-running', status_url: '/mock-import-running/status', cancel_url: '/mock-import-running/cancel' };
          },
          choose_run_output_directory: async () => {
            outputPickerCalled = true;
            return { path: 'D:/AAA/rece_mock_output', token: 'mock-output-token' };
          },
        },
      };
      const choose = document.getElementById('rece-choose-case-directory-btn');
      choose.click();
      setTimeout(() => {
        const progressBeforeCancel = Number(document.getElementById('rece-import-progress')?.value || 0);
        const etaText = document.getElementById('rece-import-eta')?.textContent || '';
        document.getElementById('rece-cancel-import-btn')?.click();
        setTimeout(() => {
          const cancelStatus = document.getElementById('rece-custom-run-status')?.textContent || '';
          phase = 'complete';
          choose.click();
          setTimeout(() => {
            const panel = document.getElementById('rece-local-import-panel');
            const style = getComputedStyle(panel);
            const lod = document.getElementById('rece-lod-select');
            const options = [...lod.options].map((option) => ({ value: option.value, text: option.textContent, selected: option.selected }));
            const resultText = document.getElementById('rece-result-index')?.textContent || '';
            const loadButton = document.getElementById('rece-load-lod-viewer-btn');
            const solveButton = document.getElementById('rece-run-local-solve-btn');
            const loadInitiallyEnabled = !loadButton.disabled;
            const solveInitiallyEnabled = !solveButton.disabled;
            loadButton.click();
            setTimeout(() => {
              solveButton.click();
              setTimeout(() => {
                window.fetch = originalFetch;
                delete window.pywebview;
                const viewRequest = runRequests.find((body) => body.mode === 'view');
                const solveRequest = runRequests.find((body) => body.mode === 'solve');
                resolve({
                  modeValue: mode.value,
                  panelVisible: style.display !== 'none' && style.visibility !== 'hidden',
                  progressBeforeCancel,
                  etaText,
                  cancelCalled,
                  cancelStatus,
                  lodDisabled: lod.disabled,
                  lodOptions: options,
                  resultText,
                  hasRawVsLodText: /Scientific source: raw REEF3D outputs/.test(resultText) && /Celeris LOD cache/.test(resultText),
                  loadInitiallyEnabled,
                  solveInitiallyEnabled,
                  outputPickerCalled,
                  runRequests,
                  viewRequest,
                  solveRequest,
                  solveStatus: document.getElementById('rece-custom-run-status')?.textContent || '',
                });
              }, 500);
            }, 250);
          }, 500);
        }, 250);
      }, 350);
    }))()`);

    const missingFilesStatus = panelState.missingFilesStatus || "";

    const apiMissing = await postForm(new URL("/api/runs", serverInfo.url).toString(), {
      solver: "reef3d",
      input_mode: "celeris_files",
      params: JSON.stringify({ mpi_ranks: 1 }),
    });
    const apiBadZipForm = new FormData();
    apiBadZipForm.append("solver", "reef3d");
    apiBadZipForm.append("input_mode", "reef3d_zip");
    apiBadZipForm.append("params", JSON.stringify({ mpi_ranks: 1 }));
    apiBadZipForm.append("reef3d_zip", new Blob(["not a zip"], { type: "application/zip" }), "bad.zip");
    const badZipResponse = await fetch(new URL("/api/runs", serverInfo.url), { method: "POST", body: apiBadZipForm });
    const apiBadZip = { status: badZipResponse.status, body: await badZipResponse.json().catch(() => ({})) };
    const cancelResponse = await fetch(new URL("/api/runs/not-a-run/cancel", serverInfo.url), { method: "POST" });
    const apiCancelUnknown = { status: cancelResponse.status, body: await cancelResponse.json().catch(() => ({})) };

    const runtimeInfo = await runtimeValue(client, `(() => window.RECE_RUNTIME_INFO || {})()`);
    let celerisState = null;
    if (!runtimeInfo.package_mode) {
      await runtimeValue(client, `(() => {
      document.querySelector('[data-lang="en"]')?.click();
      const solver = document.getElementById('rece-solver-select');
      solver.value = 'celeris';
      solver.dispatchEvent(new Event('change', { bubbles: true }));
      const select = document.getElementById('run_example-select');
      select.value = '0';
      select.dispatchEvent(new Event('change', { bubbles: true }));
      document.getElementById('run-example-simulation-btn').click();
      return true;
    })()`);

      const celerisStart = Date.now();
      while (Date.now() - celerisStart < 30000) {
        celerisState = await runtimeValue(client, `(() => ({
          selectedExample: document.getElementById('run_example-select')?.value,
          canvasWidth: document.getElementById('webgpuCanvas')?.width || 0,
          canvasHeight: document.getElementById('webgpuCanvas')?.height || 0,
          statusText: document.getElementById('simstatus-container')?.innerText || '',
        }))()`);
        const logs = consoleLogs(client.events);
        if (
          celerisState.selectedExample === "0"
          && celerisState.canvasWidth > 300
          && logs.some((entry) => /Using Celeris equations|Compute \/ Render loop starting/i.test(entry.text))
        ) {
          break;
        }
        await sleep(1000);
      }
    } else {
      celerisState = await runtimeValue(client, `(() => ({
        packageModeSkipped: true,
        selectedExample: document.getElementById('run_example-select')?.value || '',
        canvasWidth: document.getElementById('webgpuCanvas')?.width || 0,
        canvasHeight: document.getElementById('webgpuCanvas')?.height || 0,
        statusText: document.getElementById('simstatus-container')?.innerText || '',
      }))()`);
    }

    const screenshot = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await fs.writeFile(SCREENSHOT_PATH, Buffer.from(screenshot.data, "base64"));
    const logs = consoleLogs(client.events);
    const unexpectedLogs = logs.filter((entry) => /exception/i.test(entry.level) || /uncaught|unhandledrejection/i.test(entry.text));
    const report = {
      passed: Boolean(
        panelState.solverValue === "reef3d"
        && panelState.controlsHidden === false
        && panelState.bodyHasCnSolverMode
        && panelState.bodyHasCnBackendJob
        && panelState.bodyHasCnOutputFrames
        && panelState.hasCnMissingFilesStatus
        && Object.values(panelState.lockedControls || {}).every((value) => value?.locked)
        && /assets\/rece-panel-logo\.png$/i.test(panelState.brandLogoSrc || "")
        && panelState.brandLogoWidth > 0
        && panelState.brandLogoHeight > 0
        && /assets\/hkust-gz-logo\.png$/i.test(panelState.unitLogoSrc || "")
        && panelState.unitLogoWidth > 0
        && panelState.unitLogoHeight > 0
        && panelState.hasRightsText
        && lockHintState.visible
        && lockHintState.hasCnHint
        && uploadLimitState.ok === false
        && uploadLimitState.hasEnglish
        && uploadLimitState.hasChinese
        && localImportState.panelVisible
        && localImportState.progressBeforeCancel > 0.4
        && localImportState.cancelCalled
        && /cancelled|已取消/i.test(localImportState.cancelStatus)
        && localImportState.lodDisabled === false
        && localImportState.lodOptions.some((option) => option.value === "4" && option.selected)
        && localImportState.hasRawVsLodText
        && localImportState.loadInitiallyEnabled
        && localImportState.solveInitiallyEnabled
        && localImportState.outputPickerCalled
        && localImportState.viewRequest?.mode === "view"
        && localImportState.viewRequest?.lod_factor === 4
        && localImportState.solveRequest?.mode === "solve"
        && localImportState.solveRequest?.output_token === "mock-output-token"
        && localImportState.solveRequest?.params?.mpi_ranks === 4
        && apiMissing.status === 400
        && apiBadZip.status === 400
        && apiCancelUnknown.status === 404
        && (
          runtimeInfo.package_mode
          || (celerisState?.selectedExample === "0" && celerisState?.canvasWidth > 300)
        )
        && unexpectedLogs.length === 0
      ),
      appUrl: serverInfo.url,
      serverInfo,
      chromePath,
      cdpPort,
      runtimeInfo,
      panelState,
      lockHintState,
      uploadLimitState,
      localImportState,
      missingFilesStatus,
      apiMissing,
      apiBadZip,
      apiCancelUnknown,
      celerisState,
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
