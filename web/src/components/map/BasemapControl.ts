import type { IControl } from "maplibre-gl";
import { BASEMAPS, type BasemapId } from "./basemaps";

/**
 * A small segmented control (Dark / Satellite / Relief) that lives inside the MapLibre map, so every map in the application gets it
 * without per-page code. It only reports the choice; the owner of the map applies the style.
 */
export class BasemapControl implements IControl {
  private el: HTMLDivElement | null = null;
  private buttons = new globalThis.Map<BasemapId, HTMLButtonElement>();

  constructor(private current: BasemapId, private onChange: (id: BasemapId) => void) {}

  onAdd(): HTMLElement {
    const el = document.createElement("div");
    el.className = "maplibregl-ctrl maplibregl-ctrl-group";
    el.setAttribute("role", "group");
    el.setAttribute("aria-label", "Base map");
    el.style.cssText = "display:flex;flex-direction:column;overflow:hidden;";
    for (const b of BASEMAPS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = b.label;
      btn.title = b.hint;
      btn.style.cssText = "width:auto;height:auto;padding:4px 8px;font:500 11px/1.2 system-ui,sans-serif;color:#111;text-align:left;";
      btn.addEventListener("click", () => {
        this.current = b.id;
        this.paint();
        this.onChange(b.id);
      });
      this.buttons.set(b.id, btn);
      el.appendChild(btn);
    }
    this.el = el;
    this.paint();
    return el;
  }

  onRemove(): void {
    this.el?.remove();
    this.el = null;
    this.buttons.clear();
  }

  private paint(): void {
    for (const [id, btn] of this.buttons) {
      const on = id === this.current;
      btn.setAttribute("aria-pressed", String(on));
      btn.style.background = on ? "#22d3ee" : "";
      btn.style.fontWeight = on ? "700" : "500";
    }
  }
}
