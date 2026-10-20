"use client";

import { Area, AreaChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export const RESULT_COLORS: Record<string, string> = {
  supported: "#15803d",
  failed: "#dc2626",
  review_required: "#f59e0b",
  unverified: "#9ca3af",
  stale: "#fbbf24",
  unassessed: "#e5e7eb",
};

export type DonutControl = { id: string; name: string; result: string; evidence_validity: string };

export function colorFor(c: DonutControl): string {
  if (c.result === "failed") return RESULT_COLORS.failed;
  if (c.evidence_validity === "stale") return RESULT_COLORS.stale;
  return RESULT_COLORS[c.result] ?? RESULT_COLORS.unverified;
}

export function TrendChart({ points }: { points: { label: string; support: number; coverage: number }[] }) {
  if (points.length === 0) {
    return <p className="grid h-56 place-items-center text-sm text-muted">Run an assessment to start the trend.</p>;
  }
  const last = points.at(-1)!;
  return (
    <div className="h-56" role="img" aria-label={`Evidence support ${last.support}%, coverage ${last.coverage}% after the latest assessment`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 16, right: 12, left: -16, bottom: 0 }}>
          <defs>
            <linearGradient id="supportFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#15803d" stopOpacity={0.18} />
              <stop offset="100%" stopColor="#15803d" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#eef2f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#6b7280" }} tickLine={false} axisLine={false} />
          <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: "#6b7280" }} tickLine={false} axisLine={false} />
          <Tooltip formatter={(v, name) => [`${v}%`, name]} contentStyle={{ borderRadius: 8, borderColor: "#e4ebe7", fontSize: 12 }} />
          <Legend iconType="plainline" wrapperStyle={{ fontSize: 11 }} />
          <Area name="Evidence support" type="monotone" dataKey="support" stroke="#15803d" strokeWidth={2} fill="url(#supportFill)" dot={{ r: 3, fill: "#15803d" }} isAnimationActive={false} />
          <Area name="Evidence coverage" type="monotone" dataKey="coverage" stroke="#0369a1" strokeDasharray="4 3" strokeWidth={1.5} fill="none" dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ControlDonut({ controls }: { controls: DonutControl[] }) {
  const supported = controls.filter((c) => c.result === "supported" && c.evidence_validity === "current").length;
  return (
    <div className="relative size-44 shrink-0" role="img" aria-label={`${supported} of ${controls.length} controls supported with current evidence`}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={controls.map((c) => ({ name: c.name, value: 1 }))} dataKey="value" innerRadius={52} outerRadius={80} paddingAngle={2} stroke="none" isAnimationActive={false}>
            {controls.map((c) => <Cell key={c.id} fill={colorFor(c)} />)}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
        <div>
          <p className="text-2xl font-bold">{supported}/{controls.length}</p>
          <p className="text-xs text-muted">Supported</p>
          {controls.some((c) => c.result === "unassessed") && (
            <p className="text-[10px] text-muted">{controls.filter((c) => c.result === "unassessed").length} not assessed</p>)}
        </div>
      </div>
    </div>
  );
}
