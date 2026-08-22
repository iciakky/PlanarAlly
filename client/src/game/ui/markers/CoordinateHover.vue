<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

import { l2g } from "../../../core/conversions";
import { toLP } from "../../../core/geometry";
import { getCellFromPoint } from "../../../core/grid";
import { hitTestMarker } from "../../rendering/markerOverlay";
import { referenceMarkerSystem } from "../../systems/referenceMarkers";
import { locationSettingsState } from "../../systems/settings/location/state";

const mouseX = ref(0);
const mouseY = ref(0);
const visible = ref(false);
const hoveredComment = ref<string | null>(null);

const gridType = computed(() => locationSettingsState.raw.gridType.value);

const cellCoords = computed(() => {
    if (!visible.value) return { q: 0, r: 0 };
    const globalPoint = l2g(toLP(mouseX.value, mouseY.value));
    return getCellFromPoint(globalPoint, gridType.value);
});

const coordinateText = computed(() => `(${cellCoords.value.q}, ${cellCoords.value.r})`);

const tooltipStyle = computed(() => ({
    left: `${mouseX.value + 16}px`,
    top: `${mouseY.value + 16}px`,
}));

function onMouseMove(event: MouseEvent): void {
    mouseX.value = event.pageX;
    mouseY.value = event.pageY;

    const target = event.target as HTMLElement;
    visible.value = target.tagName === "CANVAS";

    if (visible.value) {
        const gPos = l2g(toLP(event.pageX, event.pageY));
        const allMarkers = referenceMarkerSystem.getAllMarkers();
        const hit = hitTestMarker(gPos.x, gPos.y, allMarkers);
        hoveredComment.value = hit?.comment ?? null;
    } else {
        hoveredComment.value = null;
    }
}

function onMouseLeave(): void {
    visible.value = false;
    hoveredComment.value = null;
}

onMounted(() => {
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseleave", onMouseLeave);
});

onUnmounted(() => {
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseleave", onMouseLeave);
});
</script>

<template>
    <div v-if="visible" id="coordinate-hover" :style="tooltipStyle">
        <span class="coords">{{ coordinateText }}</span>
        <span v-if="hoveredComment" class="comment">{{ hoveredComment }}</span>
    </div>
</template>

<style scoped>
#coordinate-hover {
    position: fixed;
    background: rgba(0, 0, 0, 0.75);
    color: #ffffff;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    pointer-events: none;
    z-index: 25;
    max-width: 280px;
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.coords,
.comment {
    font-family: monospace;
    font-size: 12px;
    white-space: pre-wrap;
    word-wrap: break-word;
}
</style>
