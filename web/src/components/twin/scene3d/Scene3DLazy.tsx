"use client";

import dynamic from "next/dynamic";
import { LoadingState } from "@/components/ui/states";

// three.js and React Three Fiber need WebGL and are large; they are loaded in the browser only, and only when the 3D view is opened.
export const Scene3D = dynamic(() => import("./Scene3D"), {
  ssr: false,
  loading: () => <LoadingState label="Loading the 3D scene" />,
});

export { CAMERA_PRESETS } from "./cameraPresets";
export type { CameraPreset } from "./cameraPresets";
