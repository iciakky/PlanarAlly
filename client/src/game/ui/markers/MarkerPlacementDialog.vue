<script setup lang="ts">
import { ref } from "vue";

import { coreStore } from "../../../store/core";
import { sendCreateReferenceMarker } from "../../api/emits/referenceMarkers";
import { gameState } from "../../systems/game/state";

import { markerPlacementState } from "./placementState";

const COLOUR_PRESETS = [
    { name: "Blue", hex: "#4488ff" },
    { name: "Red", hex: "#ff4444" },
    { name: "Green", hex: "#44bb44" },
    { name: "Yellow", hex: "#ffaa00" },
    { name: "Purple", hex: "#aa44ff" },
    { name: "White", hex: "#ffffff" },
];

const label = ref("");
const note = ref("");
const selectedShape = ref<"ring" | "flag">("ring");
const selectedColour = ref(gameState.raw.isDm ? "#ff4444" : "#4488ff");
const submitting = ref(false);
const errorMessage = ref("");

async function submit(): Promise<void> {
    if (!label.value.trim()) {
        errorMessage.value = "Label is required";
        return;
    }

    submitting.value = true;
    errorMessage.value = "";

    const username = coreStore.state.username;
    const externalId = `${username}:${label.value.trim()}`;
    const scope = gameState.raw.isDm ? "dm" : "player";
    const globalX = markerPlacementState.reactive.globalX;
    const globalY = markerPlacementState.reactive.globalY;

    try {
        await new Promise<void>((resolve, reject) => {
            sendCreateReferenceMarker(
                {
                    external_id: externalId,
                    x: globalX,
                    y: globalY,
                    shape: selectedShape.value,
                    label: label.value.trim(),
                    comment: note.value.trim() || undefined,
                    colour: selectedColour.value,
                    scope,
                    visible_to: [username],
                    render_above_fog: true,
                    record: true,
                },
                (response) => {
                    if (!response.success) {
                        reject(new Error(response.error || "Unknown error"));
                    } else {
                        resolve();
                    }
                },
            );
        });

        label.value = "";
        note.value = "";
        markerPlacementState.close();
    } catch (e) {
        errorMessage.value = `Failed: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
        submitting.value = false;
    }
}

function cancel(): void {
    label.value = "";
    note.value = "";
    errorMessage.value = "";
    markerPlacementState.close();
}
</script>

<template>
    <div v-if="markerPlacementState.reactive.visible" id="marker-dialog-backdrop" @click.self="cancel">
        <div id="marker-dialog">
            <h3>Place Marker</h3>
            <div class="field">
                <label>Shape</label>
                <div class="shape-selector">
                    <button
                        :class="{ active: selectedShape === 'ring' }"
                        class="shape-btn"
                        @click="selectedShape = 'ring'"
                    >Ring</button>
                    <button
                        :class="{ active: selectedShape === 'flag' }"
                        class="shape-btn"
                        @click="selectedShape = 'flag'"
                    >Flag</button>
                </div>
            </div>
            <div class="field">
                <label>Colour</label>
                <div class="colour-swatches">
                    <button
                        v-for="c in COLOUR_PRESETS"
                        :key="c.hex"
                        :title="c.name"
                        :class="{ active: selectedColour === c.hex }"
                        class="swatch"
                        :style="{ background: c.hex }"
                        @click="selectedColour = c.hex"
                    />
                </div>
            </div>
            <div class="field">
                <label for="marker-label">Label *</label>
                <input id="marker-label" v-model="label" type="text" placeholder="e.g. A, B, C" @keyup.enter="submit" />
            </div>
            <div class="field">
                <label for="marker-note">Note</label>
                <input
                    id="marker-note"
                    v-model="note"
                    type="text"
                    placeholder="Optional note (hover to read)"
                    @keyup.enter="submit"
                />
            </div>
            <div v-if="errorMessage" class="error">{{ errorMessage }}</div>
            <div class="actions">
                <button class="btn cancel" @click="cancel">Cancel</button>
                <button class="btn confirm" :disabled="submitting" @click="submit">
                    {{ submitting ? "Placing..." : "Place" }}
                </button>
            </div>
        </div>
    </div>
</template>

<style scoped lang="scss">
#marker-dialog-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    pointer-events: auto;
}

#marker-dialog {
    background: white;
    border-radius: 8px;
    padding: 20px;
    min-width: 280px;
    max-width: 360px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);

    h3 {
        margin: 0 0 16px;
        font-size: 16px;
        color: #333;
    }
}

.shape-selector {
    display: flex;
    gap: 6px;
}

.shape-btn {
    padding: 4px 14px;
    border: 1px solid #ccc;
    border-radius: 4px;
    background: #f5f5f5;
    cursor: pointer;
    font-size: 13px;

    &.active {
        border-color: #82c8a0;
        background: #e8f5e9;
        font-weight: 600;
    }
}

.colour-swatches {
    display: flex;
    gap: 6px;
}

.swatch {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 2px solid #999;
    cursor: pointer;
    padding: 0;

    &.active {
        border-color: #333;
        box-shadow: 0 0 0 2px #82c8a0;
    }
}

.field {
    margin-bottom: 12px;

    label {
        display: block;
        margin-bottom: 4px;
        font-size: 13px;
        color: #555;
    }

    input {
        width: 100%;
        padding: 6px 10px;
        border: 1px solid #ccc;
        border-radius: 4px;
        font-size: 14px;
        box-sizing: border-box;

        &:focus {
            outline: none;
            border-color: #82c8a0;
        }
    }
}

.error {
    color: #d32f2f;
    font-size: 12px;
    margin-bottom: 8px;
}

.actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 16px;
}

.btn {
    padding: 6px 16px;
    border: none;
    border-radius: 4px;
    font-size: 13px;
    cursor: pointer;

    &.cancel {
        background: #e0e0e0;
        color: #333;

        &:hover {
            background: #d0d0d0;
        }
    }

    &.confirm {
        background: #82c8a0;
        color: white;

        &:hover {
            background: #6bb88e;
        }

        &:disabled {
            opacity: 0.6;
            cursor: default;
        }
    }
}
</style>
