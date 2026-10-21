import { CustomerShell } from "@/components/CustomerShell";

// Member pages: navigation, workspace context and the inbox. Public pages (contact, invitations) use the (public) group.
export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return <CustomerShell>{children}</CustomerShell>;
}
