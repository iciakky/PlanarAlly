import { reactive } from "vue";

import { l2g } from "../../../core/conversions";
import { toLP } from "../../../core/geometry";

interface MarkerPlacementState {
    visible: boolean;
    globalX: number;
    globalY: number;
}

const state = reactive<MarkerPlacementState>({
    visible: false,
    globalX: 0,
    globalY: 0,
});

export const markerPlacementState = {
    get reactive() {
        return state;
    },

    open(screenX: number, screenY: number): void {
        const globalPoint = l2g(toLP(screenX, screenY));
        state.globalX = globalPoint.x;
        state.globalY = globalPoint.y;
        state.visible = true;
    },

    close(): void {
        state.visible = false;
    },
};
