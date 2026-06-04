async function readRuntimeInfo() {
    try {
        const response = await fetch('/api/runtime', { cache: 'no-store' });
        if (!response.ok) {
            return null;
        }
        return response.json();
    } catch {
        return null;
    }
}

function hideElement(id) {
    const element = document.getElementById(id);
    if (element) {
        element.classList.add('rece-package-hidden');
        element.setAttribute('aria-hidden', 'true');
    }
}

function applyPackageMode() {
    document.body.dataset.receRuntimeMode = 'package';
    hideElement('rece-workflow-panel');
    hideElement('rece-example-panel');
    const runExampleButton = document.getElementById('run-example-simulation-btn');
    if (runExampleButton) {
        runExampleButton.disabled = true;
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    const info = await readRuntimeInfo();
    window.RECE_RUNTIME_INFO = info || {};
    if (info?.package_mode) {
        applyPackageMode();
    }
});
