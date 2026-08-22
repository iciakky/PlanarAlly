import { registerSystem } from "../../../core/systems";
import type { System, SystemClearReason } from "../../../core/systems/models";

import type { ReferenceMarkerData } from "./state";
import { referenceMarkerState } from "./state";

const { mutableReactive: $ } = referenceMarkerState;

class ReferenceMarkerSystem implements System {
    clear(reason: SystemClearReason): void {
        if (reason === "full-loading" || reason === "partial-loading") {
            $.markers.clear();
        }
    }

    addMarker(marker: ReferenceMarkerData): void {
        $.markers.set(marker.external_id, marker);
    }

    removeMarker(externalId: string): void {
        $.markers.delete(externalId);
    }

    setMarkers(markers: ReferenceMarkerData[]): void {
        $.markers.clear();
        for (const marker of markers) {
            $.markers.set(marker.external_id, marker);
        }
    }

    getMarker(externalId: string): ReferenceMarkerData | undefined {
        return $.markers.get(externalId);
    }

    getAllMarkers(): ReferenceMarkerData[] {
        return [...$.markers.values()];
    }

    clearByPrefix(prefix: string): void {
        for (const [key] of $.markers) {
            if (key.startsWith(prefix)) {
                $.markers.delete(key);
            }
        }
    }

    clearByScope(scope: "player" | "dm"): void {
        for (const [key, marker] of $.markers) {
            if (marker.scope === scope) {
                $.markers.delete(key);
            }
        }
    }

    setOverlayVisible(visible: boolean): void {
        $.overlayVisible = visible;
    }

    toggleTextVisible(): void {
        $.textVisible = !$.textVisible;
    }

    getOwnMarkers(username: string): ReferenceMarkerData[] {
        return [...$.markers.values()].filter((m) => m.owner === username);
    }
}

export const referenceMarkerSystem = new ReferenceMarkerSystem();
registerSystem("referenceMarkers", referenceMarkerSystem, false, referenceMarkerState);
