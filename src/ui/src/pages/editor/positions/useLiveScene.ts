import { type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  type LiveLayer,
  type LiveLook,
  type LiveRenderer,
  createLiveRenderer,
} from "./liveRenderer";

/** The pictures a live scene is drawn from. `artwork` answers for one layer,
 * by its placement ID: a scene's layers can print different files. */
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
  /** Worth drawing now. Pictures load regardless, so a first drag finds them. */
  visible: boolean;
}

function load(url: string): Promise<HTMLImageElement> {
  const image = new Image();
  image.src = url;
  return image.decode().then(() => image);
}

const optional = (url: string | null) =>
  url === null ? Promise.resolve(null) : load(url).catch(() => null);

/** Fetches a scene's pictures and answers the upload to run if they are still
 * wanted. A layer whose artwork did not load prints nothing, as the render
 * leaves it bare. */
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

/** Draws `layers` on `canvas` as they change, and answers whether it can: `false`
 * until the pictures have loaded, and for good where WebGL is unavailable or
 * its context is lost. */
export function useLiveScene(canvas: RefObject<HTMLCanvasElement | null>, args: Args): boolean {
  const { source, look, layers, size, backing, visible } = args;
  const renderer = useRef<LiveRenderer | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [lost, setLost] = useState(false);
  // The URLs, as a key: a layer's pose changes every frame and must not
  // reload its pictures.
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

  // Every render: a pose is a new `layers`, and a frame costs far less than a
  // comparison of what changed would save.
  useLayoutEffect(() => {
    if (!ready || !visible) return;
    renderer.current?.resize(backing.width, backing.height);
    renderer.current?.draw(size, look, layers);
  });

  return ready;
}
