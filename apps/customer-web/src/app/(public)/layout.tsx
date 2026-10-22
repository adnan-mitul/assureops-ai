// Pages for visitors and invited people who are not members yet: no member API calls, no member-only shell.
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <main id="main" className="flex-1 px-4 py-10 sm:px-8">{children}</main>;
}
