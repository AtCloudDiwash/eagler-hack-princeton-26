import Link from "next/link";
import { ApiStatus } from "./ApiStatus";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-navy-950/90 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-3">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span aria-hidden className="grid size-7 place-items-center rounded-md bg-accent text-sm font-bold text-navy-950">
            T
          </span>
          <span className="hidden sm:inline">Turnkey Matchmaker</span>
          <span className="sm:hidden">Turnkey</span>
        </Link>
        <nav className="flex items-center gap-1 whitespace-nowrap text-sm sm:gap-3">
          <Link href="/" className="rounded-md px-2 py-1 text-ink-muted hover:text-ink">
            New search
          </Link>
          <Link href="/#recent" className="hidden rounded-md px-2 py-1 text-ink-muted hover:text-ink sm:inline">
            Recent
          </Link>
          <ApiStatus />
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-line">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-1 px-4 py-6 text-xs text-ink-muted sm:flex-row sm:justify-between">
        <p>Turnkey Matchmaker · HackPrinceton Fall 2026</p>
        <p>Estimates are ranges for planning only, not quotes or legal advice.</p>
      </div>
    </footer>
  );
}
