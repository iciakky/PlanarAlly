import { socket } from "../../api/socket";

import { referenceMarkerSystem } from ".";
import type { ReferenceMarkerData } from "./state";

socket.on("ReferenceMarker.Add", (marker: ReferenceMarkerData) => {
    referenceMarkerSystem.addMarker(marker);
});

socket.on("ReferenceMarker.Remove", (data: { external_id: string }) => {
    referenceMarkerSystem.removeMarker(data.external_id);
});

socket.on("ReferenceMarker.Set", (markers: ReferenceMarkerData[]) => {
    referenceMarkerSystem.setMarkers(markers);
});
