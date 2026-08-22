import { buildState } from "../../../core/systems/state";

export interface ReferenceMarkerData {
    external_id: string;
    x: number;
    y: number;
    target_x?: number;
    target_y?: number;
    shape: "ring" | "arrow" | "label" | "flag";
    label: string;
    text?: string;
    comment?: string;
    colour?: string;
    scope: "player" | "dm";
    owner: string;
    visible_to: string[];
    render_above_fog: boolean;
    record: boolean;
    metadata?: Record<string, unknown>;
}

interface ReferenceMarkerState {
    markers: Map<string, ReferenceMarkerData>;
    overlayVisible: boolean;
    textVisible: boolean;
}

const state = buildState<ReferenceMarkerState>({
    markers: new Map(),
    overlayVisible: true,
    textVisible: true,
});

export const referenceMarkerState = {
    ...state,
};
