// Placeholder home page from the bootstrap phase. Phase 03 (prompts/03-frontend-skeleton.md)
// replaces this with the business profile form.
export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-4 px-4 py-16">
      <p className="text-sm font-medium uppercase tracking-widest text-accent">HackPrinceton Fall 2026</p>
      <h1 className="text-4xl font-semibold tracking-tight">Turnkey Matchmaker</h1>
      <p className="text-lg text-ink-muted">
        Compare commercial spaces by the total cost to open, not just the rent.
      </p>
      <p className="rounded-lg border border-line bg-surface p-4 text-sm text-ink-muted">
        Backend API docs: <code className="text-accent">http://localhost:8000/docs</code>. The profile form arrives in
        phase 03.
      </p>
    </main>
  );
}
