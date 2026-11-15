import { BuildingStorefrontIcon, ClipboardDocumentCheckIcon, CurrencyDollarIcon } from "@heroicons/react/24/outline";
import { BusinessProfileForm } from "@/components/BusinessProfileForm";
import { RecentAnalyses } from "@/components/RecentAnalyses";

const highlights = [
  {
    Icon: CurrencyDollarIcon,
    title: "Total cost to open",
    text: "Fit-out plus rent during build-out, as a range, not just the asking rent.",
  },
  {
    Icon: ClipboardDocumentCheckIcon,
    title: "Compliance check",
    text: "Zoning, parking, ADA, health and building code rules flagged PASS / RISK / UNKNOWN with sources.",
  },
  {
    Icon: BuildingStorefrontIcon,
    title: "Evidence you can see",
    text: "Aerial and floor-plan overlays, plus a drafted letter asking the landlord for fixes and TI.",
  },
];

export default function Home() {
  return (
    <div className="grid gap-12">
      <section className="grid items-start gap-8 lg:grid-cols-[1.1fr_1fr] lg:gap-12">
        <div className="grid gap-5 lg:pt-6">
          <p className="text-sm font-medium uppercase tracking-widest text-accent">For small business owners</p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-5xl">
            Find the space that&apos;s actually cheapest to open.
          </h1>
          <p className="text-base text-ink-muted sm:text-lg">
            A cheap lease can hide a $150k kitchen build-out. Turnkey Matchmaker compares commercial spaces by what it
            really costs to open your doors, and tells you why.
          </p>
          <ul className="grid gap-4 pt-2">
            {highlights.map(({ Icon, title, text }) => (
              <li key={title} className="flex gap-3">
                <Icon className="mt-0.5 size-6 shrink-0 text-accent" aria-hidden />
                <div>
                  <p className="font-medium">{title}</p>
                  <p className="text-sm text-ink-muted">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <BusinessProfileForm />
      </section>
      <RecentAnalyses />
    </div>
  );
}
