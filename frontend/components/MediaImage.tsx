"use client";

import { PhotoIcon } from "@heroicons/react/24/outline";
import Image from "next/image";
import { useState } from "react";

interface MediaImageProps {
  src: string | null | undefined;
  alt: string;
  /**
   * "cover" fills a fixed-aspect parent; "contain" letterboxes inside a fixed-aspect parent (whole photo
   * visible, no layout shift); "natural" keeps the image's own aspect (needed for overlays).
   */
  fit?: "cover" | "contain" | "natural";
  placeholder?: string;
  className?: string;
}

/**
 * Backend media (/static/... placeholder SVGs, cached Vexcel JPEGs, provider URLs) with a graceful
 * placeholder when the URL is missing or fails to load. Images are never run through the Next.js
 * optimizer: they're SVG placeholders or already-sized provider images, so it adds nothing.
 */
export function MediaImage({ src, alt, fit = "cover", placeholder = "No image available", className = "" }: MediaImageProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  if (!src || failedSrc === src) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 bg-navy-900 text-xs text-ink-muted ${
          fit === "natural" ? "aspect-[4/3] w-full" : "absolute inset-0"
        } ${className}`}
      >
        <PhotoIcon className="size-8" aria-hidden />
        <span>{placeholder}</span>
      </div>
    );
  }

  if (fit === "cover") {
    return (
      <Image
        src={src}
        alt={alt}
        fill
        unoptimized
        sizes="(max-width: 640px) 100vw, 33vw"
        className={`object-cover ${className}`}
        onError={() => setFailedSrc(src)}
      />
    );
  }
  if (fit === "contain") {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={alt}
        loading="lazy"
        decoding="async"
        className={`absolute inset-0 size-full object-contain ${className}`}
        onError={() => setFailedSrc(src)}
      />
    );
  }
  // Plain <img> for overlay images (cached Vexcel JPEGs, SVG placeholders): the width/height attributes
  // reserve a 4:3 box before the image loads (no layout shift) and h-auto then follows the natural
  // aspect, which the normalized overlay boxes rely on.
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      width={1200}
      height={900}
      loading="lazy"
      decoding="async"
      className={`block h-auto w-full ${className}`}
      onError={() => setFailedSrc(src)}
    />
  );
}
