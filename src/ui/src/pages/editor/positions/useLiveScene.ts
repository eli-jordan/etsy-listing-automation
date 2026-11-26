import { type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  type LiveLayer,
  type LiveLook,
  type LiveRenderer,
  createLiveRenderer,
} from "./liveRenderer";

export interface LiveSource {
  photo: string;
  artwork: (placement: string | null) => string;
  /** The cloth a layer prints on, which only a Marigold template has. */
  mask: (placement: string | null) => string;
}

export interface SceneLayer extends LiveLayer {
  placement: string | null;
}

interface Args {
  source: LiveSource;
  look: LiveLook;
  layers: readonly SceneLayer[];
  size: { w: number; h: number };
  /** Canvas pixels: what the stage shows, not the photo's own size. */
  backing: { width: number; height: number };
  /** Pictures load even while false, so a first drag finds them. */
  visible: boolean;
}

function load(url: string): Promise<HTMLImageElement> {
  const image = new Image();
  image.src = url;
  return image.decode().then(() => image);
}

const optional = (url: string | null) =>
  url === null ? Promise.resolve(null) : load(url).catch(() => null);

/** A layer whose artwork fails to load is left bare, as the render leaves it. */
async function fetched(renderer: LiveRenderer, urls: SceneUrls) {
  const [photo, ...prints] = await Promise.all([
    load(urls.photo),
    ...urls.layers.map((layer) => Promise.all([optional(layer.artwork), optional(layer.mask)])),
  ]);
  return () => {
    renderer.setPhoto(photo);
    renderer.clearLayers();
    urls.layers.forEach((layer, index) => {
      const [artwork, mask] = prints[index] ?? [null, null];
      if (artwork !== null) renderer.setLayer(layer.id, artwork, mask);
    });
  };
}

interface SceneUrls {
  photo: string;
  layers: { id: string; artwork: string; mask: string | null }[];
}

function urlsOf(source: LiveSource, masked: boolean, layers: readonly SceneLayer[]): SceneUrls {
  return {
    photo: source.photo,
    layers: layers.map((layer) => ({
      id: layer.id,
      artwork: source.artwork(layer.placement),
      mask: masked ? source.mask(layer.placement) : null,
    })),
  };
}

/** `false` until the pictures load, and for good once WebGL is unavailable or its context is lost. */
export function useLiveScene(canvas: RefObject<HTMLCanvasElement | null>, args: Args): boolean {
  const { source, look, layers, size, backing, visible } = args;
  const renderer = useRef<LiveRenderer | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [lost, setLost] = useState(false);
  // A key of URLs alone: `layers` changes every frame and must not reload pictures.
  const pictures = JSON.stringify(urlsOf(source, look.kind === "marigold", layers));

  useEffect(() => {
    const element = canvas.current;
    if (element === null) return;
    const onLost = (event: Event) => {
      event.preventDefault();
      setLost(true);
    };
    element.addEventListener("webglcontextlost", onLost);
    const made = createLiveRenderer(element);
    renderer.current = made;
    return () => {
      element.removeEventListener("webglcontextlost", onLost);
      made?.dispose();
      renderer.current = null;
    };
  }, [canvas]);

  useEffect(() => {
    const made = renderer.current;
    if (made === null) return;
    let wanted = true;
    fetched(made, JSON.parse(pictures) as SceneUrls)
      .then((upload) => {
        if (!wanted) return;
        upload();
        setLoaded(pictures);
      })
      .catch(() => setLoaded(null));
    return () => {
      wanted = false;
    };
  }, [pictures]);

  const ready = loaded === pictures && !lost;

  // No deps: every pose is a new `layers`, and a frame is cheaper than diffing them.
  useLayoutEffect(() => {
    if (!ready || !visible) return;
    renderer.current?.resize(backing.width, backing.height);
    renderer.current?.draw(size, look, layers);
  });

  return ready;
}
