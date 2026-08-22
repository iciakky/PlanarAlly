import { socket } from "../socket";

export interface ReferenceMarkerCreateData {
    external_id: string;
    x: number;
    y: number;
    shape: "ring" | "flag";
    label: string;
    comment?: string;
    colour: string;
    scope: "player" | "dm";
    visible_to: string[];
    render_above_fog: boolean;
    record: boolean;
}

export function sendCreateReferenceMarker(
    data: ReferenceMarkerCreateData,
    callback: (response: { success: boolean; error?: string }) => void,
): void {
    socket.emit("ReferenceMarker.Create", data, callback);
}

export function sendDeleteReferenceMarker(externalId: string): void {
    socket.emit("ReferenceMarker.Delete", { external_id: externalId });
}
