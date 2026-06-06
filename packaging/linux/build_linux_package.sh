#!/usr/bin/env bash
set -euo pipefail

APP_VERSION="0.1.0+linux1"
DEB_VERSION="0.1.0+linux1"
ARCH="amd64"
TARBALL_NAME="RECE-linux-x86_64.tar.gz"
DEB_NAME="rece_${DEB_VERSION}_${ARCH}.deb"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_ROOT="${ROOT}/build/linux-package"
RESOURCES="${BUILD_ROOT}/resources"
SOURCE_STAGE="${BUILD_ROOT}/source_stage"
DIST_ROOT="${ROOT}/dist/linux"
PYINSTALLER_DIST="${DIST_ROOT}/pyinstaller"
APP_DIST="${DIST_ROOT}/RECE-linux-x86_64"
DEB_ROOT="${BUILD_ROOT}/deb"
SOLVER_BUILD="${ROOT}/build/reef3d-linux"
SOLVER_BIN_DIR="${ROOT}/third_party/REEF3D/bin/linux-x86_64"
PYTHON_BIN="${RECE_LINUX_PYTHON:-python3}"

assert_under_root() {
  local target
  target="$(realpath -m "$1")"
  case "${target}" in
    "${ROOT}"/*) ;;
    *) echo "Refusing to touch path outside repo: ${target}" >&2; exit 1 ;;
  esac
}

reset_dir() {
  assert_under_root "$1"
  rm -rf "$1"
  mkdir -p "$1"
}

copy_dir() {
  local src="$1"
  local dst="$2"
  if [[ ! -d "${src}" ]]; then
    echo "Missing required directory: ${src}" >&2
    exit 1
  fi
  mkdir -p "${dst}"
  cp -a "${src}/." "${dst}/"
}

copy_file() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "${src}" ]]; then
    echo "Missing required file: ${src}" >&2
    exit 1
  fi
  mkdir -p "${dst}"
  cp -a "${src}" "${dst}/"
}

write_sha256() {
  local path="$1"
  (cd "$(dirname "${path}")" && sha256sum "$(basename "${path}")" > "$(basename "${path}").sha256")
}

build_solvers() {
  mkdir -p "${SOLVER_BIN_DIR}"
  cmake -S "${ROOT}/third_party/REEF3D/src/REEF3D" \
    -B "${SOLVER_BUILD}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DHYPRE_ROOT="${HYPRE_ROOT:-/usr}"
  cmake --build "${SOLVER_BUILD}" --config Release --parallel "$(nproc)"
  test -x "${SOLVER_BIN_DIR}/reef3d"
  test -x "${SOLVER_BIN_DIR}/DiveMESH"
}

stage_runtime_resources() {
  reset_dir "${BUILD_ROOT}"
  mkdir -p "${RESOURCES}/web" "${RESOURCES}/third_party/REEF3D/bin/linux-x86_64" "${RESOURCES}/licenses" "${RESOURCES}/source"

  for file in index.html favicon.ico models.json no_waves.txt logo_publicex_river.png logo_USACE.png logo_USC.png logo_USC_river.png; do
    if [[ -f "${ROOT}/web/${file}" ]]; then
      copy_file "${ROOT}/web/${file}" "${RESOURCES}/web"
    fi
  done
  for dir in assets externals js shaders skybox textures; do
    copy_dir "${ROOT}/web/${dir}" "${RESOURCES}/web/${dir}"
  done

  copy_file "${SOLVER_BIN_DIR}/reef3d" "${RESOURCES}/third_party/REEF3D/bin/linux-x86_64"
  copy_file "${SOLVER_BIN_DIR}/DiveMESH" "${RESOURCES}/third_party/REEF3D/bin/linux-x86_64"

  for file in AGENTS.md LICENSE THIRD_PARTY_NOTICES.md SOURCE_MANIFEST.json README.md README_RECE.md requirements.txt environment.yml; do
    copy_file "${ROOT}/${file}" "${RESOURCES}/licenses"
  done
}

create_source_archive() {
  reset_dir "${SOURCE_STAGE}"
  "${PYTHON_BIN}" - "${ROOT}" "${SOURCE_STAGE}" "${RESOURCES}/source/RECE_corresponding_source.zip" <<'PY'
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
stage = Path(sys.argv[2]).resolve()
archive = Path(sys.argv[3]).resolve()

files = ["AGENTS.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "SOURCE_MANIFEST.json", "README.md", "README_RECE.md", "requirements.txt", "environment.yml"]
dirs = ["art", "rece", "tests", "automation", "packaging"]
web_files = ["index.html", "favicon.ico", "models.json", "no_waves.txt", "README.md", "LICENSE"]
web_dirs = ["assets", "externals", "js", "shaders", "skybox", "textures"]

for file_name in files:
    shutil.copy2(root / file_name, stage / file_name)
for dir_name in dirs:
    shutil.copytree(root / dir_name, stage / dir_name)

web_stage = stage / "web"
web_stage.mkdir(parents=True, exist_ok=True)
for file_name in web_files:
    src = root / "web" / file_name
    if src.exists():
        shutil.copy2(src, web_stage / file_name)
for dir_name in web_dirs:
    shutil.copytree(root / "web" / dir_name, web_stage / dir_name)

shutil.copytree(root / "third_party" / "REEF3D" / "src", stage / "third_party" / "REEF3D" / "src")
shutil.copytree(root / "third_party" / "REEF3D" / "docs", stage / "third_party" / "REEF3D" / "docs")

skip_dirs = {".git", "__pycache__", "vendor"}
archive.parent.mkdir(parents=True, exist_ok=True)
if archive.exists():
    archive.unlink()
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for path in sorted(stage.rglob("*")):
        rel = path.relative_to(stage)
        parts = set(rel.parts)
        if path.is_dir() or parts & skip_dirs:
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        zf.write(path, rel.as_posix())
PY
}

build_pyinstaller_app() {
  rm -rf "${PYINSTALLER_DIST}" "${APP_DIST}" "${ROOT}/build/pyinstaller-linux"
  mkdir -p "${DIST_ROOT}"
  PYTHONUTF8=1 "${PYTHON_BIN}" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "${PYINSTALLER_DIST}" \
    --workpath "${ROOT}/build/pyinstaller-linux" \
    "${ROOT}/packaging/linux/rece_linux_pyinstaller.spec"
  mv "${PYINSTALLER_DIST}/RECE" "${APP_DIST}"
  ln -sfn RECE "${APP_DIST}/rece"
  cp -a "${ROOT}/packaging/linux/install-deps.sh" "${APP_DIST}/install-deps.sh"
  chmod +x "${APP_DIST}/RECE" "${APP_DIST}/install-deps.sh"
  cp -a "${ROOT}/packaging/linux/rece.desktop" "${APP_DIST}/rece.desktop"
  sed -i "s#Exec=/usr/bin/rece#Exec=${APP_DIST}/rece#g" "${APP_DIST}/rece.desktop"
  sed -i "s#Icon=rece#Icon=${APP_DIST}/_internal/web/assets/rece-app-icon.png#g" "${APP_DIST}/rece.desktop"
}

build_tarball() {
  rm -f "${DIST_ROOT}/${TARBALL_NAME}" "${DIST_ROOT}/${TARBALL_NAME}.sha256"
  (cd "${DIST_ROOT}" && tar -czf "${TARBALL_NAME}" "RECE-linux-x86_64")
  write_sha256 "${DIST_ROOT}/${TARBALL_NAME}"
}

build_deb() {
  reset_dir "${DEB_ROOT}"
  mkdir -p \
    "${DEB_ROOT}/DEBIAN" \
    "${DEB_ROOT}/opt" \
    "${DEB_ROOT}/usr/bin" \
    "${DEB_ROOT}/usr/share/applications" \
    "${DEB_ROOT}/usr/share/icons/hicolor/256x256/apps"

  cp -a "${APP_DIST}" "${DEB_ROOT}/opt/rece"
  rm -f "${DEB_ROOT}/opt/rece/rece.desktop"
  cat > "${DEB_ROOT}/DEBIAN/control" <<EOF
Package: rece
Version: ${DEB_VERSION}
Section: science
Priority: optional
Architecture: ${ARCH}
Maintainer: HKUST-GZ / MHRF <rece@example.invalid>
Depends: gir1.2-gtk-3.0, gir1.2-webkit2-4.1, libgtk-3-0, libwebkit2gtk-4.1-0, openmpi-bin, libopenmpi-dev, libhypre-dev
Description: RECE ocean fluid simulation interface
 RECE integrates Celeris-WebGPU, REEF3D, DIVEMesh, and a local Python bridge service.
EOF

  cat > "${DEB_ROOT}/usr/bin/rece" <<'EOF'
#!/usr/bin/env sh
exec /opt/rece/RECE "$@"
EOF
  chmod 0755 "${DEB_ROOT}/usr/bin/rece"
  cp -a "${ROOT}/packaging/linux/rece.desktop" "${DEB_ROOT}/usr/share/applications/rece.desktop"
  cp -a "${ROOT}/web/assets/rece-app-icon.png" "${DEB_ROOT}/usr/share/icons/hicolor/256x256/apps/rece.png"
  chmod -R go-w "${DEB_ROOT}"
  rm -f "${DIST_ROOT}/${DEB_NAME}" "${DIST_ROOT}/${DEB_NAME}.sha256"
  dpkg-deb --build --root-owner-group "${DEB_ROOT}" "${DIST_ROOT}/${DEB_NAME}"
  write_sha256 "${DIST_ROOT}/${DEB_NAME}"
}

main() {
  command -v cmake >/dev/null
  command -v dpkg-deb >/dev/null
  "${PYTHON_BIN}" -m PyInstaller --version >/dev/null
  build_solvers
  stage_runtime_resources
  create_source_archive
  build_pyinstaller_app
  "${APP_DIST}/RECE" --print-runtime
  build_tarball
  build_deb
  echo "Linux application: ${APP_DIST}"
  echo "Portable tarball:  ${DIST_ROOT}/${TARBALL_NAME}"
  echo "Debian package:    ${DIST_ROOT}/${DEB_NAME}"
}

main "$@"
