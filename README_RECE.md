# RECE 部署与开发接手说明

最后更新：2026-06-07

## 0F. GitHub 安装指引同步, 2026-06-07

本轮 Linux Release 已更新为从最新源码真实构建的 Ubuntu 24.04 LTS amd64 包，不是 Windows exe 改名。GitHub 首页安装指引需要同步，因为 Linux 便携包的推荐启动命令应使用 `./RECE`，并且用户应从对应平台的 Release 页面下载资产和 `.sha256` 校验文件。

已同步 `README.md`：

- Windows 安装入口明确指向 `https://github.com/yih1827686127/RECE/releases/tag/v0.1.0-windows`。
- Linux 安装入口明确指向 `https://github.com/yih1827686127/RECE/releases/tag/v0.1.0-linux`。
- Linux `.deb` 安装流程保留 `sudo apt install ./rece_0.1.0+linux1_amd64.deb` 后运行 `rece`。
- Linux 便携包流程更新为 `tar -xzf RECE-linux-x86_64.tar.gz`、`cd RECE-linux-x86_64`、`./install-deps.sh`、`./RECE`。
- Linux 安装前要求运行 `sha256sum -c` 校验对应 `.sha256` 文件。

同时已同步 Linux Release notes，让用户在 GitHub Release 页面也能直接看到下载、校验、`.deb` 安装和便携包启动命令。

## 0E. Ubuntu Linux packaged release, 2026-06-06

This update adds the Ubuntu 24.04 LTS amd64 packaging path without changing the existing Windows release.

- Release tag: `v0.1.0-linux`
- Release title: `RECE Linux packaged release`
- Release assets: `RECE-linux-x86_64.tar.gz`, `RECE-linux-x86_64.tar.gz.sha256`, `rece_0.1.0+linux1_amd64.deb`, `rece_0.1.0+linux1_amd64.deb.sha256`
- Linux runtime: pywebview GTK/WebKitGTK desktop window; writes go to `$XDG_DATA_HOME/RECE` or `~/.local/share/RECE`
- Linux solver binaries: `third_party/REEF3D/bin/linux-x86_64/reef3d` and `DiveMESH`, with `RECE_REEF3D_BIN`, `RECE_DIVEMESH_BIN`, and `RECE_MPIEXEC` overrides

Build entry:

```bash
bash packaging/linux/build_linux_package.sh
```

GitHub Actions workflow: `.github/workflows/linux-release.yml`. It installs OpenMPI, HYPRE, GTK/WebKitGTK, Python and Node dependencies on `ubuntu-24.04`, builds Linux solver binaries, builds the portable tarball and `.deb`, runs Python tests, runs a small custom REEF3D solver smoke test, runs package-mode UI CDP, install-tests the `.deb`, and creates or updates the `RECE Linux packaged release` only for `v*-linux` tags. Do not replace or edit the existing `v0.1.0-windows` release.

## 0D. 自定义安装目录热修复, 2026-06-05

本轮修复 `RECE_Setup.exe` 在已有安装记录或默认 Inno Setup 策略下看起来只能固定安装到默认目录的问题。`packaging\RECE_Setup.iss` 现在显式设置 `DisableDirPage=no`，安装向导会始终显示 `Select Destination Location` 页面；用户可以接受默认 `{autopf}\RECE`，也可以点击 Browse 选择自己的安装位置。静默安装仍可通过 `/DIR=...` 指定目标目录。

已新增回归测试 `RECEPackagingTests.test_installer_always_shows_install_directory_page`，直接检查 `packaging\RECE_Setup.iss` 保留 `DefaultDirName={autopf}\RECE` 且 `DisableDirPage=no`，防止后续打包脚本退回自动隐藏目录页。

已重新封装本体和安装包：

```text
D:\AAA\RECE\dist\RECE\RECE.exe
D:\AAA\RECE\dist\installer\RECE_Setup.exe
```

当前本地安装包校验：

```powershell
Get-FileHash -Algorithm SHA256 D:\AAA\RECE\dist\installer\RECE_Setup.exe
Get-Content D:\AAA\RECE\dist\installer\RECE_Setup.exe.sha256
```

`packaging\build_installer.ps1` 会在每次本地重建后写入 `dist\installer\RECE_Setup.exe.sha256`，因此该旁置校验文件是当前安装包的权威 SHA256 来源，避免 README 内写死旧哈希。

安装验证：使用新 `RECE_Setup.exe` 静默安装到自定义目录 `D:\AAA\RECE_test_install_custom`，安装日志确认命令行包含 `/DIR=D:\AAA\RECE_test_install_custom` 且文件写入该目录；已验证安装目录包含 `RECE.exe`、`_internal\scipy\_lib\_ccallback_c.cp312-win_amd64.pyd`、`_internal\web\assets\rece-app.ico`、`rece-panel-logo.png` 和 `hkust-gz-logo.png`。随后启动安装后的 `RECE.exe --port 8794 --debug`，并用 `RECE_URL=http://127.0.0.1:8794/ node automation\run_rece_packaged_runtime_cdp.mjs` 通过 package-mode UI 检查。

本轮验证命令和结果：

```powershell
& 'D:\AAA\tools\rece-build-venv\Scripts\python.exe' -m unittest tests.test_rece -v
& 'D:\AAA\tools\rece-build-venv\Scripts\python.exe' -m rece.workflow validate
node --check automation\run_rece_packaged_runtime_cdp.mjs
node --check automation\run_rece_solver_modes_cdp.mjs
node --check automation\run_rece_core_matrix_cdp.mjs
powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1
node automation\run_rece_packaged_runtime_cdp.mjs
node automation\run_rece_solver_modes_cdp.mjs
node automation\run_rece_core_matrix_cdp.mjs
$env:RECE_CDP_WINDOW_SIZE='390,844'; node automation\run_rece_core_matrix_cdp.mjs; Remove-Item Env:\RECE_CDP_WINDOW_SIZE
```

结果：`D:\AAA\tools\rece-build-venv` 中 Python 单测 `25/25` 通过；`python -m rece.workflow validate` 返回 `status: ok`、`frame_count: 5`、`expected_frame_bytes: 153600`；Celeris 上传小作业 `output_frames=2` 产出 2 帧；native zip 小作业 `output_frames=3` 产出 3 帧并从 `M 10` 自动采用 `mpi_ranks=1`；完整 HK Celeris 上传准备阶段接受 600x400 网格；package-mode UI、solver-mode UI、桌面核心矩阵和 `390x844` 窄屏核心矩阵均通过。安装包使用 `D:\AAA\tools\rece-build-venv` 中的 pinned 依赖，不使用全局 Python。

注意：`RECE.exe` 是窗口化桌面程序。若只想检查 `--print-runtime` 退出码，请在 PowerShell 中使用 `Start-Process -Wait -PassThru`；运行时 JSON 状态仍推荐通过已启动服务的 `GET /api/runtime` 查看。

## 0C. GitHub Publication Handoff, 2026-06-05

本轮已按“用户直接下载安装包、本地安装后打开 RECE 处理自己的数据”的目标完成 GitHub 发布。RECE 没有被拆成多个仓库；GitHub 上的 `RECE` 是总项目，包含 RECE Python 衔接层、Celeris-WebGPU 核心前端/WebGPU 管线、REEF3D/DIVEMesh 核心源码与运行组件、打包脚本、图标、许可证和说明文件。

### 0C.1 GitHub 位置

- 源码仓库：`https://github.com/yih1827686127/RECE`
- Release 页面：`https://github.com/yih1827686127/RECE/releases/tag/v0.1.0-windows`
- 安装包直链：`https://github.com/yih1827686127/RECE/releases/download/v0.1.0-windows/RECE_Setup.exe`
- 当前远端分支：`main`
- 初始发布源码提交：`c18f75e81b01cf37dcbb4723808f25ae99a28d05`，提交信息为 `Initial RECE packaged release`
- Release tag：`v0.1.0-windows`
- Release title：`RECE Windows packaged release`
- Release asset：`RECE_Setup.exe`，大小 `510640461` bytes，GitHub asset digest 为 `sha256:7fcdbffe72a40339c2cc8332e501c9f6dd8b837b72c043ebaf4a654f975ee585`

### 0C.2 用户安装说明

中文：

1. 打开 Release 页面并下载 `RECE_Setup.exe`。
2. 双击运行安装程序，在 `Select Destination Location` 页面接受默认路径或点击 Browse 选择自己的安装位置。
3. 安装完成后，从桌面快捷方式或开始菜单启动 `RECE.exe`。
4. 如果启动器提示缺少 WebView2 Runtime 或 Microsoft MPI，按提示安装对应运行时后重新打开 `RECE.exe`。

English:

1. Open the Release page and download `RECE_Setup.exe`.
2. Run the installer and use the `Select Destination Location` page to accept the default path or choose a custom install directory.
3. After installation, launch `RECE.exe` from the Desktop shortcut or the Start Menu.
4. If the launcher reports that WebView2 Runtime or Microsoft MPI is missing, install the prompted runtime and start `RECE.exe` again.

### 0C.3 上传架构和提交范围

- `RECE_Setup.exe` 只作为 GitHub Release 附件发布，不进入普通 Git 历史。
- 根目录 `.gitignore` 已新增并提交，用于排除构建产物、临时目录、日志、浏览器缓存、测试截图、示例数据和预计算输出。
- 已提交的核心范围包括：`rece/`、`web/` 的运行核心、`third_party/REEF3D/src`、`third_party/REEF3D/bin`、`third_party/REEF3D/docs`、`packaging/`、`automation/`、`tests/`、`art/`、根目录 README/许可证/环境文件。
- 已明确排除：`dist/`、`build/`、`tmp/`、`logs/`、`examples/`、`web/examples/`、`web/transect_version/examples/`、`third_party/REEF3D/simulations/`、`third_party/REEF3D/src/REEF3D/Tutorials/`、`web/automation/`、`web/automation_edge_browser/`、`web/automation_firefox_browser/`。
- REEF3D 与 DIVEMesh 原始源码目录内部带有自己的 `.git` 元数据。为避免 GitHub 上出现 submodule/gitlink，本轮提交时临时将 `third_party\REEF3D\src\REEF3D\.git` 和 `third_party\REEF3D\src\DIVEMesh\.git` 移到 `tmp\nested_git_backup`，完成 `git add` 后已恢复原位。远端仓库中 REEF3D/DIVEMesh 源码以普通文件形式存在。
- 未使用 Git LFS；当前普通 Git 跟踪文件均未超过 GitHub 100MB 单文件限制。

### 0C.4 本轮验证证据

本地发布前验证：

```powershell
node --check web\js\i18n.js
node --check web\js\main.js
node --check automation\run_rece_packaged_runtime_cdp.mjs
node --check automation\run_rece_solver_modes_cdp.mjs
node --check automation\run_rece_core_matrix_cdp.mjs
python -m unittest tests.test_rece -v
python -m rece.workflow validate
```

结果：JS 语法检查通过；Python 单测 `18/18` 通过；`python -m rece.workflow validate` 返回 `status: ok`、`frame_count: 5`、`expected_frame_bytes: 153600`。当前全局开发环境仍会显示 SciPy/NumPy 版本警告，但安装包使用 `D:\AAA\tools\rece-build-venv` 中的 pinned 依赖，不使用该全局环境。

GitHub 发布后验证：

```powershell
git ls-remote --heads origin main
gh release view v0.1.0-windows --repo yih1827686127/RECE --json name,tagName,url,assets
git show origin/main:README.md
git ls-files | Select-String -Pattern '^(examples|dist|build|tmp|logs|screenshots)/|^web/examples/|^web/transect_version/examples/|^third_party/REEF3D/simulations/|^third_party/REEF3D/src/REEF3D/Tutorials/'
```

已确认：首次发布时 `origin/main` 指向 `c18f75e81b01cf37dcbb4723808f25ae99a28d05`；Release asset `RECE_Setup.exe` 状态为 `uploaded`；`README.md` 含中英双语安装说明；Git 跟踪文件中没有示例数据、构建缓存、日志目录或 REEF3D simulation/tutorial 输出。

### 0C.5 后续 AI 注意事项

- 若只更新文档或源码，正常 `git add`、`git commit`、`git push` 到 `main` 即可。
- 若重新生成安装包，不要把 `dist\installer\RECE_Setup.exe` 加入 Git；应创建新的 tag/Release 或替换 Release asset。
- 若需要重新提交 REEF3D/DIVEMesh 源码目录，必须避免把其内部 `.git` 提交成 submodule/gitlink。推荐继续使用“临时移出嵌套 `.git`，添加源码文件后恢复”的方式。
- 当前 GitHub CLI 已通过 `winget` 安装，路径为 `%LOCALAPPDATA%\Microsoft\WinGet\Links\gh.exe`；本轮已完成 `gh auth login` 并登录为 `yih1827686127`。
- 用户侧目标是下载安装包即可使用，后续文档优先把 Release 下载链接和 `RECE.exe` 启动流程放在最前面。

## 0B. Windows Installer / Packaged Runtime Handoff, 2026-06-04

### 0B.1 Installed-startup hotfix, 2026-06-04 19:10 HKT

- Fixed the installed `RECE.exe` startup popup reported from `D:\AAA\RECE_test_install`: PyInstaller/SciPy could fail with `cannot import name '_ccallback_c' from 'scipy._lib'`.
- `rece.jobs` now lazy-loads `rece.converter` only when REEF3D frame conversion is needed, so the desktop UI can start cleanly before a backend conversion job imports SciPy/VTK.
- `packaging\rece_pyinstaller.spec` explicitly freezes `scipy._lib._ccallback_c`, `scipy._lib._fpumode`, `scipy._lib.messagestream`, and `scipy.spatial._ckdtree`.
- `packaging\build_installer.ps1` removes `__pycache__`, `.pyc`, and duplicate `packaging\vendor` files from `source\RECE_corresponding_source.zip`; runtime vendor installers are still bundled under `_internal\vendor`.
- Rebuilt final installer: `D:\AAA\RECE\dist\installer\RECE_Setup.exe`.
- Verified the installed app path directly: installed to `D:\AAA\RECE_test_install`, confirmed `_internal\scipy\_lib\_ccallback_c.cp312-win_amd64.pyd`, launched installed `RECE.exe --port 8793 --debug`, passed `node automation\run_rece_packaged_runtime_cdp.mjs`, stopped the app, and uninstalled cleanly.

### 0B.2 CN / REEF3D control lock / icon fix, 2026-06-04 20:20 HKT

- 修复 `Language = CN` 时 REEF3D runner 仍显示英文的问题；`Solver Mode`、REEF3D 输入模式、MPI/输出/波浪参数、run/cancel 按钮和 REEF3D 作业状态提示现在都会随中英文切换。
- 当 `Solver Mode = REEF3D backend job` 时，Celeris-WebGPU 只作为外部 REEF3D 帧的 WebGPU 播放和渲染器；内部 Celeris 求解器控件、边界/入射波、扰动、地形编辑和结构设计等不会改变后端 REEF3D 作业的控件已统一灰色锁定。
- 锁定控件保留可感知的灰锁状态：`aria-disabled="true"`、`data-rece-locked="reef3d"` 和 `.rece-control-locked`；用户点击、键盘操作或聚焦这些控件时，会显示随 EN/CN 切换的提示，要求到 REEF3D runner 中修改参数并重新提交后端作业。
- 已按最终确认资源更新图标：`RECE.exe` 和 `RECE_Setup.exe` 使用当前最新 `art\icon0.png` 生成的 `web\assets\rece-app.ico`；交互面板左上角改为纵向堆叠的响应式品牌区，当前最新 `art\icon1.png` 位于上方，`art\logo.png` 同步出的 HKUST-GZ 单位 Logo 紧随其下，下面保留 HKUST-GZ / MHRF 署名权益文字。
- `packaging\build_installer.ps1` 在每次打包前自动同步 `art\icon1.png`、`art\icon0.png` 和 `art\logo.png` 到 web assets，并重新生成 ico，避免 setup 或本体 exe 使用旧图标。
- `automation\run_rece_solver_modes_cdp.mjs` 已扩展为本问题的回归测试：自动切 CN、验证 REEF3D 面板中文、锁定控件、中文锁定 toast、左上角响应式纵向堆叠 icon1、单位 Logo 和权益文字；`automation\run_rece_packaged_runtime_cdp.mjs` 已加入 package-mode 品牌区检查；`automation\run_rece_core_matrix_cdp.mjs` 已更新为识别 aria/data/class 锁定语义，并加固下载落盘检测。
- 本轮源码侧验证已通过：`node --check web\js\i18n.js`、`node --check web\js\main.js`、`node --check automation\run_rece_packaged_runtime_cdp.mjs`、`node --check automation\run_rece_solver_modes_cdp.mjs`、`node --check automation\run_rece_core_matrix_cdp.mjs`、`node automation\run_rece_packaged_runtime_cdp.mjs`、`node automation\run_rece_solver_modes_cdp.mjs`、`node automation\run_rece_core_matrix_cdp.mjs`、`python -m unittest tests.test_rece -v`、`python -m rece.workflow validate`。
- 已重新封装本体和安装包：`D:\AAA\RECE\dist\RECE\RECE.exe`、`D:\AAA\RECE\dist\installer\RECE_Setup.exe`。最终安装验证：静默安装到 `D:\AAA\RECE_test_install`，确认安装目录含最新 `rece-app.ico`、`rece-panel-logo.png`、`hkust-gz-logo.png` 和 SciPy `_ccallback_c`，启动安装后的 `RECE.exe --port 8793 --debug` 后通过 `node automation\run_rece_packaged_runtime_cdp.mjs`。

本轮已经把 RECE 封装为 Windows 安装版软件。最终安装包位于：

```powershell
D:\AAA\RECE\dist\installer\RECE_Setup.exe
```

安装后用户只需要点击桌面或开始菜单里的 `RECE.exe`。这个 exe 会自动启动本机 RECE Python HTTP 服务、打开独立 WebView2 桌面窗口，并在窗口关闭时清理后台服务和仍在运行的 REEF3D 作业；正常使用时不会打开外部浏览器。

安装版保留三部分核心代码/资源：

- Celeris-WebGPU 前端、WebGPU 渲染管线和运行资产。
- REEF3D / DIVEMesh 运行二进制以及对应源码材料。
- RECE Python 衔接服务、上传 workflow、路径守卫、转换器和任务管理器。

安装包策略：

- 不包含 `web\examples`、`third_party\REEF3D\simulations`、香港示例数据、预计算帧、截图、浏览器 profile 或 demo cache。
- 安装目录只作为只读程序资源；package mode 下 `logs`、`tmp`、`examples\custom_runs`、上传文件、转换输出和 WebView2 profile 写入 `%LOCALAPPDATA%\RECE`。
- package mode 隐藏 `Choose Example`、`Run Example Simulation`、固定香港 smoke workflow 等示例入口，只保留用户上传 Celeris 文件或 REEF3D case zip 的入口。
- 安装包内包含 `LICENSE`、`THIRD_PARTY_NOTICES.md`、README、环境文件，以及 `source\RECE_corresponding_source.zip`。

构建命令：

```powershell
cd D:\AAA\RECE
powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1
```

构建工具和依赖下载位置：

```text
D:\AAA\tools\rece-build-venv
D:\AAA\tools\InnoSetup
D:\AAA\tools\pip-cache
D:\AAA\RECE\packaging\vendor\MicrosoftEdgeWebView2Setup.exe
D:\AAA\RECE\packaging\vendor\msmpisetup.exe
```

打包后关键自检：

```powershell
D:\AAA\RECE\dist\RECE\RECE.exe --print-runtime
```

已确认输出为 package mode，`resource_root` 指向 `D:\AAA\RECE\dist\RECE\_internal`，`examples_available` 为 `false`，`reef3d_bin_exists` 和 `divemesh_bin_exists` 为 `true`。

最新验证结果：

- `python -m unittest tests.test_rece -v`：18/18 通过。
- `python -m rece.workflow validate`：`status: ok`，5 帧，单帧期望 `153600` bytes。
- `node automation\run_rece_packaged_runtime_cdp.mjs`：通过，示例入口隐藏、上传入口可见、无外部脚本依赖。
- 使用打包后的 `dist\RECE\RECE.exe --port 8792 --debug` 启动真实 WebView2/服务后，同一 package UI 检查通过。
- `node automation\run_rece_solver_modes_cdp.mjs`：通过。
- `node automation\run_rece_core_matrix_cdp.mjs`：桌面视口 18/18 通过。
- `$env:RECE_CDP_WINDOW_SIZE='390,844'; node automation\run_rece_core_matrix_cdp.mjs`：窄窗口 18/18 通过。

注意：当前全局开发环境仍会提示 SciPy 与 NumPy 2.4.6 的版本警告；安装包构建不再使用该全局环境，而使用 `D:\AAA\tools\rece-build-venv` 中按 `requirements.txt` 安装的 pinned 依赖（NumPy 2.2.6）。

## 0A. Current Dual-Solver Handoff, 2026-06-04

This RECE build now exposes two front-end solver paths without modifying the original `D:\AAA\Celeris-WebGPU`, `D:\AAA\REEF3D`, or `D:\AAA\hk_dtm_example` directories.

- Celeris test path: start `python -m rece.server --host 127.0.0.1 --port 8787`, open `http://127.0.0.1:8787/`, set `Solver Mode` to `Celeris-WebGPU in browser`, select `Ventura Harbor (CA), wind waves`, then click `Run Example Simulation`.
- REEF3D test path: set `Solver Mode` to `REEF3D backend job`, upload either Celeris-style `config.json` plus `bathy.txt` files or a native REEF3D case zip, review MPI/output/wave parameters and optional advanced `control.txt`/`ctrl.txt`, then click `Run Custom REEF3D Job`.
- Custom REEF3D APIs are `POST /api/runs`, `GET /api/runs/{id}/status`, `GET /api/runs/{id}/manifest`, `GET /api/runs/{id}/frames/{name}`, `GET /api/runs/{id}/assets/{name}`, and `POST /api/runs/{id}/cancel`. Invalid numeric run parameters return HTTP 400 instead of being clamped. Run frame endpoints accept either manifest-relative values like `frames/state_000000.bin` or bare filenames like `state_000000.bin`.
- Custom job folders are written to `examples/custom_runs/{run_id}` and logs to `logs/custom_runs/{run_id}`. Only one native REEF3D job runs at a time.
- Validation commands used for this handoff include `python -m unittest tests.test_rece -v`, `python -m rece.workflow validate`, `node automation\run_rece_solver_modes_cdp.mjs`, `node automation\run_rece_smoke_cdp.mjs`, `node automation\run_rece_core_matrix_cdp.mjs`, and `node automation\run_rece_all_examples_cdp.mjs`.

## 0. 2026-06-04 前端重设计与合规交付摘要

本节记录上一轮已经完成的改动，方便下一位 AI 从零接手时快速判断当前状态。

### 0.1 已完成目标

- 按 `D:\AAA\RECE\art\界面风格参考.png` 重设计 RECE 前端，改为深色科研控制台风格。
- 保留所有现有功能入口、按钮、表单控件、DOM `id`、select option value、事件绑定、WebGPU shader/JS 管线和后端 API 契约。
- 将 `D:\AAA\RECE\art\logo.png` 同步为前端可访问资产 `web\assets\hkust-gz-logo.png`，并显示在页面品牌区和底部法律区。
- 更新 RECE、Celeris-WebGPU、REEF3D、DIVEMesh 的许可证和署名说明。
- 新增全示例浏览器自动化脚本，验证 `run_example-select` 中全部预置示例。
- 修复自动化导出检查中固定文件名覆盖导致的误判，并加入移动视口核心矩阵验证能力。

### 0.2 本轮修改文件

主要修改：

- `web\index.html`：替换旧白底 Courier UI 为深色三栏控制台；新增 RECE / HKUST-GZ / MHRF 品牌区、HKUST-GZ logo、底部许可证摘要；保持原功能控件不变。
- `web\js\i18n.js`：调整语言切换条注入样式，避免旧白色语言栏覆盖新深色界面。
- `web\assets\hkust-gz-logo.png`：由 `art\logo.png` 同步而来，供前端直接引用。
- `LICENSE`：根目录许可证设为 GPL-3.0。
- `THIRD_PARTY_NOTICES.md`：新增第三方署名与许可证汇总。
- `README.md`、`README_RECE.md`、`SOURCE_MANIFEST.json`：同步 RECE 署名、第三方权益、分发约束和验证说明。
- `automation\run_rece_core_matrix_cdp.mjs`：修复下载检测逻辑，支持覆盖式下载文件；新增 `RECE_CDP_WINDOW_SIZE` 环境变量用于桌面/移动视口验证。
- `automation\run_rece_all_examples_cdp.mjs`：新增脚本，逐个启动并验证全部预置示例。

没有删除 `web\js`、`shaders`、`examples`、`textures` 等功能资产；本轮只是替换前端视觉 shell 和法律展示。

### 0.3 当前功能契约

前端仍使用原有接口：

```text
GET  /api/health
POST /api/scenarios/hk_victoria_smoke/run
GET  /api/runs/{id}/status
GET  /api/scenarios/hk_victoria_smoke/manifest
GET  /api/scenarios/hk_victoria_smoke/frames/{frame}
```

关键控件仍保留：

- RECE 香港示例仍是 `run_example-select` 的 value `54`。
- 自定义 config、bathy、waves、initial eta、friction、hard bottom 等文件上传入口仍在。
- surface/color map、overlay、2D/3D、箭头、暂停/恢复、render step、time series、JPG/JSON/binary 导出仍按原逻辑工作。
- 语言切换仍可用，且新样式不会改变翻译逻辑。

### 0.4 已完成验证

上一轮已实际跑通：

```powershell
python -m unittest tests.test_rece -v
python -m rece.workflow validate
node --check web\js\ExternalFramePlayer.js
node --check web\js\display_parameters.js
node --check web\js\main.js
node --check web\js\i18n.js
node --check automation\run_rece_smoke_cdp.mjs
node --check automation\run_rece_core_matrix_cdp.mjs
node --check automation\run_rece_all_examples_cdp.mjs
node automation\run_rece_smoke_cdp.mjs
node automation\run_rece_core_matrix_cdp.mjs
node automation\run_rece_all_examples_cdp.mjs
$env:RECE_CDP_WINDOW_SIZE='390,844'; node automation\run_rece_core_matrix_cdp.mjs; Remove-Item Env:\RECE_CDP_WINDOW_SIZE
```

验证结果：

- Python 单元测试：13/13 通过。
- `python -m rece.workflow validate`：`status: ok`，5 帧，单帧 `153600` bytes。
- core matrix：18/18 通过，覆盖外部 REEF3D 帧、内部物理控件禁用、overlay、surface/color map、箭头、2D/3D、暂停/恢复、render step、time series、JPG/JSON/binary 导出。
- all examples：42/42 个预置示例通过。
- 桌面截图和 390px 移动视口截图均确认非空、布局可读、canvas 正常渲染。

报告位置：

```text
D:\AAA\RECE\examples\hk_victoria_smoke\screenshots\core_matrix\rece_core_matrix_report.json
D:\AAA\RECE\examples\hk_victoria_smoke\screenshots\all_examples\rece_all_examples_report.json
```

备注：Browser 插件后端本轮探测为空，无法使用 in-app Browser 接管页面；已用现有 CDP 自动化完成等价的浏览器渲染、点击、下载、console 和截图验证。

### 0.5 接手注意

- RECE 组合包包含并调度 REEF3D/DIVEMesh 的 GPL 组件，因此对外分发包含这些组件的组合包时应保留 GPL-3.0 权利、许可证文本、无担保声明，并提供对应源码。
- 如果继续改前端，请优先保持现有 DOM `id` 和控件 value 不变；自动化脚本依赖这些契约。
- 如果修改下载逻辑或示例加载逻辑，必须重跑 `run_rece_core_matrix_cdp.mjs` 和 `run_rece_all_examples_cdp.mjs`。
- 当前 Python 环境会出现 SciPy 对 NumPy 2.4.6 的版本警告，但测试和 workflow 已通过；重建环境时建议按 `environment.yml` 使用 `numpy<2.3`。

## 1. 项目背景

RECE 是本机新建的拼接项目，目标是把两个已经部署好的项目接成一个可运行的端到端流程：

- `D:\AAA\Celeris-WebGPU`：原始 Celeris-WebGPU 项目，负责 WebGPU 可视化、纹理管线、时间显示、统计和导出。
- `D:\AAA\REEF3D`：原始 REEF3D 和 DIVEMesh 项目，负责水动力求解和网格生成。
- `D:\AAA\hk_dtm_example`：香港示例数据目录，只允许读取，不复制原始大数据。
- `D:\AAA\RECE`：本项目目录，所有新增代码、临时文件、输出、日志、README 和自动化脚本都必须放在这里。

RECE 的核心设计是：REEF3D/DIVEMesh 作为唯一流体求解器，Celeris-WebGPU 不再推进自己的流体方程，只播放 REEF3D 后端生成并转换好的外部帧，然后继续使用 Celeris 的 WebGPU 渲染和导出管线。

## 1.1 许可证、署名与分发约束

RECE 新增集成代码署名为：

```text
香港科技大学（广州） / HKUST-GZ
MHRF / Marine Hydrodynamic Research Facility
2026
```

本项目按 GPL-3.0 开源组合处理。依据本地源码许可证：

- Celeris-WebGPU：MIT License，Copyright (c) 2023 plynett，项目由 Patrick Lynett 维护，并保留原始 Celeris、USACE ERDC、ONR、NSF 等鸣谢。
- REEF3D：GPL-3.0-or-later，Copyright 2008-2026 Hans Bihs。
- DIVEMesh：GPL-3.0-or-later，Copyright 2008-2026 Hans Bihs。

由于 RECE 包含并调度 REEF3D/DIVEMesh 的 GPL 组件，向外分发包含这些组件的 RECE 组合包时，需要保留 GPL-3.0 权利、许可证文本、无担保声明，并提供相应源码。根目录 `LICENSE` 为 GPL-3.0，第三方署名汇总在 `THIRD_PARTY_NOTICES.md`。

## 2. 硬性路径约束

所有项目相关写入都必须在：

```text
D:\AAA\RECE
```

原始项目只读：

```text
D:\AAA\Celeris-WebGPU
D:\AAA\REEF3D
```

香港原始数据只读：

```text
D:\AAA\hk_dtm_example
```

唯一例外：如果后续需要新建 Conda 环境，可以放在 Conda 默认环境目录。

来源、复制范围、排除项、哈希和未改原项目原因记录在：

```text
D:\AAA\RECE\SOURCE_MANIFEST.json
```

## 3. 项目目录结构

```text
D:\AAA\RECE
├─ README.md
├─ README_RECE.md
├─ SOURCE_MANIFEST.json
├─ requirements.txt
├─ environment.yml
├─ rece\
│  ├─ __init__.py
│  ├─ paths.py
│  ├─ hk_prepare.py
│  ├─ converter.py
│  ├─ workflow.py
│  └─ server.py
├─ web\
│  ├─ index.html
│  ├─ js\
│  │  ├─ main.js
│  │  ├─ ExternalFramePlayer.js
│  │  ├─ display_parameters.js
│  │  ├─ constants_load_calc.js
│  │  └─ ...
│  └─ examples\
│     └─ hk_victoria_smoke\
│        ├─ config.json
│        ├─ bathy.txt
│        ├─ waves.txt
│        ├─ overlay.jpg
│        └─ frames_manifest.json
├─ third_party\
│  └─ REEF3D\
│     ├─ bin\
│     │  ├─ DiveMESH.exe
│     │  └─ reef3d.exe
│     ├─ src\
│     ├─ docs\
│     └─ simulations\
├─ examples\
│  └─ hk_victoria_smoke\
│     ├─ bathy.txt
│     ├─ prepare_manifest.json
│     ├─ validation_report.json
│     ├─ workflow_summary.json
│     ├─ frames_manifest.json
│     ├─ frames\
│     ├─ reef3d_case\
│     └─ screenshots\
├─ tests\
│  ├─ __init__.py
│  └─ test_rece.py
├─ automation\
│  ├─ run_rece_smoke_cdp.mjs
│  └─ run_rece_core_matrix_cdp.mjs
├─ logs\
└─ tmp\
```

## 4. Python 后端代码说明

### `rece/paths.py`

负责路径守卫。

- 所有写入路径必须解析到 `D:\AAA\RECE` 下。
- 读取允许来自 `D:\AAA\RECE` 和 `D:\AAA\hk_dtm_example`。
- 防止脚本误写到 AAA 外部或覆盖原始项目。

后续新增脚本应优先复用这里的路径检查。

### `rece/hk_prepare.py`

负责香港烟测场景预处理。

主要功能：

- 读取 `D:\AAA\hk_dtm_example` 中已有的香港派生地形。
- 生成 120x80、50m 分辨率的小网格。
- 生成 Celeris 可读的 `bathy.txt`。
- 生成 DIVEMesh/REEF3D 输入目录 `reef3d_case`。
- 生成前端示例目录 `web\examples\hk_victoria_smoke`。
- 生成 `overlay.jpg`，用于香港地形视觉底图。
- 生成 `config.json`，启用 `externalSolver: "reef3d"`。

重要默认值：

- 网格：`120 x 80`
- 分辨率：`dx = dy = 50m`
- 海平面：`0m`
- REEF3D 波浪：0.4m 波高、10s 周期
- 输出帧：约 1s 间隔
- `ShowLogos: 1`，表示关闭 Celeris 原始 USACE/USC logo。注意 Celeris 原始枚举里 `0 = Yes`，`1 = No`。

### `rece/converter.py`

负责把 REEF3D 输出转换为 Celeris-WebGPU 可播放帧。

输入：

```text
examples\hk_victoria_smoke\reef3d_case\REEF3D_NHFLOW_VTP_FSF\*.pvtp
```

输出：

```text
examples\hk_victoria_smoke\frames\state_000000.bin
examples\hk_victoria_smoke\frames\velocity_000000.bin
examples\hk_victoria_smoke\frames_manifest.json
```

帧格式：

```text
little-endian Float32 RGBA
row-major
无额外 padding
```

状态帧：

```text
state = [eta, hu, hv, foam]
```

速度帧：

```text
velocity = [u, v, eta, depth]
```

其中：

- `eta`：自由液面高程
- `u, v`：水平速度
- `depth`：水深
- `hu = depth * u`
- `hv = depth * v`
- `foam`：当前外部帧模式中为占位值

### `rece/workflow.py`

命令行入口，负责串联完整流程。

常用命令：

```powershell
cd D:\AAA\RECE
python -m rece.workflow env
python -m rece.workflow prepare
python -m rece.workflow divemesh
python -m rece.workflow reef3d --mpi-ranks 4
python -m rece.workflow convert
python -m rece.workflow validate
python -m rece.workflow run --scenario hk_victoria_smoke --mpi-ranks 4
```

完整 `run` 顺序：

```text
env -> prepare -> divemesh -> reef3d -> convert -> validate
```

### `rece/server.py`

本地 HTTP 服务入口。

启动：

```powershell
cd D:\AAA\RECE
python -m rece.server --host 127.0.0.1 --port 8787
```

作用：

- 提供 `web\` 静态页面。
- 提供 RECE API。
- 调度 workflow。
- 提供转换后的帧 manifest 和二进制帧文件。
- 静态文件只允许从 `web\` 读取，帧文件只允许从 `examples\hk_victoria_smoke\frames\` 读取；路径穿越请求会返回 404。

浏览器不能直接运行 `.exe` 或 `mpiexec`，所以必须由 Python 后端启动：

```text
DiveMESH.exe
mpiexec -n 4 reef3d.exe
```

## 5. Web 前端拼接说明

前端目录：

```text
D:\AAA\RECE\web
```

这是从 Celeris-WebGPU 复制来的副本，原项目不修改。

### `web\examples\hk_victoria_smoke\config.json`

关键字段：

```json
{
  "externalSolver": "reef3d",
  "externalFrameManifest": "/api/scenarios/hk_victoria_smoke/manifest",
  "externalFrameStride": 1,
  "ShowLogos": 1,
  "GoogleMapOverlay": 2
}
```

含义：

- `externalSolver: "reef3d"`：启用 RECE 外部求解器模式。
- `externalFrameManifest`：从后端 API 读取 REEF3D 帧 manifest。
- `externalFrameStride`：播放帧步长。
- `ShowLogos: 1`：关闭 USACE/USC logo，避免遮挡模拟结果。
- `GoogleMapOverlay: 2`：使用本地 `overlay.jpg` 作为地形底图。

### `web\js\ExternalFramePlayer.js`

新增文件，负责外部帧播放。

主要功能：

- 读取 `/api/scenarios/hk_victoria_smoke/manifest`。
- 拉取 `state_*.bin` 和 `velocity_*.bin`。
- 对 WebGPU row alignment 做上传前 padding。
- 上传到 Celeris 原有纹理：
  - `txNewState`
  - `txModelVelocities`
  - `txH`
  - `txU`
  - `txV`
- 让后续 Celeris 渲染、统计、导出路径继续工作。

### `web\js\main.js`

主要拼接点。

RECE 修改点：

- import `ExternalFramePlayer.js`。
- 检测 `externalSolver: "reef3d"`。
- 外部模式下设置：
  - `render_step = externalFrameStride`
  - `useBreakingModel = 0`
  - `useSedTransModel = 0`
  - `ShowLogos = 1`
- 创建 `externalFramePlayer`。
- 在主循环中上传下一帧 REEF3D 结果。
- 跳过 Celeris 的流体推进 pass：
  - Pass0
  - Pass1
  - Pass2
  - Pass3
  - Boundary
  - Tridiag
  - Breaking
  - SedTrans
- 保留 Celeris 的渲染、统计、时间序列和导出逻辑。
- 外部帧模式下禁用内部求解器物理控件，包括 NLSW/Boussinesq、Courant、Theta、破碎、输沙、摩擦、海平面直接改动和扰动按钮，避免误以为这些控件会修改已生成的 REEF3D 帧。
- 添加 RECE workflow 按钮，调用后端 API 重新运行完整流程。

### `web\js\display_parameters.js`

负责页面参数和状态文字显示。

本次修复了顶部状态栏闪烁问题。原逻辑每一帧都会：

```text
清空 simstatus-container -> 新建整行 p 标签 -> 居中显示
```

由于 `Faster-than-Realtime Ratio` 数字长度变化，整行宽度变化，居中位置也变化，所以肉眼看起来一直闪烁。

当前逻辑改为：

- 第一次创建固定结构的 span。
- 后续只更新：
  - simulation type
  - simulated time
  - faster-than-realtime ratio
- 不再每帧重建 DOM。

### `web\index.html`

RECE 修改点：

- 重设计为参考图风格的深色科研控制台界面。
- 新增 RECE / HKUST-GZ / MHRF 品牌区，并显示 `art\logo.png` 同步到前端后的 HKUST-GZ 标志。
- 新增 RECE workflow 按钮。
- 新增 RECE Hong Kong smoke 示例选项。
- 保留所有 Celeris/RECE 表单控件、按钮、DOM `id`、选项值和事件绑定。
- 前端底部显示 RECE 2026 署名、Celeris-WebGPU MIT、REEF3D/DIVEMesh GPL-3.0-or-later 权益声明。
- 给 `#simstatus-container` 增加固定 grid 列宽。

状态栏 CSS 关键点：

```css
#simstatus-container {
    display: grid;
    grid-template-columns: 24ch 2ch 24ch 7ch 2ch 32ch 8ch;
    justify-content: center;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
```

这样固定文本和数值列都有稳定位置，只有数值内容更新，不会再随着字符串长度左右抖动。

### `web\js\constants_load_calc.js`

RECE 修改点：

- 把 `./examples/hk_victoria_smoke/` 注册到 Celeris 示例目录数组。
- RECE 示例编号为 `54`。
- 加了配置加载日志，便于确认浏览器加载的是 RECE 示例而不是其他示例。

## 6. 香港烟测数据说明

源数据目录：

```text
D:\AAA\hk_dtm_example
```

本项目当前使用的是其中已有的香港 Victoria Harbour 派生小样例：

```text
D:\AAA\hk_dtm_example\celeris_hk_demo\hk_victoria_demo_bathy.txt
```

该文件是从香港陆地和海底数据处理来的派生地形，RECE 只读取，不复制原始大数据。

生成结果：

```text
D:\AAA\RECE\examples\hk_victoria_smoke\bathy.txt
D:\AAA\RECE\web\examples\hk_victoria_smoke\bathy.txt
D:\AAA\RECE\web\examples\hk_victoria_smoke\overlay.jpg
```

地形语义沿用 Celeris：

- 负值：海底低于海平面
- 正值：陆地高程
- 海平面：`0m`

## 7. REEF3D/DIVEMesh 工作目录

香港烟测 REEF3D case：

```text
D:\AAA\RECE\examples\hk_victoria_smoke\reef3d_case
```

关键输入：

```text
control.txt
ctrl.txt
geo.dat
```

关键输出：

```text
REEF3D_NHFLOW_VTP_FSF\
REEF3D_NHFLOW_VTP_BED\
```

自由液面 `.pvtp` 是当前转换的主要输入。

## 8. 后端 API

服务地址：

```text
http://127.0.0.1:8787/
```

API：

```text
GET  /api/health
POST /api/scenarios/hk_victoria_smoke/run
GET  /api/runs/{run_id}/status
GET  /api/scenarios/hk_victoria_smoke/manifest
GET  /api/scenarios/hk_victoria_smoke/frames/{frame_file}
```

健康检查示例：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/health
```

预期：

```json
{
  "status": "ok",
  "scenario": "hk_victoria_smoke"
}
```

## 9. 如何运行

### 9.1 启动服务

```powershell
cd D:\AAA\RECE
python -m rece.server --host 127.0.0.1 --port 8787
```

### 9.2 打开页面

```text
http://127.0.0.1:8787/
```

选择：

```text
RECE Hong Kong smoke (REEF3D external frames)
```

然后点击运行示例。

### 9.3 重新跑完整 workflow

```powershell
cd D:\AAA\RECE
python -m rece.workflow run --scenario hk_victoria_smoke --mpi-ranks 4
```

### 9.4 只校验已有帧

```powershell
cd D:\AAA\RECE
python -m rece.workflow validate
```

## 10. 测试与验证

### 10.1 Python 单元测试

```powershell
cd D:\AAA\RECE
python -m unittest tests.test_rece -v
```

覆盖内容：

- 写入路径必须留在 RECE 内。
- 原始数据读取路径允许。
- 香港烟测预处理核心文件生成。
- 香港 DTM tile 选择为空时必须明确失败。
- zip 解压和下载缓存路径必须留在 RECE 内。
- 服务端静态文件和帧文件路径穿越必须被拒绝。
- 非 HK 转换测试不再污染 `web\examples`。
- 用复制来的 REEF3D Meander 输出测试 `.pvtp` 转换。

### 10.2 JS 语法检查

```powershell
node --check web\js\ExternalFramePlayer.js
node --check web\js\display_parameters.js
node --check web\js\main.js
node --check web\js\i18n.js
node --check automation\run_rece_smoke_cdp.mjs
node --check automation\run_rece_core_matrix_cdp.mjs
node --check automation\run_rece_all_examples_cdp.mjs
```

### 10.3 浏览器自动化验证

```powershell
node automation\run_rece_smoke_cdp.mjs
node automation\run_rece_core_matrix_cdp.mjs
node automation\run_rece_all_examples_cdp.mjs
```

这些脚本会自动检查 `http://127.0.0.1:8787/api/health`；如果本地 RECE server 没有启动，会临时启动并在结束时关闭。

smoke 脚本会：

- 启动 Chrome/Edge。
- 打开 `http://127.0.0.1:8787/`。
- 自动选择 RECE 香港示例。
- 启动 WebGPU 模拟。
- 检查 REEF3D external manifest 是否加载。
- 检查外部求解器模式是否激活。
- 截取 WebGPU canvas。
- 写出报告。

core matrix 脚本会额外验证：

- 外部 REEF3D 模式下内部求解器物理控件被禁用。
- overlay、渲染模式、2D/3D 视角、箭头、暂停/恢复、render step 和时间序列控件仍可工作。
- JPG、JSON config 和单帧二进制导出文件非空。

all examples 脚本会额外验证：

- 遍历 `run_example-select` 中全部预置示例。
- 逐个启动示例并等待 WebGPU canvas 和状态栏进入有效状态。
- 检查阻塞级 console error / runtime exception。
- 对失败示例保存截图并写入报告。

报告：

```text
D:\AAA\RECE\examples\hk_victoria_smoke\screenshots\rece_cdp_report.json
D:\AAA\RECE\examples\hk_victoria_smoke\screenshots\core_matrix\rece_core_matrix_report.json
D:\AAA\RECE\examples\hk_victoria_smoke\screenshots\all_examples\rece_all_examples_report.json
```

截图：

```text
D:\AAA\RECE\examples\hk_victoria_smoke\screenshots\rece_hk_external_frames.png
D:\AAA\RECE\examples\hk_victoria_smoke\screenshots\core_matrix\
```

如果要保留浏览器窗口给人工查看：

```powershell
$env:RECE_KEEP_BROWSER='1'
node automation\run_rece_smoke_cdp.mjs
node automation\run_rece_core_matrix_cdp.mjs
```

## 11. 当前已验证结果

已经跑通：

```powershell
python -m rece.workflow run --scenario hk_victoria_smoke --mpi-ranks 4
```

结果：

- REEF3D 自由液面输出：5 帧。
- 转换后的 Celeris state/velocity 帧：5 帧。
- 网格：`120 x 80`
- 单帧字节数：`153600`
- `validation_report.json` 显示 `status: ok`。

已通过：

```powershell
python -m unittest tests.test_rece -v
python -m rece.workflow validate
node --check web\js\ExternalFramePlayer.js
node --check web\js\display_parameters.js
node --check web\js\main.js
node --check web\js\i18n.js
node --check automation\run_rece_smoke_cdp.mjs
node --check automation\run_rece_core_matrix_cdp.mjs
node --check automation\run_rece_all_examples_cdp.mjs
node automation\run_rece_smoke_cdp.mjs
node automation\run_rece_core_matrix_cdp.mjs
node automation\run_rece_all_examples_cdp.mjs
$env:RECE_CDP_WINDOW_SIZE='390,844'; node automation\run_rece_core_matrix_cdp.mjs; Remove-Item Env:\RECE_CDP_WINDOW_SIZE
```

最近一次结果：

- Python 单元测试：13/13 通过。
- workflow validate：`status: ok`，5 帧。
- core matrix：桌面视口 18/18 通过。
- core matrix：`390,844` 移动视口 18/18 通过。
- all examples：42/42 个预置示例通过。

说明：当前 Python 环境 NumPy 为 `2.4.6`，SciPy 为 `1.14.1`，SciPy 会提示建议 NumPy `<2.3.0`。测试和 workflow 已实际跑通；如果后续重建环境，建议按 `environment.yml` 使用 `numpy<2.3`。

## 12. 本次 UI 问题修复记录

### 12.1 USACE/USC logo 遮挡模拟结果

现象：

- 页面上方出现 USC 学校 logo。
- logo 和香港海面模拟结果重叠。
- logo 尺寸过大，影响查看。

原因：

- Celeris 原始 UI 有 `Show USACE & USC logos` 功能。
- 原始枚举比较反直觉：`ShowLogos == 0` 表示显示，`ShowLogos == 1` 表示不显示。
- RECE HK 配置之前没有显式设置该字段，回落到默认值 `0`，所以 logo 被绘制到 `txDraw` 叠加纹理里。

修复：

- 在 `rece/hk_prepare.py` 中写入：

```json
"ShowLogos": 1
```

- 在 `web\js\main.js` 的 `externalSolver: "reef3d"` 分支中兜底设置：

```javascript
calc_constants.ShowLogos = 1;
```

结果：

- RECE 外部 REEF3D 帧模式默认不显示 USACE/USC logo。
- 香港 overlay 仍保留。
- 模拟结果不再被学校图标遮挡。

### 12.2 顶部状态栏闪烁

现象：

```text
NLSW Simulation, Simulated Time (min): 0, Faster-than-Realtime Ratio: ...
```

这一行在运行时闪烁。

原因：

- 原代码每帧清空 `simstatus-container`。
- 每帧重新创建多个 `<p>`。
- Faster-than-Realtime 数值长度变化。
- 整行默认居中，字符串总宽度变化导致整行位置左右变化。

修复：

- `web\js\display_parameters.js` 改为固定 DOM 结构。
- 后续只更新模型名、时间、倍率三个字段。
- `web\index.html` 中给 `#simstatus-container` 固定 grid 列宽。
- 数值列右对齐，并启用 `font-variant-numeric: tabular-nums`。

结果：

- 固定文字位置稳定。
- 只有数值内容更新。
- 状态栏不再因为字符串长度变化而闪烁。

### 12.3 前端深色控制台重设计

目标：

- 参考 `D:\AAA\RECE\art\界面风格参考.png`。
- 保留所有功能和交互，只更换视觉外壳。
- 删除旧白底 Courier 风格和旧 Celeris-only 页脚显示。

实现：

- `web\index.html` 改为深色三栏控制台布局。
- 左侧保留所有控制组，使用折叠面板样式。
- 中间保留 WebGPU simulation canvas、状态栏、time series canvas 和常量面板。
- 右侧保留 simulation console。
- 底部新增 RECE / HKUST-GZ / MHRF / 2026 署名和第三方许可证摘要。
- 前端可访问图标为 `web\assets\hkust-gz-logo.png`，来源为 `art\logo.png`。

## 13. 常见问题

### 页面打不开

检查服务：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/health
```

如果失败，重新启动：

```powershell
cd D:\AAA\RECE
python -m rece.server --host 127.0.0.1 --port 8787
```

### 端口被占用

换端口：

```powershell
python -m rece.server --host 127.0.0.1 --port 8788
```

打开：

```text
http://127.0.0.1:8788/
```

### WebGPU 不工作

使用新版 Chrome 或 Edge，并检查：

```text
chrome://gpu
edge://gpu
```

确认硬件加速和 WebGPU 可用。

### REEF3D 不启动

检查：

```text
D:\AAA\RECE\third_party\REEF3D\bin\DiveMESH.exe
D:\AAA\RECE\third_party\REEF3D\bin\reef3d.exe
C:\Program Files\Microsoft MPI\Bin\mpiexec.exe
```

### 前端提示没有帧

先确认：

```text
D:\AAA\RECE\examples\hk_victoria_smoke\frames_manifest.json
D:\AAA\RECE\examples\hk_victoria_smoke\frames\
```

再运行：

```powershell
python -m rece.workflow validate
```

## 14. 后续开发建议

1. 如果要扩大香港区域，先在 `hk_prepare.py` 中增加场景参数，不要直接改原始数据。
2. 如果要支持更多 REEF3D case，给 `workflow.py` 增加 scenario，而不是把 HK 逻辑写死到通用转换器。
3. 如果要做更严格的地理配准，需要把 HK1980、WGS84、海图深度基准和 LiDAR 高程基准单独整理成 `rece/geodesy.py`。
4. 如果要做浏览器内实时求解，不要塞进当前 external frame 模式；当前首版目标是后端预计算、前端播放。
5. 如果要让用户在 UI 中修改地形/摩擦/扰动并影响结果，需要触发后端重新跑 REEF3D，而不是直接改当前已生成帧。
6. 所有新增测试、缓存、截图、日志继续放在 `D:\AAA\RECE` 内。

## 15. 给接手 AI 的最短路线

如果只想快速理解并继续开发，建议按这个顺序阅读：

1. `README_RECE.md`
2. `SOURCE_MANIFEST.json`
3. `THIRD_PARTY_NOTICES.md`
4. `LICENSE`
5. `rece\paths.py`
6. `rece\workflow.py`
7. `rece\hk_prepare.py`
8. `rece\converter.py`
9. `rece\server.py`
10. `web\index.html`
11. `web\js\ExternalFramePlayer.js`
12. `web\js\main.js` 中搜索 `externalSolver`
13. `web\js\display_parameters.js`
14. `web\js\i18n.js`
15. `tests\test_rece.py`
16. `automation\run_rece_smoke_cdp.mjs`
17. `automation\run_rece_core_matrix_cdp.mjs`
18. `automation\run_rece_all_examples_cdp.mjs`
# RECE Custom REEF3D Frontend Integration Update

Last updated: 2026-06-04

This section records the current RECE handoff state after adding full custom REEF3D frontend interaction.

## What Changed

- Added a backend custom job layer in `rece/custom_case.py` and `rece/jobs.py`.
- Added `POST /api/runs`, `GET /api/runs/{id}/status`, `GET /api/runs/{id}/manifest`, `GET /api/runs/{id}/frames/{name}`, `GET /api/runs/{id}/assets/{name}`, and `POST /api/runs/{id}/cancel`.
- Added front-end solver selection: `Celeris-WebGPU in browser` and `REEF3D backend job`.
- Added custom REEF3D input modes:
  - Celeris-style uploads: `config.json`, `bathy.txt`, optional `waves.txt`, optional overlay.
  - Native REEF3D case zip: must include `geo.dat`, `control.txt`, `ctrl.txt`, `bathy.txt`, and either `config.json` or `rece_metadata.json`.
- Added REEF3D common controls for MPI ranks, wave height, wave period, wave direction, output frames, and output interval.
- Added advanced text overrides for `control.txt` and `ctrl.txt`.
- Extended `ExternalFramePlayer` so an incomplete manifest can grow while REEF3D is running; it holds the latest frame until new frames appear, then loops only after `complete: true`.
- Added `automation/run_rece_solver_modes_cdp.mjs` for solver-mode smoke checks.
- Preserved the legacy Hong Kong smoke workflow and option value `54`.

## How To Run Both Solver Test Projects

### Celeris-WebGPU Solver Test

```powershell
cd D:\AAA\RECE
python -m rece.server --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787/`, set `Solver Mode` to `Celeris-WebGPU in browser`, choose `Ventura Harbor (CA), wind waves`, then click `Run Example Simulation`.

### REEF3D Solver Test

Start the same server, open the same URL, set `Solver Mode` to `REEF3D backend job`, then choose one of:

- `Use uploaded Celeris config/bathy/waves`: upload `config.json` and `bathy.txt`, optional `waves.txt` and overlay, adjust REEF3D controls, then click `Run Custom REEF3D Job`.
- `Use native REEF3D case zip`: upload a zip containing `geo.dat`, `control.txt`, `ctrl.txt`, `bathy.txt`, and `config.json` or `rece_metadata.json`, then click `Run Custom REEF3D Job`.

The backend writes custom jobs to `examples/custom_runs/{run_id}` and logs to `logs/custom_runs/{run_id}`. Only one custom REEF3D job runs at a time. As stable REEF3D free-surface frames appear, RECE converts them to Celeris external frame binaries and the front end starts live playback.

## Validation Run

Current validation commands:

```powershell
cd D:\AAA\RECE
python -m unittest tests.test_rece -v
python -m rece.workflow validate
node --check web\js\ExternalFramePlayer.js
node --check web\js\display_parameters.js
node --check web\js\main.js
node --check web\js\i18n.js
node --check automation\run_rece_solver_modes_cdp.mjs
```

`environment.yml` and `requirements.txt` pin `numpy<2.3`; use those pins when rebuilding the environment to avoid the current SciPy/NumPy warning.
