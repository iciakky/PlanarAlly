import { socket } from "./api/socket";
import { visionState } from "./vision/state";
import { getGlobalId } from "./id";
import type { LocalId } from "../core/id";
import { g2l } from "../core/conversions";
import { positionSystem } from "./systems/position";
import { positionState } from "./systems/position/state";
import { floorSystem } from "./systems/floors";
import { gameState } from "./systems/game/state";

const params = new URLSearchParams(window.location.search);
export const isAutomationMode = params.get("automation") === "1";
export const hideUi = params.get("hideUi") === "1";

let _readyResolve: ((value: boolean) => void) | null = null;
let _readyReject: ((reason: Error) => void) | null = null;
let _readyTimer: ReturnType<typeof setTimeout> | null = null;
let _readyPromise = _newReadyPromise();

let _lastProcessedRevision = 0;
let _epoch = 0;
let _reconnectCount = 0;
let _revisionWaiters: Array<{
    revision: number;
    epoch: number;
    resolve: () => void;
    reject: (e: Error) => void;
    timer: ReturnType<typeof setTimeout> | null;
}> = [];
let _listenersRegistered = false;
let _externalIdCache: Map<string, string> | null = null;

function _newReadyPromise(): Promise<boolean> {
    return new Promise<boolean>((resolve, reject) => {
        _readyResolve = resolve;
        _readyReject = reject;
    });
}

function _settleReady(): void {
    if (_readyTimer) {
        clearTimeout(_readyTimer);
        _readyTimer = null;
    }
    _readyResolve = null;
    _readyReject = null;
}

function _onLocationLoaded(): void {
    _externalIdCache = null;
    if (_readyResolve) {
        _readyResolve(true);
        _settleReady();
    }
}

function _onRevisionReceived(revision: number): void {
    _lastProcessedRevision = Math.max(_lastProcessedRevision, revision);
    _externalIdCache = null;

    requestAnimationFrame(() => {
        const resolved: number[] = [];
        for (let i = 0; i < _revisionWaiters.length; i++) {
            const w = _revisionWaiters[i]!;
            if (w.epoch === _epoch && w.revision <= _lastProcessedRevision) {
                if (w.timer) clearTimeout(w.timer);
                w.resolve();
                resolved.push(i);
            }
        }
        for (let i = resolved.length - 1; i >= 0; i--) {
            _revisionWaiters.splice(resolved[i]!, 1);
        }
    });
}

function _onReconnect(): void {
    _lastProcessedRevision = 0;
    _epoch++;
    _reconnectCount++;
    _externalIdCache = null;

    const staleWaiters = _revisionWaiters;
    _revisionWaiters = [];
    requestAnimationFrame(() => {
        for (const w of staleWaiters) {
            if (w.timer) clearTimeout(w.timer);
            w.reject(new Error(`Connection lost (reconnect #${_reconnectCount}). Revision epoch changed.`));
        }
    });

    if (_readyReject) {
        _readyReject(new Error(`Connection lost (reconnect #${_reconnectCount}). Call ready() again.`));
    }
    _settleReady();
    _readyPromise = _newReadyPromise();
}

async function _fetchExternalIds(): Promise<Map<string, string>> {
    if (_externalIdCache) return _externalIdCache;

    const epochBefore = _epoch;
    const mappings: Record<string, string> = await new Promise((resolve) => {
        socket.emit("Automation.ExternalIds.Request", null, (response: Record<string, string>) => {
            resolve(response);
        });
    });

    if (_epoch !== epochBefore) {
        _externalIdCache = null;
        throw new Error("Reconnect during getVisibleShapes. Await ready() then call getVisibleShapes() again.");
    }

    _externalIdCache = new Map(Object.entries(mappings));
    return _externalIdCache;
}

export function setupAutomation(): void {
    if (!isAutomationMode) return;

    if (!_listenersRegistered) {
        socket.on("connect", () => _onReconnect());
        socket.on("Location.Loaded", () => _onLocationLoaded());
        socket.on("Automation.Revision", (data: { revision: number }) => _onRevisionReceived(data.revision));
        _listenersRegistered = true;
    }

    const api = {
        ready(opts?: { timeout?: number }): Promise<boolean> {
            const timeout = opts?.timeout ?? 60000;
            return new Promise<boolean>((resolve, reject) => {
                _readyPromise.then(
                    (v) => { if (_readyTimer) { clearTimeout(_readyTimer); _readyTimer = null; } resolve(v); },
                    (e) => { if (_readyTimer) { clearTimeout(_readyTimer); _readyTimer = null; } reject(e); },
                );
                _readyTimer = setTimeout(() => {
                    _readyTimer = null;
                    reject(new Error("ready() timed out after " + timeout + "ms"));
                }, timeout);
            });
        },

        waitForSync(opts: { revision: number; timeout?: number }): Promise<void> {
            const currentEpoch = _epoch;

            if (opts.revision <= _lastProcessedRevision) {
                return new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
            }

            return new Promise<void>((resolve, reject) => {
                let timer: ReturnType<typeof setTimeout> | null = null;
                const entry = {
                    revision: opts.revision,
                    epoch: currentEpoch,
                    resolve: () => { if (timer) clearTimeout(timer); resolve(); },
                    reject: (e: Error) => { if (timer) clearTimeout(timer); reject(e); },
                    timer: null as ReturnType<typeof setTimeout> | null,
                };

                const timeout = opts.timeout ?? 30000;
                timer = setTimeout(() => {
                    const idx = _revisionWaiters.indexOf(entry);
                    if (idx !== -1) _revisionWaiters.splice(idx, 1);
                    reject(
                        new Error(
                            `waitForSync timed out: requested=${opts.revision}, current=${_lastProcessedRevision}, epoch=${_epoch}`,
                        ),
                    );
                }, timeout);
                entry.timer = timer;

                _revisionWaiters.push(entry);
            });
        },

        async getVisibleShapes(): Promise<
            Array<{
                uuid: string;
                external_id: string | null;
                layer: string;
                visible: boolean;
                reason: string;
            }>
        > {
            const results: Array<{
                uuid: string;
                external_id: string | null;
                layer: string;
                visible: boolean;
                reason: string;
            }> = [];

            const idMap = (window as any).idMap as Map<LocalId, any> | undefined;
            if (!idMap) return results;

            const externalIds = await _fetchExternalIds();

            for (const [localId, shape] of idMap) {
                const globalId = getGlobalId(localId);
                if (!globalId) continue;

                const layer = shape.layer;
                if (!layer) continue;

                const layerName = layer.name ?? "unknown";
                const center = shape.center;
                const localPoint = g2l(center);

                let visible = false;
                let reason = "not_in_vision";

                try {
                    visible = visionState.isInVision(localPoint);
                    reason = visible ? "visible" : "not_in_vision";
                } catch {
                    reason = "not_in_vision";
                }

                results.push({
                    uuid: globalId,
                    external_id: externalIds.get(globalId) ?? null,
                    layer: layerName,
                    visible,
                    reason,
                });
            }

            return results;
        },

        setView(opts: { panX?: number; panY?: number; zoom?: number }): void {
            if (!gameState.raw.boardInitialized) throw new Error("setView: board not ready. Call ready() first.");
            if (opts.panX !== undefined || opts.panY !== undefined) {
                const x = opts.panX ?? positionState.mutable.panX;
                const y = opts.panY ?? positionState.mutable.panY;
                positionSystem.setPan(x, y, { updateSectors: true });
            }
            if (opts.zoom !== undefined) {
                positionSystem.setZoomDisplay(opts.zoom, {
                    invalidate: true,
                    updateSectors: true,
                    sync: false,
                });
            }
            floorSystem.invalidateAllFloors();
        },

        setViewToBounds(opts: { x: number; y: number; width: number; height: number; padding?: number }): void {
            if (!gameState.raw.boardInitialized) throw new Error("setViewToBounds: board not ready.");
            const padding = opts.padding ?? 50;
            const screenW = window.innerWidth;
            const screenH = window.innerHeight;
            const targetW = opts.width + padding * 2;
            const targetH = opts.height + padding * 2;

            const scaleX = screenW / targetW;
            const scaleY = screenH / targetH;
            const factor = Math.min(scaleX, scaleY);

            // Inverse of zoomDisplayToFactor: factor = 1 / (-5/3 + (28/15) * exp(1.83 * display))
            // Solve for display: display = ln((1/factor + 5/3) * 15/28) / 1.83
            const inner = (1 / factor + 5 / 3) * 15 / 28;
            let zoomDisplay = inner > 0 ? Math.log(inner) / 1.83 : 0.5;
            zoomDisplay = Math.max(0, Math.min(1, zoomDisplay));

            const centerX = opts.x + opts.width / 2;
            const centerY = opts.y + opts.height / 2;
            const panX = -(centerX - screenW / (2 * factor));
            const panY = -(centerY - screenH / (2 * factor));

            positionSystem.setPan(panX, panY, { updateSectors: true });
            positionSystem.setZoomDisplay(zoomDisplay, {
                invalidate: true,
                updateSectors: true,
                sync: false,
            });
            floorSystem.invalidateAllFloors();
        },

        async readyStable(opts?: { timeout?: number; maxRetries?: number }): Promise<boolean> {
            const timeout = opts?.timeout ?? 60000;
            const maxRetries = opts?.maxRetries ?? 3;
            for (let attempt = 0; attempt <= maxRetries; attempt++) {
                try {
                    return await this.ready({ timeout });
                } catch (e) {
                    const isReconnect = e instanceof Error && e.message.includes("Connection lost");
                    if (!isReconnect || attempt >= maxRetries) throw e;
                }
            }
            throw new Error("readyStable: exceeded max retries");
        },

        reloadLocation(): Promise<boolean> {
            if (_readyReject) {
                _readyReject(new Error("reloadLocation() called, previous ready() invalidated."));
            }
            _settleReady();
            _lastProcessedRevision = 0;
            _externalIdCache = null;
            _readyPromise = _newReadyPromise();
            socket.emit("Location.Load");
            return _readyPromise;
        },

        get lastRevision(): number {
            return _lastProcessedRevision;
        },

        get reconnectCount(): number {
            return _reconnectCount;
        },

        get epoch(): number {
            return _epoch;
        },
    };

    (window as any).planarallyAutomation = api;
}
