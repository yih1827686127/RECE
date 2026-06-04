function requiredBytesPerRow(width) {
    return Math.ceil(width * 16 / 256) * 256;
}

function paddedTextureBytes(floatData, width, height) {
    const actualBytesPerRow = width * 16;
    const bytesPerRow = requiredBytesPerRow(width);
    const source = new Uint8Array(floatData.buffer, floatData.byteOffset, floatData.byteLength);
    if (actualBytesPerRow === bytesPerRow) {
        return { bytes: source, bytesPerRow };
    }
    const padded = new Uint8Array(height * bytesPerRow);
    for (let y = 0; y < height; y++) {
        const srcStart = y * actualBytesPerRow;
        const dstStart = y * bytesPerRow;
        padded.set(source.subarray(srcStart, srcStart + actualBytesPerRow), dstStart);
    }
    return { bytes: padded, bytesPerRow };
}

function uploadRgba32Float(device, texture, floatData, width, height) {
    const { bytes, bytesPerRow } = paddedTextureBytes(floatData, width, height);
    const buffer = device.createBuffer({
        size: bytes.byteLength,
        usage: GPUBufferUsage.COPY_SRC,
        mappedAtCreation: true,
    });
    new Uint8Array(buffer.getMappedRange()).set(bytes);
    buffer.unmap();
    const encoder = device.createCommandEncoder();
    encoder.copyBufferToTexture(
        { buffer, bytesPerRow, rowsPerImage: height },
        { texture },
        { width, height, depthOrArrayLayers: 1 }
    );
    device.queue.submit([encoder.finish()]);
    buffer.destroy();
}

function duplicateChannel(source, channel, width, height) {
    const output = new Float32Array(width * height * 4);
    for (let i = 0; i < width * height; i++) {
        const value = source[i * 4 + channel];
        const offset = i * 4;
        output[offset] = value;
        output[offset + 1] = value;
        output[offset + 2] = value;
        output[offset + 3] = value;
    }
    return output;
}

function resolveFrameUrl(manifestUrl, relativePath) {
    const cleanPath = validateRelativeFramePath(relativePath);
    return new URL(cleanPath, new URL(manifestUrl, window.location.href)).toString();
}

function validateRelativeFramePath(relativePath) {
    if (typeof relativePath !== "string" || relativePath.length === 0) {
        throw new Error("External frame path must be a non-empty relative string.");
    }
    if (relativePath.startsWith("/") || relativePath.includes("\\") || /^[a-z][a-z0-9+.-]*:/i.test(relativePath)) {
        throw new Error(`External frame path is not relative: ${relativePath}`);
    }
    const parts = relativePath.split("/");
    if (parts.some((part) => part === "" || part === "." || part === "..")) {
        throw new Error(`External frame path contains an unsafe segment: ${relativePath}`);
    }
    if (!relativePath.startsWith("frames/")) {
        throw new Error(`External frame path must stay under frames/: ${relativePath}`);
    }
    return relativePath;
}

async function fetchFloatFrame(url, expectedFloats) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
        throw new Error(`Failed to fetch external frame ${url}: HTTP ${response.status}`);
    }
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength !== expectedFloats * 4) {
        throw new Error(`External frame ${url} has ${buffer.byteLength} bytes; expected ${expectedFloats * 4}`);
    }
    return new Float32Array(buffer);
}

class ExternalFramePlayer {
    constructor(calcConstants, device, textures, manifest, manifestUrl) {
        this.calcConstants = calcConstants;
        this.device = device;
        this.textures = textures;
        this.manifest = manifest;
        this.manifestUrl = manifestUrl;
        this.frameIndex = 0;
        this.currentTime = 0.0;
        this.expectedFloats = calcConstants.WIDTH * calcConstants.HEIGHT * 4;
        this.complete = Boolean(manifest.complete);
        this.lastRefresh = 0;
    }

    get frameCount() {
        return this.manifest.frames.length;
    }

    async uploadNextFrame() {
        if (this.frameCount === 0) {
            await this.refreshManifest();
        }
        if (this.frameCount === 0) {
            return false;
        }
        if (this.frameIndex >= this.frameCount) {
            await this.refreshManifest();
            if (this.frameIndex >= this.frameCount) {
                if (this.complete) {
                    this.frameIndex = 0;
                } else {
                    this.frameIndex = Math.max(0, this.frameCount - 1);
                }
            }
        }
        const frame = this.manifest.frames[this.frameIndex];
        const stateUrl = resolveFrameUrl(this.manifestUrl, frame.state);
        const velocityUrl = resolveFrameUrl(this.manifestUrl, frame.velocity);
        const [state, velocity] = await Promise.all([
            fetchFloatFrame(stateUrl, this.expectedFloats),
            fetchFloatFrame(velocityUrl, this.expectedFloats),
        ]);

        const width = this.calcConstants.WIDTH;
        const height = this.calcConstants.HEIGHT;
        uploadRgba32Float(this.device, this.textures.txNewState, state, width, height);
        uploadRgba32Float(this.device, this.textures.txModelVelocities, velocity, width, height);
        uploadRgba32Float(this.device, this.textures.txH, duplicateChannel(velocity, 3, width, height), width, height);
        uploadRgba32Float(this.device, this.textures.txU, duplicateChannel(velocity, 0, width, height), width, height);
        uploadRgba32Float(this.device, this.textures.txV, duplicateChannel(velocity, 1, width, height), width, height);

        this.currentTime = Number(frame.time ?? this.frameIndex);
        const stride = Math.max(1, Number(this.calcConstants.externalFrameStride || 1));
        const nextIndex = this.frameIndex + stride;
        this.frameIndex = this.complete ? nextIndex % this.frameCount : nextIndex;
        this.calcConstants.externalFrameIndex = this.frameIndex;
        this.calcConstants.externalFrameCount = this.frameCount;
        this.calcConstants.externalFrameComplete = this.complete ? 1 : 0;
        return true;
    }

    async refreshManifest({ force = false } = {}) {
        const now = Date.now();
        if (!force && now - this.lastRefresh < 1200) {
            return false;
        }
        this.lastRefresh = now;
        const response = await fetch(this.manifestUrl, { cache: "no-store" });
        if (!response.ok) {
            return false;
        }
        const manifest = await response.json();
        validateManifest(manifest, this.calcConstants, this.manifestUrl);
        const previousCount = this.frameCount;
        this.manifest = manifest;
        this.complete = Boolean(manifest.complete);
        this.calcConstants.externalFrameCount = manifest.frames.length;
        this.calcConstants.externalFrameComplete = this.complete ? 1 : 0;
        return manifest.frames.length > previousCount;
    }
}

export function isExternalSolver(calcConstants) {
    return String(calcConstants.externalSolver || "").toLowerCase() === "reef3d";
}

export async function createExternalFramePlayer(calcConstants, device, textures) {
    const manifestUrl = calcConstants.externalFrameManifest || "/api/scenarios/hk_victoria_smoke/manifest";
    const response = await fetch(manifestUrl, { cache: "no-store" });
    if (!response.ok) {
        throw new Error(`REEF3D frame manifest is not available at ${manifestUrl}. Run the RECE workflow first.`);
    }
    const manifest = await response.json();
    validateManifest(manifest, calcConstants, manifestUrl);
    calcConstants.externalFrameCount = manifest.frames.length;
    calcConstants.externalFrameIndex = 0;
    calcConstants.externalFrameComplete = manifest.complete ? 1 : 0;
    console.log(`Loaded REEF3D external frame manifest with ${manifest.frames.length} frames.`);
    return new ExternalFramePlayer(calcConstants, device, textures, manifest, manifestUrl);
}

function validateManifest(manifest, calcConstants, manifestUrl) {
    if (manifest.width !== calcConstants.WIDTH || manifest.height !== calcConstants.HEIGHT) {
        throw new Error(`External frame grid ${manifest.width}x${manifest.height} does not match Celeris grid ${calcConstants.WIDTH}x${calcConstants.HEIGHT}`);
    }
    if (!Array.isArray(manifest.frames) || manifest.frames.length === 0) {
        throw new Error(`External frame manifest contains no frames at ${manifestUrl}. Wait for the REEF3D job to produce its first frame.`);
    }
    manifest.frames.forEach((frame) => {
        validateRelativeFramePath(frame.state);
        validateRelativeFramePath(frame.velocity);
    });
}
