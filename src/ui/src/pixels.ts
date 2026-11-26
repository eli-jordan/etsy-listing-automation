/** The pixel spaces the editors measure in. A value branded with one space is a
 * type error where another is expected; a plain number fits any, so arithmetic
 * needs no casts. */
declare const pixelSpace: unique symbol;
type In<Space extends string> = { readonly [pixelSpace]?: Space };

/** The template photo's true pixels: the space template.yaml boxes are written in. */
export type PhotoPx = number & In<"photo">;
/** A box's rectified frame: the unit square stretched to the box's W x H. */
export type RectifiedPx = number & In<"rectified">;
/** CSS pixels from the viewport's corner, as `clientX` and `getBoundingClientRect` give. */
export type ScreenPx = number & In<"screen">;
/** CSS pixels from the editor canvas's own top-left corner. */
export type CanvasPx = number & In<"canvas">;
/** A `<canvas>` bitmap's own pixels: neither the photo's size nor its CSS size. */
export type BackingPx = number & In<"backing">;

export interface PointIn<Px extends number> {
  x: Px;
  y: Px;
}

export type PhotoPoint = PointIn<PhotoPx>;
export type RectifiedPoint = PointIn<RectifiedPx>;
export type ScreenPoint = PointIn<ScreenPx>;
export type CanvasPoint = PointIn<CanvasPx>;

export type PhotoQuad = [
  topLeft: PhotoPoint,
  topRight: PhotoPoint,
  bottomRight: PhotoPoint,
  bottomLeft: PhotoPoint,
];
