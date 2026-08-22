import type { DeepReadonly } from "vue";

import { g2l } from "../../core/conversions";
import { toGP } from "../../core/geometry";
import { positionState } from "../systems/position/state";
import type { ReferenceMarkerData } from "../systems/referenceMarkers/state";
import { referenceMarkerState } from "../systems/referenceMarkers/state";

const HIT_RADIUS_SCREEN = 30;

let _canvas: HTMLCanvasElement | null = null;
let _ctx: CanvasRenderingContext2D | null = null;
let _animFrameId = 0;
let _running = false;

export function initMarkerOverlay(canvas: HTMLCanvasElement): void {
  _canvas = canvas;
  _ctx = canvas.getContext("2d");
  resizeOverlay();
  if (!_running) {
    _running = true;
    _animFrameId = requestAnimationFrame(drawLoop);
  }
}

export function stopMarkerOverlay(): void {
  _running = false;
  if (_animFrameId) {
    cancelAnimationFrame(_animFrameId);
    _animFrameId = 0;
  }
  _canvas = null;
  _ctx = null;
}

export function resizeOverlay(): void {
  if (!_canvas) return;
  const dpr = window.devicePixelRatio || 1;
  _canvas.width = window.innerWidth * dpr;
  _canvas.height = window.innerHeight * dpr;
  _canvas.style.width = `${window.innerWidth}px`;
  _canvas.style.height = `${window.innerHeight}px`;
  if (_ctx) _ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawLoop(): void {
  if (!_running) return;
  render();
  _animFrameId = requestAnimationFrame(drawLoop);
}

function render(): void {
  if (!_ctx || !_canvas) return;

  const state = referenceMarkerState.reactive;
  if (!state.overlayVisible) {
    _ctx.clearRect(0, 0, _canvas.width, _canvas.height);
    return;
  }

  _ctx.clearRect(0, 0, _canvas.width, _canvas.height);

  for (const marker of state.markers.values()) {
    if (!marker.render_above_fog) continue;
    drawMarker(_ctx, marker);
  }
}

function parseColourToRgb(colour: string): [number, number, number] {
  if (colour.startsWith("#")) {
    const hex = colour.slice(1);
    if (hex.length === 3) {
      return [
        parseInt(hex[0]! + hex[0]!, 16),
        parseInt(hex[1]! + hex[1]!, 16),
        parseInt(hex[2]! + hex[2]!, 16),
      ];
    }
    return [
      parseInt(hex.slice(0, 2), 16),
      parseInt(hex.slice(2, 4), 16),
      parseInt(hex.slice(4, 6), 16),
    ];
  }
  const match = colour.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (match)
    return [parseInt(match[1]!), parseInt(match[2]!), parseInt(match[3]!)];
  return [255, 68, 68];
}

function getContrastOutline(colour: string): {
  outlineColour: string;
  shadowAlpha: number;
} {
  const [r, g, b] = parseColourToRgb(colour);
  const y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  return {
    outlineColour: y > 0.5 ? "#000000" : "#ffffff",
    shadowAlpha: 0.4,
  };
}

function applyContrastStyle(
  ctx: CanvasRenderingContext2D,
  colour: string,
): void {
  const { outlineColour, shadowAlpha } = getContrastOutline(colour);
  ctx.shadowColor = `rgba(0,0,0,${shadowAlpha})`;
  ctx.shadowBlur = 4;
  ctx.shadowOffsetX = 1;
  ctx.shadowOffsetY = 1;
  (ctx as any)._outlineColour = outlineColour;
}

function drawMarker(
  ctx: CanvasRenderingContext2D,
  marker: DeepReadonly<ReferenceMarkerData>,
): void {
  const colour = marker.colour ?? "#ff4444";
  const localPos = g2l(toGP(marker.x, marker.y));
  const zoom = positionState.readonly.zoom;

  ctx.save();
  try {
    applyContrastStyle(ctx, colour);
    switch (marker.shape) {
      case "ring":
        drawRing(
          ctx,
          localPos.x,
          localPos.y,
          colour,
          marker.label,
          marker.text,
          zoom,
        );
        break;
      case "arrow":
        drawArrow(ctx, localPos.x, localPos.y, marker, colour, zoom);
        break;
      case "label":
        drawLabel(
          ctx,
          localPos.x,
          localPos.y,
          colour,
          marker.label,
          marker.text,
        );
        break;
      case "flag":
        drawFlag(
          ctx,
          localPos.x,
          localPos.y,
          colour,
          marker.label,
          marker.text,
          zoom,
        );
        break;
    }
  } finally {
    ctx.restore();
  }
}

function drawRing(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  colour: string,
  label: string,
  text: string | undefined,
  zoom: number,
): void {
  const radius = Math.max(12, 20 * zoom);
  const lineW = Math.max(2, 3 * zoom);
  const outlineColour = (ctx as any)._outlineColour ?? "#ffffff";

  // Outline stroke (wider, contrasting)
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.strokeStyle = outlineColour;
  ctx.lineWidth = lineW + 2;
  ctx.stroke();

  // Main colour stroke
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.strokeStyle = colour;
  ctx.lineWidth = lineW;
  ctx.stroke();

  // Label above the ring
  const fontSize = Math.max(10, 12 * zoom);
  ctx.font = `bold ${fontSize}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.strokeStyle = outlineColour;
  ctx.lineWidth = 3;
  ctx.strokeText(label, x, y - radius - 4);
  ctx.fillStyle = colour;
  ctx.fillText(label, x, y - radius - 4);

  // Text below the ring (toggleable)
  if (
    referenceMarkerState.reactive.textVisible &&
    text !== undefined &&
    text !== ""
  ) {
    ctx.font = `${Math.max(9, 10 * zoom)}px sans-serif`;
    ctx.textBaseline = "top";
    ctx.strokeStyle = outlineColour;
    ctx.lineWidth = 2;
    ctx.globalAlpha = 0.8;
    ctx.strokeText(text, x, y + radius + 4);
    ctx.fillStyle = colour;
    ctx.fillText(text, x, y + radius + 4);
    ctx.globalAlpha = 1;
  }
}

function drawArrow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  marker: DeepReadonly<ReferenceMarkerData>,
  colour: string,
  zoom: number,
): void {
  const targetX = marker.target_x ?? marker.x;
  const targetY = marker.target_y ?? marker.y;
  const localTarget = g2l(toGP(targetX, targetY));

  const tx = localTarget.x;
  const ty = localTarget.y;

  const lineW = Math.max(2, 3 * zoom);
  const outlineColour = (ctx as any)._outlineColour ?? "#ffffff";

  // Outline line
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(tx, ty);
  ctx.strokeStyle = outlineColour;
  ctx.lineWidth = lineW + 2;
  ctx.stroke();

  // Main line
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(tx, ty);
  ctx.strokeStyle = colour;
  ctx.lineWidth = lineW;
  ctx.stroke();

  // Arrowhead at target
  const angle = Math.atan2(ty - y, tx - x);
  const headLen = Math.max(10, 15 * zoom);
  ctx.beginPath();
  ctx.moveTo(tx, ty);
  ctx.lineTo(
    tx - headLen * Math.cos(angle - Math.PI / 6),
    ty - headLen * Math.sin(angle - Math.PI / 6),
  );
  ctx.lineTo(
    tx - headLen * Math.cos(angle + Math.PI / 6),
    ty - headLen * Math.sin(angle + Math.PI / 6),
  );
  ctx.closePath();
  ctx.strokeStyle = outlineColour;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = colour;
  ctx.fill();

  // Label at midpoint (with outline text)
  const mx = (x + tx) / 2;
  const my = (y + ty) / 2;
  const fontSize = Math.max(10, 12 * zoom);
  ctx.font = `bold ${fontSize}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.strokeStyle = outlineColour;
  ctx.lineWidth = 3;
  ctx.strokeText(marker.label, mx, my - 8);
  ctx.fillStyle = colour;
  ctx.fillText(marker.label, mx, my - 8);

  // Text at midpoint (toggleable)
  if (
    referenceMarkerState.reactive.textVisible &&
    marker.text !== undefined &&
    marker.text !== ""
  ) {
    const mx = (x + tx) / 2;
    const my = (y + ty) / 2;
    ctx.font = `${Math.max(9, 10 * zoom)}px sans-serif`;
    ctx.textBaseline = "top";
    ctx.globalAlpha = 0.8;
    ctx.strokeStyle = outlineColour;
    ctx.lineWidth = 2;
    ctx.strokeText(marker.text, mx, my + 4);
    ctx.fillStyle = colour;
    ctx.fillText(marker.text, mx, my + 4);
    ctx.globalAlpha = 1;
  }
}

function drawLabel(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  colour: string,
  label: string,
  text: string | undefined,
): void {
  ctx.font = "bold 13px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  const labelWidth = ctx.measureText(label).width + 12;
  const labelHeight = 22;

  // Background box
  ctx.fillStyle = colour;
  ctx.globalAlpha = 0.85;
  ctx.beginPath();
  ctx.roundRect(
    x - labelWidth / 2,
    y - labelHeight / 2,
    labelWidth,
    labelHeight,
    4,
  );
  ctx.fill();
  ctx.globalAlpha = 1;

  // Label text
  ctx.fillStyle = "#ffffff";
  ctx.fillText(label, x, y);

  // Additional text below (toggleable)
  if (
    referenceMarkerState.reactive.textVisible &&
    text !== undefined &&
    text !== ""
  ) {
    const outlineColour = (ctx as any)._outlineColour ?? "#ffffff";
    ctx.font = "11px sans-serif";
    ctx.textBaseline = "top";
    ctx.strokeStyle = outlineColour;
    ctx.lineWidth = 2;
    ctx.strokeText(text, x, y + labelHeight / 2 + 4);
    ctx.fillStyle = colour;
    ctx.fillText(text, x, y + labelHeight / 2 + 4);
  }
}

function drawFlag(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  colour: string,
  label: string,
  text: string | undefined,
  zoom: number,
): void {
  const poleHeight = Math.max(20, 30 * zoom);
  const flagWidth = Math.max(14, 20 * zoom);
  const flagHeight = Math.max(10, 14 * zoom);

  const poleW = Math.max(1.5, 2 * zoom);
  const outlineColour = (ctx as any)._outlineColour ?? "#ffffff";

  // Pole outline
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x, y - poleHeight);
  ctx.strokeStyle = outlineColour;
  ctx.lineWidth = poleW + 2;
  ctx.stroke();

  // Pole
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x, y - poleHeight);
  ctx.strokeStyle = colour;
  ctx.lineWidth = poleW;
  ctx.stroke();

  // Flag triangle outline
  ctx.beginPath();
  ctx.moveTo(x, y - poleHeight);
  ctx.lineTo(x + flagWidth, y - poleHeight + flagHeight / 2);
  ctx.lineTo(x, y - poleHeight + flagHeight);
  ctx.closePath();
  ctx.strokeStyle = outlineColour;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = colour;
  ctx.fill();

  // Label beside the flag (with outline text)
  const fontSize = Math.max(10, 12 * zoom);
  ctx.font = `bold ${fontSize}px sans-serif`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.strokeStyle = outlineColour;
  ctx.lineWidth = 3;
  ctx.strokeText(label, x + flagWidth + 4, y - poleHeight + flagHeight / 2);
  ctx.fillStyle = colour;
  ctx.fillText(label, x + flagWidth + 4, y - poleHeight + flagHeight / 2);

  // Text below the pole base (toggleable)
  if (
    referenceMarkerState.reactive.textVisible &&
    text !== undefined &&
    text !== ""
  ) {
    ctx.font = `${Math.max(9, 10 * zoom)}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.globalAlpha = 0.8;
    ctx.strokeStyle = outlineColour;
    ctx.lineWidth = 2;
    ctx.strokeText(text, x, y + 4);
    ctx.fillStyle = colour;
    ctx.fillText(text, x, y + 4);
    ctx.globalAlpha = 1;
  }
}

export function hitTestMarker(
  globalX: number,
  globalY: number,
  markers: readonly ReferenceMarkerData[],
): ReferenceMarkerData | null {
  const zoom = positionState.readonly.zoom;
  const hitRadiusGlobal = HIT_RADIUS_SCREEN / zoom;
  let nearest: ReferenceMarkerData | null = null;
  let nearestDist = hitRadiusGlobal;
  for (const m of markers) {
    const dx = globalX - m.x;
    const dy = globalY - m.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < nearestDist) {
      nearestDist = dist;
      nearest = m;
    }
  }
  return nearest;
}
