"use client";

import { PhotoIcon } from "@heroicons/react/24/outline";
import Image from "next/image";
import { useState } from "react";

interface MediaImageProps {
  src: string | null | undefined;
  alt: string;
  /** "cover" fills a fixed-aspect parent; "natural" keeps the image's own aspect (needed for overlays). */
  fit?: "cover" | "natural";
  placeholder?: string;
  className?: string;
}

/**
 * Backend media (/static/... placeholder SVGs or provider URLs) with a graceful placeholder when the
 * URL is missing or fails to load. Images are served unoptimized: they're SVG placeholders or
 * third-party URLs, so the Next.js optimizer adds nothing.
 */
export function MediaImage({ src, alt, fit = "cover", placeholder = "No image available", className = "" }: MediaImageProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  if (!src || failedSrc === src) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 bg-navy-900 text-xs text-ink-muted ${
          fit === "cover" ? "absolute inset-0" : "aspect-[4/3] w-full"
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
  return (
    <Image
      src={src}
      alt={alt}
      width={1200}
      height={900}
      unoptimized
      className={`block h-auto w-full ${className}`}
      onError={() => setFailedSrc(src)}
    />
  );
}
