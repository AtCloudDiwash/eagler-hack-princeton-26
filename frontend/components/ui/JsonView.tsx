"use client";

import { Fragment, useState } from "react";

const isEmpty = (v: unknown) => v === null || v === undefined || v === "";

export function CopyButton({ value, label = "Copy JSON" }: { value: unknown; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(typeof value === "string" ? value : JSON.stringify(value, null, 2));
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* clipboard blocked */
        }
      }}
      className="rounded-md border border-line px-2 py-0.5 text-[11px] text-slate-400 hover:border-teal-400 hover:text-teal-300"
    >
      {copied ? "Copied" : label}
    </button>
  );
}

export function RawJson({ value, maxH = "max-h-96" }: { value: unknown; maxH?: string }) {
  return (
    <pre className={`${maxH} overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/40 p-3 font-mono text-[10.5px] leading-relaxed text-slate-300`}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function formatValue(key: string, v: unknown): string {
  if (isEmpty(v)) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof v === "string" && /wkt$/i.test(key)) {
    const points = (v.match(/-?\d+\.\d+ -?\d+\.\d+/g) ?? []).length;
    return `${v.split(" ")[0]} (${points} points)`;
  }
  if (typeof v === "object") return JSON.stringify(v).slice(0, 160);
  return String(v);
}

/** Flat Vexcel-style "a.b.c" fields grouped by their first segment. */
function FieldGroups({ title, fields, showEmpty }: { title: string; fields: Record<string, unknown>; showEmpty: boolean }) {
  const groups = new Map<string, [string, unknown][]>();
  for (const [key, value] of Object.entries(fields)) {
    if (!showEmpty && isEmpty(value)) continue;
    if (typeof value === "object" && value !== null && !Array.isArray(value)) continue;
    const dot = key.indexOf(".");
    const group = dot === -1 ? "general" : key.slice(0, dot);
    const rest = dot === -1 ? key : key.slice(dot + 1);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group)!.push([rest, value]);
  }
  return (
    <div className="mt-3">
      <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-300">{title}</h4>
      {[...groups].map(([group, entries]) => (
        <div key={group} className="mb-2">
          <div className="text-[10px] uppercase tracking-wide text-teal-400/70">{group.replace(/-/g, " ")}</div>
          <dl className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-[11px]">
            {entries.map(([name, value]) => (
              <Fragment key={name}>
                <dt className="break-words text-slate-500">{name}</dt>
                <dd className={`break-words ${isEmpty(value) ? "text-slate-600" : "text-slate-200"}`}>{formatValue(name, value)}</dd>
              </Fragment>
            ))}
          </dl>
        </div>
      ))}
      {groups.size === 0 && <p className="text-[11px] text-slate-600">No populated fields.</p>}
    </div>
  );
}

/** Every field of a Vexcel GeoJSON feature: grouped table, or raw JSON. */
export function FieldExplorer({ feature }: { feature: Record<string, unknown> }) {
  const [showEmpty, setShowEmpty] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const props = (feature.properties ?? feature) as Record<string, unknown> & { structures?: Record<string, unknown>[] };
  const { structures = [], ...parcel } = props;
  const total = Object.keys(parcel).length + structures.reduce((n, s) => n + Object.keys(s).length, 0);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
        <span>{total} fields</span>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)} className="accent-teal-500" />
          Show empty
        </label>
        <button onClick={() => setShowJson((v) => !v)} className="rounded-md border border-line px-2 py-0.5 hover:border-teal-400 hover:text-teal-300">
          {showJson ? "Grouped view" : "Raw JSON"}
        </button>
        <CopyButton value={feature} />
      </div>
      {showJson ? (
        <div className="mt-2">
          <RawJson value={feature} />
        </div>
      ) : (
        <>
          <FieldGroups title="Parcel" fields={parcel} showEmpty={showEmpty} />
          {structures.map((s, i) => (
            <FieldGroups key={i} title={`Structure ${i + 1}${s["primary-structure"] === true ? " (primary)" : ""}`} fields={s} showEmpty={showEmpty} />
          ))}
        </>
      )}
    </div>
  );
}
