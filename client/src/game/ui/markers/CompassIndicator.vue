<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
    northDegrees: number;
}>();

const rotationStyle = computed(() => ({
    transform: `rotate(${props.northDegrees}deg)`,
}));
</script>

<template>
    <div id="compass-indicator">
        <div class="compass-body" :style="rotationStyle">
            <div class="compass-north">N</div>
            <div class="compass-arrow">
                <div class="arrow-north"></div>
                <div class="arrow-south"></div>
            </div>
            <div class="compass-south">S</div>
        </div>
        <div class="compass-ring">
            <span class="compass-dir compass-e">E</span>
            <span class="compass-dir compass-w">W</span>
        </div>
    </div>
</template>

<style scoped lang="scss">
#compass-indicator {
    position: fixed;
    top: 70px;
    right: 20px;
    width: 50px;
    height: 50px;
    pointer-events: none;
    z-index: 22;
}

.compass-body {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    transition: transform 0.3s ease;
}

.compass-north,
.compass-south {
    font-size: 11px;
    font-weight: bold;
    line-height: 1;
}

.compass-north {
    color: #d32f2f;
}

.compass-south {
    color: #666;
}

.compass-arrow {
    display: flex;
    flex-direction: column;
    align-items: center;
    height: 18px;
}

.arrow-north {
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 10px solid #d32f2f;
}

.arrow-south {
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 10px solid #999;
}

.compass-ring {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    border: 2px solid rgba(0, 0, 0, 0.2);
    border-radius: 50%;
}

.compass-dir {
    position: absolute;
    font-size: 9px;
    font-weight: bold;
    color: #666;
}

.compass-e {
    right: -2px;
    top: 50%;
    transform: translate(100%, -50%);
}

.compass-w {
    left: -2px;
    top: 50%;
    transform: translate(-100%, -50%);
}
</style>
