import { type Matrix, type Quad, proportions, toPhoto, unitFrame } from "./pose";

/**
 * The stage's picture while a position is ahead of its render, drawn on the
 * GPU so it keeps up with the pointer: the bare photo, then each layer's
 * artwork through the same homography the server warps it by.
 *
 * It stands in for a render that can take seconds. A Photo warp template's
 * shade is `passes.py`'s arithmetic, on the luminance of a photo assumed to span
 * the full range. A Marigold print approximates what the maps know: it picks up
 * the garment's light as the photo's luminance over the luminance around the
 * box, and is cut to the cloth by the template's mask. Neither displaces or fits
 * the print to the cloth, so the render that replaces it can move the ink a
 * little.
 */

/** How a template's print takes the garment's light. */
export type LiveLook =
  | { kind: "marigold" }
  | { kind: "photo-warp"; blend: "multiply" | "soft-light" | "grey-pivot"; opacity: number };

export interface LiveLayer {
  id: string;
  /** Where the print sits now, in photo pixels. */
  quad: Quad;
  /** The template's own box, which fixes what "the garment's light" is measured
   * against, so the print does not brighten and dim as it moves. */
  box: Quad;
}

export interface LiveRenderer {
  setPhoto: (photo: TexImageSource) => void;
  /** Sets one layer's pictures. A layer with none is drawn bare. */
  setLayer: (id: string, artwork: TexImageSource, mask: TexImageSource | null) => void;
  clearLayers: () => void;
  resize: (width: number, height: number) => void;
  draw: (size: { w: number; h: number }, look: LiveLook, layers: readonly LiveLayer[]) => void;
  dispose: () => void;
}

const VERTEX = `#version 300 es
out vec2 vUv;
void main() {
  // One triangle over the canvas; v runs down, as a photo's rows do.
  vec2 corner = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  vUv = corner;
  gl_Position = vec4(corner.x * 2.0 - 1.0, 1.0 - corner.y * 2.0, 0.0, 1.0);
}`;

const FRAGMENT = `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 colour;
uniform sampler2D uPhoto;
uniform sampler2D uArtwork;
uniform sampler2D uMask;
uniform bool uPrint;
uniform mat3 uToUnit;
uniform vec2 uSize;
uniform vec3 uGarment;
uniform int uBlend;
uniform float uOpacity;

// Mip filtering softens a downscaled picture; the stage should read as sharply
// as the composite under it.
const float SHARPEN = -0.5;
const int BLEND_MARIGOLD = 0;
const int BLEND_MULTIPLY = 1;
const int BLEND_SOFT_LIGHT = 2;

vec3 linear(vec3 c) { return pow(c, vec3(2.2)); }
vec3 display(vec3 c) { return pow(c, vec3(1.0 / 2.2)); }
float light(vec3 c) { return dot(linear(c), vec3(0.2126, 0.7152, 0.0722)); }

vec3 softLight(vec3 base, float l) {
  if (l <= 0.5) return 2.0 * base * l + base * base * (1.0 - 2.0 * l);
  return sqrt(base) * (2.0 * l - 1.0) + 2.0 * base * (1.0 - l);
}

// The print's colour, unpremultiplied, under the garment's light.
vec3 shaded(vec3 ink) {
  vec3 photo = texture(uPhoto, vUv).rgb;
  if (uBlend == BLEND_MARIGOLD) {
    float garment = light(textureLod(uPhoto, uGarment.xy, uGarment.z).rgb);
    float gain = clamp(light(texture(uPhoto, vUv, 1.0).rgb) / max(garment, 0.01), 0.4, 1.2);
    return display(linear(ink) * gain);
  }
  float l = dot(photo, vec3(0.299, 0.587, 0.114));
  vec3 blended = uBlend == BLEND_MULTIPLY ? ink * l
    : uBlend == BLEND_SOFT_LIGHT ? softLight(ink, l)
    : clamp(ink + (l - 0.5) * 2.0, 0.0, 1.0);
  return mix(ink, blended, uOpacity);
}

void main() {
  if (!uPrint) {
    colour = vec4(texture(uPhoto, vUv, SHARPEN).rgb, 1.0);
    return;
  }
  vec3 mapped = uToUnit * vec3(vUv * uSize, 1.0);
  vec2 uv = mapped.xy / mapped.z;
  vec4 ink = texture(uArtwork, uv, SHARPEN);
  vec2 inside = step(vec2(0.0), uv) * step(uv, vec2(1.0));
  float alpha = ink.a * inside.x * inside.y * texture(uMask, vUv).r;
  colour = vec4(shaded(ink.rgb / max(ink.a, 0.001)) * alpha, alpha);
}`;

/** The fragment shader's `uBlend` and `uOpacity` for `look`. */
function lookUniforms(look: LiveLook): { blend: number; opacity: number } {
  if (look.kind === "marigold") return { blend: 0, opacity: 1 };
  const blend = { multiply: 1, "soft-light": 2, "grey-pivot": 3 }[look.blend];
  return { blend, opacity: look.opacity };
}

/** `m` for a GLSL `mat3`, which is column-major. */
const columns = (m: Matrix) => [m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]];

/** Where a layer measures the garment's light: the middle of the template's
 * box, averaged over about half of it by the photo's mip chain. */
export function garmentSample(box: Quad, size: { w: number; h: number }): [number, number, number] {
  const centre = toPhoto(box, { x: 0.5, y: 0.5 });
  const { w, h } = proportions(box);
  return [centre.x / size.w, centre.y / size.h, Math.log2(Math.max(1, Math.min(w, h) / 2))];
}

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (shader === null) throw new Error("no shader");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS) !== true) {
    throw new Error(gl.getShaderInfoLog(shader) ?? "shader did not compile");
  }
  return shader;
}

function link(gl: WebGL2RenderingContext): WebGLProgram {
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(program);
  if (gl.getProgramParameter(program, gl.LINK_STATUS) !== true) {
    throw new Error(gl.getProgramInfoLog(program) ?? "program did not link");
  }
  return program;
}

/** A mip-mapped texture of `source`, its colour premultiplied so that filtering
 * never bleeds what lies under transparent artwork into the print's edge. */
function texture(gl: WebGL2RenderingContext, source: TexImageSource): WebGLTexture {
  const made = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, made);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
  gl.generateMipmap(gl.TEXTURE_2D);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return made;
}

/** A mask that cuts nothing, for a template without one. */
function uncut(gl: WebGL2RenderingContext): WebGLTexture {
  const made = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, made);
  const white = new Uint8Array([255, 255, 255, 255]);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, white);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  return made;
}

function bind(gl: WebGL2RenderingContext, unit: number, made: WebGLTexture | null) {
  gl.activeTexture(gl.TEXTURE0 + unit);
  gl.bindTexture(gl.TEXTURE_2D, made);
}

function rendererOn(canvas: HTMLCanvasElement, gl: WebGL2RenderingContext): LiveRenderer {
  const program = link(gl);
  const at = (name: string) => gl.getUniformLocation(program, name);
  const uniforms = {
    print: at("uPrint"),
    toUnit: at("uToUnit"),
    size: at("uSize"),
    garment: at("uGarment"),
    blend: at("uBlend"),
    opacity: at("uOpacity"),
  };
  gl.useProgram(program);
  gl.uniform1i(at("uPhoto"), 0);
  gl.uniform1i(at("uArtwork"), 1);
  gl.uniform1i(at("uMask"), 2);
  gl.bindVertexArray(gl.createVertexArray());
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

  const none = uncut(gl);
  let photo: WebGLTexture | null = null;
  const prints = new Map<string, { artwork: WebGLTexture; mask: WebGLTexture | null }>();

  function drawPrint(size: { w: number; h: number }, layer: LiveLayer) {
    const print = prints.get(layer.id);
    if (print === undefined) return;
    bind(gl, 1, print.artwork);
    bind(gl, 2, print.mask ?? none);
    gl.uniformMatrix3fv(uniforms.toUnit, false, columns(unitFrame(layer.quad)));
    gl.uniform3fv(uniforms.garment, garmentSample(layer.box, size));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function clearLayers() {
    for (const print of prints.values()) {
      gl.deleteTexture(print.artwork);
      gl.deleteTexture(print.mask);
    }
    prints.clear();
  }

  return {
    setPhoto: (source) => {
      gl.deleteTexture(photo);
      photo = texture(gl, source);
    },
    setLayer: (id, artwork, mask) => {
      prints.set(id, {
        artwork: texture(gl, artwork),
        mask: mask === null ? null : texture(gl, mask),
      });
    },
    clearLayers,
    resize: (width, height) => {
      if (canvas.width === width && canvas.height === height) return;
      canvas.width = width;
      canvas.height = height;
    },
    draw: (size, look, layers) => {
      const { blend, opacity } = lookUniforms(look);
      gl.viewport(0, 0, canvas.width, canvas.height);
      bind(gl, 0, photo);
      gl.uniform2f(uniforms.size, size.w, size.h);
      gl.uniform1i(uniforms.blend, blend);
      gl.uniform1f(uniforms.opacity, opacity);
      gl.uniform1i(uniforms.print, 0);
      gl.disable(gl.BLEND);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.uniform1i(uniforms.print, 1);
      gl.enable(gl.BLEND);
      for (const layer of layers) drawPrint(size, layer);
    },
    dispose: () => {
      clearLayers();
      gl.deleteTexture(photo);
      gl.deleteTexture(none);
      gl.deleteProgram(program);
    },
  };
}

/** `null` where the browser has no WebGL 2, which the stage falls back from. */
export function createLiveRenderer(canvas: HTMLCanvasElement): LiveRenderer | null {
  const gl = canvas.getContext("webgl2", { alpha: false, antialias: false });
  return gl === null ? null : rendererOn(canvas, gl);
}
