export type CameraPreset = "oblique" | "top" | "southwest" | "profile";

/** Positions are in scene kilometres (x east, y up with exaggerated altitude, z south); targets are the point the camera looks at. */
export const CAMERA_PRESETS: Record<CameraPreset, { label: string; position: [number, number, number]; target: [number, number, number] }> = {
  oblique: { label: "Oblique", position: [0, 82, 128], target: [0, 4, 0] },
  top: { label: "Top down", position: [0, 165, 0.1], target: [0, 0, 0] },
  southwest: { label: "From south-west", position: [-98, 58, 88], target: [0, 4, 0] },
  profile: { label: "Side profile", position: [0, 16, 150], target: [0, 7, 0] },
};
