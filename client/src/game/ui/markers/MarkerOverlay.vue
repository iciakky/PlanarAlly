<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

import { initMarkerOverlay, resizeOverlay, stopMarkerOverlay } from "../../rendering/markerOverlay";

const canvasRef = ref<HTMLCanvasElement | null>(null);

function onResize(): void {
    resizeOverlay();
}

onMounted(() => {
    if (canvasRef.value) {
        initMarkerOverlay(canvasRef.value);
    }
    window.addEventListener("resize", onResize);
});

onUnmounted(() => {
    stopMarkerOverlay();
    window.removeEventListener("resize", onResize);
});
</script>

<template>
    <canvas id="marker-overlay" ref="canvasRef"></canvas>
</template>

<style scoped>
#marker-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 10;
    pointer-events: none;
}
</style>
