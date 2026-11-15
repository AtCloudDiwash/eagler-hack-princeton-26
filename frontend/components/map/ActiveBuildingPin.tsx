"use client";

/** Minimal 3D pin that slowly rotates above the building under investigation. */
export default function ActiveBuildingPin({ label = "Investigating" }: { label?: string }) {
  return (
    <div className="tk-active-pin" aria-label={label} role="img">
      <div className="tk-active-pin-orbit">
        <div className="tk-active-pin-body">
          <span className="tk-active-pin-face tk-active-pin-face-a" />
          <span className="tk-active-pin-face tk-active-pin-face-b" />
          <span className="tk-active-pin-face tk-active-pin-face-c" />
          <span className="tk-active-pin-face tk-active-pin-face-d" />
          <span className="tk-active-pin-cap" />
          <span className="tk-active-pin-tip" />
        </div>
      </div>
      <div className="tk-active-pin-stem" />
      <div className="tk-active-pin-shadow" />
      <div className="tk-active-pin-ring" />
    </div>
  );
}
