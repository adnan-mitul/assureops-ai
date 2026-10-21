"use client";

import { LoadingState } from "@assureops/ui/components";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useApp } from "@/lib/app-context";

export default function ReleasesRedirect() {
  const { applicationId } = useApp();
  const router = useRouter();
  const href = applicationId ? `/applications/${encodeURIComponent(applicationId)}/releases` : null;

  useEffect(() => {
    if (href) router.replace(href);
  }, [href, router]);

  if (!href) return <LoadingState label="Finding your application…" />;
  return (
    <p role="status" className="py-6 text-sm text-muted">
      Opening releases… <Link className="text-brand-700 underline" href={href}>Continue to releases</Link>
    </p>
  );
}
