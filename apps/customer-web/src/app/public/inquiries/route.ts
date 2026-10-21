import { connection, type NextRequest, NextResponse } from "next/server";

// Public contact form: the one unauthenticated call this portal forwards. The API rate-limits it per client
// address, and an inquiry grants nothing until AssureOps staff convert it into a workspace and invite the contact.
export async function POST(request: NextRequest) {
  await connection();
  const body = await request.text();
  if (body.length > 6000) return NextResponse.json({ detail: { code: "too_large", message: "message too long" } }, { status: 413 });
  const upstream = await fetch(`${process.env.ASSUREOPS_API_URL}/v1/public/inquiries`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body, cache: "no-store",
  });
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
}
